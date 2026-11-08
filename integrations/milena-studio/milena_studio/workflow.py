# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
"""Small video workflows; Concat owns the editing, undo, rendering and projects."""

import asyncio
import json
import math
import os
import re
from contextlib import asynccontextmanager
from fractions import Fraction
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

from .subtitles import read_srt

PATH_FIELDS = {"path", "file", "location", "output", "template"}
CAPTION_STYLE = {
    "fontFamily": "Hanken Grotesk", "fontSize": 0.039, "fontWeight": 700,
    "color": "#ffffff", "strokeColor": "#000000", "strokeWidth": 0.002,
    "background": "#00000080", "shadow": True, "maxWidth": 0.88,
}


class BackendError(RuntimeError):
    pass


def content(data: dict) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
        structuredContent=data, isError=False,
    )


def structured(result: CallToolResult) -> dict:
    if result.isError:
        message = " ".join(x.text for x in result.content if x.type == "text")
        raise BackendError(message or "O editor recusou a operação.")
    if isinstance(result.structuredContent, dict):
        return result.structuredContent
    for item in result.content:
        if item.type == "text":
            try:
                value = json.loads(item.text)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
    raise BackendError("O editor respondeu sem os dados esperados.")


class Workspace:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, value: str, *, exists: bool = False) -> Path:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("Use um caminho absoluto dentro da pasta de trabalho.")
        path = Path(value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("O arquivo está fora da pasta de trabalho autorizada.")
        if exists and not path.exists():
            raise ValueError(f"Arquivo ou projeto não encontrado: {path.name}")
        return path

    def guard(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in PATH_FIELDS and isinstance(item, str):
                    self.path(item)
                else:
                    self.guard(item)
        elif isinstance(value, list):
            for item in value:
                self.guard(item)

    @staticmethod
    def name(value: str) -> str:
        reserved = r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?"
        if (not isinstance(value, str) or not re.fullmatch(r"[\w .-]{1,80}", value)
                or value != value.strip() or value.endswith(".")
                or value in {".", ".."} or re.fullmatch(reserved, value, re.I)):
            raise ValueError("Use um nome simples de até 80 caracteres, sem barras.")
        return value


class Studio:
    def __init__(self, workspace: Workspace, concat: str, mode: str = "auto"):
        self.workspace = workspace
        self.concat = concat
        self.mode = mode
        self.session = None
        self.tools = []
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def connect(self):
        environment = dict(os.environ)
        # Narrow the child editor's write roots; never change HOME or global settings.
        environment["CONCAT_MCP_ROOTS"] = str(self.workspace.root)
        parameters = StdioServerParameters(
            command=self.concat, args=["--mcp", self.mode], env=environment,
        )
        async with stdio_client(parameters) as streams:
            async with ClientSession(*streams) as session:
                self.session = session
                await session.initialize()
                cursor = None
                for _ in range(100):
                    page = await session.list_tools(cursor=cursor)
                    self.tools.extend(page.tools)
                    cursor = page.nextCursor
                    if not cursor:
                        break
                else:
                    raise BackendError("O catálogo de ferramentas excedeu o limite.")
                required = {"project_create", "media_probe", "media_import", "clip_add",
                            "captions_add", "project_save", "timeline_read", "export_start"}
                missing = required - {tool.name for tool in self.tools}
                if missing:
                    raise BackendError("Esta versão do Concat não oferece: "
                                       + ", ".join(sorted(missing)))
                try:
                    yield self
                finally:
                    self.session = None
                    self.tools = []

    async def call(self, name: str, arguments: dict) -> CallToolResult:
        self.workspace.guard(arguments)
        if self.session is None:
            raise BackendError("O editor não está conectado.")
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            structured(result)
        return result

    async def forward(self, name, arguments):
        result = await self.call(name, arguments)
        # Recent projects can include unrelated personal folders. Do not disclose them.
        if name == "project_list":
            for item in result.content:
                if item.type == "text":
                    try:
                        recent = json.loads(item.text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(recent, list):
                        safe = []
                        for project in recent:
                            try:
                                self.workspace.path(project.get("path", ""))
                                safe.append(project)
                            except ValueError:
                                pass
                        return CallToolResult(content=[TextContent(
                            type="text", text=json.dumps(safe, ensure_ascii=False)
                        )], isError=False)
            raise BackendError("Não foi possível filtrar a lista de projetos.")
        return result

    async def import_srt(self, path, file, offset_seconds=0.0, save=True):
        project = self.workspace.path(path, exists=True)
        subtitle = self.workspace.path(file, exists=True)
        if not math.isfinite(offset_seconds):
            raise ValueError("O deslocamento deve ser um número finito.")
        cues = read_srt(subtitle, offset_seconds)
        timeline = structured(await self.call("timeline_read", {"path": str(project)}))
        duration = float(timeline["timeline"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Adicione um vídeo ao projeto antes das legendas.")
        if max(cue["end"] for cue in cues) > duration + 0.05:
            raise ValueError("As legendas ultrapassam o fim do vídeo; confira os tempos.")
        await self.call("captions_add", {
            "path": str(project), "captions": cues, "offsetY": 0.37,
            "style": dict(CAPTION_STYLE),
        })
        if save:
            await self.call("project_save", {"path": str(project)})
        return content({"path": str(project), "captionCount": len(cues), "saved": save})

    async def prepare_video(self, video: str, name: str, srt: str | None = None):
        source = self.workspace.path(video, exists=True)
        project_name = self.workspace.name(name)
        if not source.is_file():
            raise ValueError("O vídeo deve ser um arquivo.")
        subtitles = self.workspace.path(srt, exists=True) if srt else None
        # Validate all external input before creating a project.
        cues = read_srt(subtitles) if subtitles else None
        probe = structured(await self.call("media_probe", {"path": str(source)}))
        picture = probe.get("video")
        duration = probe.get("duration")
        if not picture or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            raise ValueError("O arquivo precisa ter vídeo e duração válidos.")
        if cues and max(cue["end"] for cue in cues) > duration + 0.05:
            raise ValueError("As legendas ultrapassam o fim do vídeo.")
        rate = Fraction(picture["frameRateFraction"])
        if rate <= 0 or rate > 240:
            raise ValueError("Taxa de quadros inválida para este fluxo.")
        settings = {"width": picture["width"], "height": picture["height"],
                    "rateNum": rate.numerator, "rateDen": rate.denominator}
        parent = self.workspace.root / "projects"
        parent.mkdir(exist_ok=True)
        project = parent / project_name
        if project.exists():
            raise ValueError("Já existe um projeto com esse nome. Escolha outro.")
        await self.call("project_create", {"location": str(parent), "name": project_name,
                                           "video": settings})
        try:
            imported = structured(await self.call("media_import", {
                "path": str(project), "file": str(source),
            }))
            await self.call("clip_add", {
                "path": str(project), "mediaId": imported["createdId"],
                "trackId": imported["timeline"]["tracks"][0]["id"], "start": 0,
            })
            if cues:
                await self.call("captions_add", {
                    "path": str(project), "captions": cues, "offsetY": 0.37,
                    "style": dict(CAPTION_STYLE),
                })
            saved = structured(await self.call("project_save", {"path": str(project)}))
        except Exception as error:
            raise BackendError(f"O projeto parcial ficou em {project}. "
                               f"Nenhum arquivo original foi removido. {error}") from error
        return content({"path": str(project), "video": settings,
                        "captionCount": len(cues or []), "summary": saved})

    async def export_video(self, path: str, filename: str):
        project = self.workspace.path(path, exists=True)
        self.workspace.name(filename)
        if Path(filename).suffix.lower() != ".mp4":
            raise ValueError("O nome de saída deve terminar em .mp4.")
        folder = self.workspace.root / "exports"
        folder.mkdir(exist_ok=True)
        output = self.workspace.path(str(folder / filename))
        if output.exists():
            raise ValueError("Essa exportação já existe. Escolha outro nome.")
        await self.call("project_save", {"path": str(project)})
        return await self.call("export_start", {
            "path": str(project), "output": str(output),
            "codec": "h264", "crf": 23, "preset": "veryfast",
        })
