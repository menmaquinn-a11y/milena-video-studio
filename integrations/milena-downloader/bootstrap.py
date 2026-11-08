# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
"""Install the pinned official Deno binary, verifying its release SHA-256."""
import hashlib
import io
import os
import sys
import urllib.request
import zipfile
from pathlib import Path
from app import BASE, ffmpeg_path, runtime

DENO_URL = "https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-pc-windows-msvc.zip"
DENO_SHA256 = "cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf"


def install():
    print("Preparando FFmpeg para exportar MP4...", flush=True)
    ffmpeg_path()
    if runtime():
        print("Suporte JavaScript: pronto.")
        return
    if os.name != "nt":
        raise RuntimeError("Instale Deno 2.3+ ou Node.js 22+ e execute novamente.")
    print("Baixando Deno 2.9.8 da distribuicao oficial do projeto...", flush=True)
    request = urllib.request.Request(DENO_URL, headers={"User-Agent": "MilenaDownloader/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(150 * 1024 * 1024 + 1)
    if len(raw) > 150 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != DENO_SHA256:
        raise RuntimeError("A verificacao do download falhou. Nenhum executavel foi instalado.")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entry = archive.getinfo("deno.exe")
        if entry.file_size > 200 * 1024 * 1024:
            raise RuntimeError("Arquivo inesperado na distribuicao.")
        target = BASE / ".runtime" / "deno.exe"
        target.parent.mkdir(exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(archive.read(entry))
        temporary.replace(target)
    if not runtime():
        raise RuntimeError("Deno foi baixado, mas nao foi possivel executa-lo.")
    print("Deno verificado e instalado somente na pasta deste projeto.")


if __name__ == "__main__":
    try:
        install()
    except Exception as error:
        print(f"Falha na preparacao: {error}", file=sys.stderr)
        raise SystemExit(1)
