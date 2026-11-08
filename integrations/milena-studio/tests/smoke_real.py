# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
"""Opt-in end-to-end test using an installed Concat and FFmpeg, never user media."""
import argparse
import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from milena_studio.workflow import structured


async def smoke(concat, workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    source = workspace / "source.mp4"
    subtitle = workspace / "ptbr.srt"
    if source.exists() or (workspace / "projects").exists():
        raise ValueError("Use uma pasta nova e vazia para o teste.")
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x234056:s=320x180:r=30000/1001:d=2", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source)], check=True)
    subtitle.write_text("1\n00:00:00,100 --> 00:00:01,800\nOlá! Legenda em PT-BR.\n", encoding="utf-8")
    params = StdioServerParameters(command=sys.executable, args=["-m", "milena_studio.server",
        "--concat", concat, "--workspace", str(workspace), "--mode", "headless"])
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as client:
            await client.initialize()
            health = structured(await client.call_tool("studio_health", {}))
            project = structured(await client.call_tool("studio_prepare_video", {
                "video": str(source), "name": "smoke-ptbr", "srt": str(subtitle)}))
            frame = await client.call_tool("preview_frame", {"path": project["path"], "time": 1})
            images = [item for item in frame.content if item.type == "image"]
            if not images:
                raise AssertionError(frame)
            (workspace / "preview.png").write_bytes(base64.b64decode(images[0].data))
            job = structured(await client.call_tool("studio_export_video", {
                "path": project["path"], "filename": "ptbr.mp4"}))
            result = structured(await client.call_tool("export_wait", {"job": job["job"], "timeoutSeconds": 45}))
            print(json.dumps({"tools": health["tools"], "project": project, "export": result}, ensure_ascii=False))
    output = workspace / "exports" / "ptbr.mp4"
    metadata = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
        "-show_format", "-of", "json", str(output)]))
    video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (320, 180, "30000/1001"), video
    assert any(stream["codec_type"] == "audio" for stream in metadata["streams"])
    assert 1.9 <= float(metadata["format"]["duration"]) <= 2.2, metadata["format"]
    print("PASS: MCP → Concat → legendas → prévia → MP4 com áudio, resolução e FPS preservados.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--concat", required=True)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(smoke(args.concat, args.workspace.resolve()))
