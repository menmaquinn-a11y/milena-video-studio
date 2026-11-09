# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
import base64
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import httpx

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, ImageContent, TextContent, Tool

from milena_studio.server import make_http_app, make_server
from milena_studio.subtitles import parse_srt, read_srt
from milena_studio.workflow import BackendError, Studio, Workspace, content, structured

SRT = "1\n00:00:00,100 --> 00:00:01,500\nOlá, <b>vídeo</b>!\nSegunda linha &amp; ação.\n"


class SubtitleTests(unittest.TestCase):
    def test_unicode_bom_crlf_multiline_and_offset(self):
        cues = parse_srt("\ufeff" + SRT.replace("\n", "\r\n"), .5)
        self.assertEqual(cues, [{"start": .6, "end": 2.,
                                "text": "Olá, vídeo!\nSegunda linha & ação."}])

    def test_invalid_timing_text_and_offset(self):
        for value in ["", SRT.replace("01,500", "00,050"),
                      SRT.replace("00:00:00,100", "00:99:00,100"),
                      SRT.replace("Olá, <b>vídeo</b>!", "\x00")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_srt(value)
        for offset in [-1, float("nan"), float("inf")]:
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                parse_srt(SRT, offset)

    def test_rejects_out_of_order_but_allows_overlap(self):
        second = "2\n00:00:00,200 --> 00:00:01,700\nDuas vozes."
        self.assertEqual(len(parse_srt(SRT + "\n" + second)), 2)
        with self.assertRaises(ValueError):
            parse_srt(second + "\n\n" + SRT)

    def test_rejects_non_utf8(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sub.srt"
            path.write_bytes(SRT.encode("cp1252"))
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                read_srt(path)


class FakeEditor:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.image = CallToolResult(content=[ImageContent(
            type="image", data=base64.b64encode(b"preview").decode(), mimeType="image/png")])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == self.fail:
            return CallToolResult(content=[TextContent(type="text", text="Falha de renderização")], isError=True)
        if name == "media_probe":
            return content({"duration": 2, "video": {"width": 320, "height": 180,
                                                       "frameRateFraction": "30000/1001"}})
        if name == "project_create":
            (Path(arguments["location"]) / arguments["name"]).mkdir()
        if name == "preview_frame":
            return self.image
        return content({"createdId": "media-1", "timeline": {
            "duration": 2, "tracks": [{"id": "track-1"}]}})


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(Workspace(self.root), "unused")
        self.editor = FakeEditor()
        self.studio.session = self.editor
        self.video = self.root / "source.mp4"
        self.video.write_bytes(b"original")
        self.srt = self.root / "ptbr.srt"
        self.srt.write_text(SRT, encoding="utf-8")

    async def test_prepare_preserves_source_and_fractional_frame_rate(self):
        result = structured(await self.studio.prepare_video(str(self.video), "ILLIT", str(self.srt)))
        self.assertEqual(result["video"], {"width": 320, "height": 180,
                                          "rateNum": 30000, "rateDen": 1001})
        self.assertEqual(result["captionCount"], 1)
        self.assertEqual(self.video.read_bytes(), b"original")
        self.assertEqual([n for n, _ in self.editor.calls], ["media_probe", "project_create",
                         "media_import", "clip_add", "captions_add", "project_save"])

    async def test_invalid_srt_does_not_create_project_or_edit(self):
        self.srt.write_text(SRT + "\n2\nBAD TIMING\nTexto", encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.studio.prepare_video(str(self.video), "ILLIT", str(self.srt))
        self.assertEqual(self.editor.calls, [])
        self.srt.write_text(SRT.replace("01,500", "09,500"), encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.studio.prepare_video(str(self.video), "ILLIT", str(self.srt))
        self.assertEqual([n for n, _ in self.editor.calls], ["media_probe"])

    async def test_import_validates_entire_file_before_mutation(self):
        self.srt.write_text(SRT.replace("01,500", "09,500"), encoding="utf-8")
        with self.assertRaises(ValueError):
            await self.studio.import_srt(str(self.root), str(self.srt))
        self.assertEqual([n for n, _ in self.editor.calls], ["timeline_read"])

    async def test_failure_keeps_original_and_identifies_partial_project(self):
        self.editor.fail = "media_import"
        with self.assertRaisesRegex(BackendError, "projeto parcial"):
            await self.studio.prepare_video(str(self.video), "ILLIT")
        self.assertTrue((self.root / "projects" / "ILLIT").is_dir())
        self.assertEqual(self.video.read_bytes(), b"original")

    async def test_refuses_overwrite_and_unsafe_paths(self):
        exports = self.root / "exports"
        exports.mkdir()
        existing = exports / "final.mp4"
        existing.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            await self.studio.export_video(str(self.root), "final.mp4")
        self.assertEqual(existing.read_bytes(), b"keep")
        with self.assertRaises(ValueError):
            await self.studio.forward("media_import", {"path": str(self.root),
                                                      "file": str(self.root.parent / "secret")})
        for name in ["../other", "CON.mp4", "NUL", "bad/thing", "..", " final"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                Workspace.name(name)
        self.assertEqual(self.editor.calls, [])

    async def test_symlink_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as outside:
            link = self.root / "outside"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation unavailable for this Windows account")
            with self.assertRaises(ValueError):
                self.studio.workspace.guard({"nested": [{"output": str(link / "video.mp4")}]})

    async def test_mcp_protocol_lists_tools_preserves_images_and_reports_errors(self):
        self.studio.tools = [Tool(name="preview_frame", inputSchema={"type": "object"}),
                             Tool(name="media_import", inputSchema={"type": "object"})]
        async with create_connected_server_and_client_session(make_server(self.studio)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            self.assertTrue({"studio_prepare_video", "studio_import_srt", "preview_frame"} <= names)
            preview = await client.call_tool("preview_frame", {"path": str(self.root), "time": 0})
            self.assertEqual(preview.content[0].type, "image")
            invalid = await client.call_tool("studio_prepare_video", {"video": str(self.video)})
            self.assertTrue(invalid.isError)
            outside = await client.call_tool("media_import", {"file": str(self.root.parent / "secret")})
            self.assertTrue(outside.isError)

    async def test_recent_projects_filtered(self):
        async def recent(name, arguments):
            return CallToolResult(content=[TextContent(type="text", text=json.dumps([
                {"path": str(self.root / "ours")}, {"path": str(self.root.parent / "other")}
            ]))])
        self.editor.call_tool = recent
        result = await self.studio.forward("project_list", {})
        self.assertEqual(json.loads(result.content[0].text), [{"path": str(self.root / "ours")}])

    async def test_http_reconnections_do_not_exhaust_sessions(self):
        @asynccontextmanager
        async def connected_editor():
            yield

        app = make_http_app(self.studio)
        headers = {"Accept": "application/json, text/event-stream"}
        with patch.object(self.studio, "connect", connected_editor):
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                            base_url="http://127.0.0.1:8765",
                                            headers=headers) as client:
                    for i in range(12):
                        response = await client.post("/mcp", json={
                            "jsonrpc": "2.0", "id": i * 2,
                            "method": "initialize", "params": {
                                "protocolVersion": "2025-11-25", "capabilities": {},
                                "clientInfo": {"name": "tunnel-reconnect", "version": "test"}}})
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertNotIn("mcp-session-id", response.headers)
                        # Calls must also work without a retained initialize session,
                        # while the same editor connection remains alive.
                        response = await client.post("/mcp", json={
                            "jsonrpc": "2.0", "id": i * 2 + 1,
                            "method": "tools/call", "params": {
                                "name": "studio_health", "arguments": {}}})
                        self.assertEqual(response.status_code, 200, response.text)
                        result = response.json()["result"]
                        self.assertFalse(result.get("isError", False), result)
                        self.assertEqual(json.loads(result["content"][0]["text"])["workspace"],
                                         str(self.root))
        self.assertEqual(sum(name == "concat_version" for name, _ in self.editor.calls), 12)


if __name__ == "__main__":
    unittest.main()
