# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional offline RVC voice conversion for the existing Milena/Concat bridge.

Models and all resulting media remain in the configured workspace.
RVC is executed from an explicitly configured local installation, never
from an executable path supplied over MCP. No shell is used.
"""
import asyncio
import json
import os
import re
import uuid
from pathlib import Path

from .workflow import content

VOICE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
AUDIO_FORMATS = {".wav", ".flac", ".mp3"}


class VoiceBridge:
    def __init__(self, workspace):
        self.workspace = workspace
        self.jobs = {}
        self.busy = asyncio.Lock()

    @property
    def folder(self):
        return self.workspace.root / "voices" / "rvc"

    def model(self, name):
        if not isinstance(name, str) or not VOICE_ID.fullmatch(name):
            raise ValueError("Escolha um identificador simples de voz do catálogo.")
        path = (self.folder / (name + ".pth")).resolve()
        if not path.is_relative_to(self.folder.resolve()) or not path.is_file():
            raise ValueError("Voz RVC não encontrada no catálogo.")
        return path

    def inventory(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        voices = []
        for path in sorted(self.folder.glob("*.pth")):
            if not VOICE_ID.fullmatch(path.stem) or path.is_symlink():
                continue
            license_path = path.with_suffix(".json")
            details = {}
            if license_path.is_file() and license_path.stat().st_size < 32_000:
                try:
                    value = json.loads(license_path.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        details = value
                except (OSError, ValueError):
                    pass
            voices.append({
                "id": path.stem,
                "displayName": str(details.get("display_name", path.stem))[:100],
                "hasIndex": path.with_suffix(".index").is_file(),
                "commercialUseRecorded": details.get("commercial_use") is True,
                "consentRecorded": details.get("voice_owner_consent") is True,
            })
        root = Path(os.environ.get("MILENA_RVC_HOME", ""))
        py = Path(os.environ.get("MILENA_RVC_PYTHON", ""))
        configured = bool(os.environ.get("MILENA_RVC_HOME")
                          and os.environ.get("MILENA_RVC_PYTHON")
                          and (root / "infer" / "cli.py").is_file()
                          and py.is_file())
        return content({"voices": voices, "runtimeConfigured": configured,
                        "modelFolder": str(self.folder),
                        "note": "Modelos .pth podem executar código ao carregar. Use somente fontes confiáveis e com consentimento/licença."})

    def status(self, job):
        if job not in self.jobs:
            raise ValueError("Trabalho de voz não encontrado nesta sessão.")
        return content(dict(self.jobs[job]))

    async def start(self, source, voice, pitch=0, index_rate=0.75, rights_confirmed=False):
        if rights_confirmed is not True:
            raise ValueError("Confirme os direitos de clonagem e uso do modelo antes de converter.")
        audio = self.workspace.path(source, exists=True)
        if not audio.is_file() or audio.suffix.lower() not in AUDIO_FORMATS:
            raise ValueError("Informe um áudio de origem WAV, FLAC ou MP3 da pasta de trabalho.")
        model = self.model(voice)
        if not isinstance(pitch, int) or isinstance(pitch, bool) or not -12 <= pitch <= 12:
            raise ValueError("Pitch precisa estar entre -12 e 12 semitons.")
        if not isinstance(index_rate, (float, int)) or isinstance(index_rate, bool) or not 0 <= index_rate <= 1:
            raise ValueError("Index rate precisa estar entre 0 e 1.")
        root_s = os.environ.get("MILENA_RVC_HOME")
        python_s = os.environ.get("MILENA_RVC_PYTHON")
        if not root_s or not python_s:
            raise ValueError("Configure MILENA_RVC_HOME e MILENA_RVC_PYTHON no serviço local.")
        root = Path(root_s).expanduser().resolve()
        python = Path(python_s).expanduser().resolve()
        script = root / "infer" / "cli.py"
        if not script.is_file() or not python.is_file():
            raise ValueError("Instalação RVC não localizada; confira as variáveis locais.")
        if self.busy.locked():
            raise ValueError("Já existe uma conversão RVC em execução.")
        output_dir = self.workspace.root / "audio" / "voices"
        output_dir.mkdir(parents=True, exist_ok=True)
        job = uuid.uuid4().hex
        output = output_dir / ("rvc_" + job + ".wav")
        index = model.with_suffix(".index")
        command = [str(python), str(script), "--model", str(model),
                   "--input", str(audio), "--output", str(output),
                   "--pitch", str(pitch), "--f0-method", "rmvpe",
                   "--index-rate", str(index_rate if index.is_file() else 0),
                   "--format", "wav"]
        if index.is_file():
            command += ["--index", str(index)]
        self.jobs[job] = {"job": job, "state": "queued", "voice": voice, "output": None}
        asyncio.create_task(self._execute(job, command, root, output))
        return content({"job": job, "state": "queued",
                        "next": "Consulte studio_rvc_status até a saída ficar pronta."})

    async def _execute(self, job, command, cwd, output):
        async with self.busy:
            self.jobs[job]["state"] = "running"
            try:
                process = await asyncio.create_subprocess_exec(
                    *command, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                try:
                    out, err = await asyncio.wait_for(process.communicate(), timeout=1200)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.communicate()
                    raise RuntimeError("Conversão excedeu 20 minutos.")
                if process.returncode != 0:
                    detail = (err or out).decode("utf-8", "replace")[-1200:]
                    raise RuntimeError("RVC falhou: " + detail)
                if not output.is_file() or output.stat().st_size == 0:
                    raise RuntimeError("RVC terminou sem criar WAV válido.")
                self.jobs[job].update(state="done", output=str(output))
            except Exception as error:
                self.jobs[job].update(state="failed", error=str(error)[:1500])
            finally:
                if len(self.jobs) > 100:
                    for old in list(self.jobs)[:-50]:
                        self.jobs.pop(old, None)
