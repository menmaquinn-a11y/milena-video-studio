# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
"""MCP server: forwards Concat tools and adds a small PT-BR editing workflow."""

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from . import __version__
from .workflow import Studio, Workspace, content
from .voice import VoiceBridge

INSTRUCTIONS = (
    "Edite vídeos na pasta de trabalho configurada. Comece por studio_health e "
    "studio_prepare_video; studio_import_srt importa a tradução já revisada. "
    "Preserve o idioma, formato e duração pedidos pelo usuário. Veja timeline_read "
    "e preview_frame antes de exportar. studio_export_video inicia um job: acompanhe "
    "com export_status ou export_wait e confira o arquivo final. Salve o projeto. "
    "A conexão não publica vídeos e não gera traduções ou vozes sozinha."
)


def schema(properties, required):
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


STRING = {"type": "string"}
LOCAL_TOOLS = [
    Tool(name="studio_health", title="Verificar conexão do estúdio",
         description="Confere a versão do editor, o modo de conexão e a pasta de trabalho.",
         inputSchema=schema({}, []),
         annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=False)),
    Tool(name="studio_prepare_video", title="Preparar vídeo com legendas",
         description="Cria um projeto novo, preservando resolução e taxa de quadros do vídeo. "
                     "Importa um SRT UTF-8 opcional com estilo PT-BR e salva o projeto. "
                     "Os arquivos precisam estar na pasta de trabalho; não traduz o texto.",
         inputSchema=schema({"video": STRING, "name": STRING,
                             "srt": {"type": ["string", "null"], "default": None}},
                            ["video", "name"]),
         annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                     idempotentHint=False, openWorldHint=False)),
    Tool(name="studio_import_srt", title="Importar legendas em PT-BR",
         description="Valida um SRT UTF-8 inteiro antes de adicionar as legendas em uma "
                     "única etapa desfazível. Não apaga legendas anteriores. O SRT não "
                     "pode ultrapassar a duração do projeto; save grava o projeto.",
         inputSchema=schema({"path": STRING, "file": STRING,
                             "offset_seconds": {"type": "number", "default": 0},
                             "save": {"type": "boolean", "default": True}}, ["path", "file"]),
         annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                     idempotentHint=False, openWorldHint=False)),
    Tool(name="studio_export_video", title="Exportar vídeo legendado",
         description="Salva e inicia uma exportação MP4 H.264, CRF 23 e preset veryfast, "
                     "mantendo resolução e taxa de quadros do projeto. O arquivo fica "
                     "em exports; recusa nomes já existentes. Retorna job para export_status.",
         inputSchema=schema({"path": STRING, "filename": STRING}, ["path", "filename"]),
         annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                     idempotentHint=False, openWorldHint=False)),

    Tool(name="studio_rvc_voices", title="Listar vozes locais RVC",
         description="Lista modelos RVC .pth dentro de voices/rvc da pasta de trabalho; "
                     "não carrega modelos e informa se o motor RVC está configurado.",
         inputSchema=schema({}, []),
         annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=False)),
    Tool(name="studio_rvc_start", title="Converter narração com voz RVC",
         description="Inicia conversão RVC local de um WAV/FLAC/MP3 autorizado para voz .pth. "
                     "Confirme consentimento e direitos de uso comercial; retorna job, "
                     "não importa automaticamente áudio na timeline.",
         inputSchema=schema({"source": STRING, "voice": STRING,
                             "pitch": {"type": "integer", "default": 0},
                             "index_rate": {"type": "number", "default": 0.75},
                             "rights_confirmed": {"type": "boolean"}},
                            ["source", "voice", "rights_confirmed"]),
         annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                     idempotentHint=False, openWorldHint=False)),
    Tool(name="studio_rvc_status", title="Status da conversão RVC",
         description="Consulta estado de job RVC, incluindo caminho do WAV quando concluído.",
         inputSchema=schema({"job": STRING}, ["job"]),
         annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                     idempotentHint=True, openWorldHint=False)),
]


def make_server(studio):
    voice_bridge = VoiceBridge(studio.workspace)
    server = Server("milena-video-studio", version=__version__, instructions=INSTRUCTIONS)

    @server.list_tools()
    async def list_tools():
        names = {tool.name for tool in LOCAL_TOOLS}
        return [tool for tool in studio.tools if tool.name not in names] + LOCAL_TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        async with studio.lock:
            try:
                if name == "studio_health":
                    version = await studio.call("concat_version", {})
                    return content({"workspace": str(studio.workspace.root),
                                    "tools": len(studio.tools),
                                    "editor": version.model_dump(mode="json", exclude_none=True)})
                if name == "studio_prepare_video":
                    return await studio.prepare_video(**arguments)
                if name == "studio_import_srt":
                    return await studio.import_srt(**arguments)
                if name == "studio_export_video":
                    return await studio.export_video(**arguments)
                if name == "studio_rvc_voices":
                    return voice_bridge.inventory()
                if name == "studio_rvc_start":
                    return await voice_bridge.start(**arguments)
                if name == "studio_rvc_status":
                    return voice_bridge.status(**arguments)
                if name not in {tool.name for tool in studio.tools}:
                    raise ValueError("Ferramenta não disponível no editor conectado.")
                return await studio.forward(name, arguments)
            except Exception as error:
                logging.getLogger(__name__).warning("%s: %s", name, error)
                return CallToolResult(content=[TextContent(type="text", text=str(error))],
                                      isError=True)

    return server


async def run_stdio(studio):
    server = make_server(studio)
    async with studio.connect():
        async with stdio_server() as streams:
            await server.run(*streams, server.create_initialization_options())


def make_http_app(studio):
    """Keep editor state in Studio, without retaining HTTP client sessions."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    server = make_server(studio)
    manager = StreamableHTTPSessionManager(
        # Tunnel clients may reconnect without closing their previous session.
        # Project state and edit serialization already belong to Studio; HTTP
        # sessions only retain idle streams and eventually reject new clients.
        app=server, json_response=True, stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

    class MCP:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    @asynccontextmanager
    async def lifespan(app):
        async with studio.connect():
            async with manager.run():
                yield

    async def health(request):
        return JSONResponse({"service": "milena-video-studio", "version": __version__})

    return Starlette(routes=[Route("/mcp", MCP(), methods=["GET", "POST", "DELETE"]),
                            Route("/health", health)], lifespan=lifespan)


async def run_http(studio, port):
    """Loopback only. For ChatGPT web use an authenticated tunnel, not a public bind."""
    import uvicorn
    await uvicorn.Server(uvicorn.Config(make_http_app(studio), host="127.0.0.1", port=port,
                                      log_level="warning")).serve()


def main():
    parser = argparse.ArgumentParser(description="Milena Video Studio: conexão local com o Concat")
    parser.add_argument("--concat", required=True, help="Caminho do executável oficial do Concat")
    parser.add_argument("--workspace", type=Path, required=True,
                        help="Pasta autorizada para vídeos, legendas, projetos e exportações")
    parser.add_argument("--mode", choices=["auto", "headless", "window"], default="auto")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("A porta deve ficar entre 1024 e 65535.")
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING,
                        format="milena-studio: %(levelname)s: %(message)s")
    studio = Studio(Workspace(args.workspace), args.concat, args.mode)
    try:
        asyncio.run(run_stdio(studio) if args.transport == "stdio"
                    else run_http(studio, args.port))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        logging.error("Falha ao conectar ao editor: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
