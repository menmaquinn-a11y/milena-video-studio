# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
"""Loopback-only video downloader. No accounts, cloud storage, or browser cookies."""
import argparse
import hashlib
import http.cookies
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

BASE = Path(__file__).resolve().parent
MAX_BYTES = 2 * 1024**3
QUALITIES = {"720": 720, "1080": 1080, "original": None}
TERMINAL = {"done", "error", "cancelled"}


def video_url(raw):
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2048:
        raise ValueError("Cole um link de vídeo do YouTube ou TikTok.")
    value = raw.strip()
    if "://" not in value:
        value = "https://" + value
    try:
        url = urlsplit(value)
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443):
            raise ValueError()
        host = url.hostname or ""
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            identifier = parse_qs(url.query).get("v", [""])[0] if url.path == "/watch" else ""
            match = re.fullmatch(r"/(?:shorts|live|embed)/([\w-]{11})/?", url.path)
            if match:
                identifier = match[1]
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
                raise ValueError()
            return "https://www.youtube.com/watch?v=" + identifier, "YouTube"
        if host in {"youtu.be", "www.youtu.be"}:
            identifier = url.path.strip("/")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
                raise ValueError()
            return "https://www.youtube.com/watch?v=" + identifier, "YouTube"
        if host in {"tiktok.com", "www.tiktok.com", "m.tiktok.com"}:
            if re.fullmatch(r"/@[A-Za-z0-9_.]{1,40}/video/\d{10,25}/?", url.path):
                return urlunsplit(("https", "www.tiktok.com", url.path, "", "")), "TikTok"
            if re.fullmatch(r"/t/[A-Za-z0-9]{4,40}/?", url.path):
                return urlunsplit(("https", "www.tiktok.com", url.path, "", "")), "TikTok"
        if host in {"vm.tiktok.com", "vt.tiktok.com"} and re.fullmatch(r"/[A-Za-z0-9]{4,40}/?", url.path):
            return urlunsplit(("https", host, url.path, "", "")), "TikTok"
    except (ValueError, TypeError):
        pass
    raise ValueError("Use um link de um vídeo específico do YouTube ou TikTok. Perfis, playlists e outros sites não são aceitos.")


def runtime():
    choices = [("deno", BASE / ".runtime" / ("deno.exe" if os.name == "nt" else "deno")),
               ("deno", shutil.which("deno")), ("node", shutil.which("node"))]
    for name, executable in choices:
        if not executable or not Path(executable).is_file():
            continue
        try:
            version = subprocess.check_output([str(executable), "--version"], timeout=5, text=True)
            number = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
            minimum = (2, 3, 0) if name == "deno" else (22, 0, 0)
            if number and tuple(map(int, number.groups())) >= minimum:
                return name, str(executable)
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def ffmpeg_path():
    import imageio_ffmpeg
    source = Path(imageio_ffmpeg.get_ffmpeg_exe())
    target = BASE / ".runtime" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    target.parent.mkdir(exist_ok=True)
    if not target.exists() or target.stat().st_size != source.stat().st_size:
        shutil.copy2(source, target)
        target.chmod(0o755)
    return str(target)


def emit(event):
    print(json.dumps(event, ensure_ascii=False), flush=True)


def within_resolution(format_info, limit):
    if not limit or format_info.get("vcodec") == "none":
        return True
    dimensions = [format_info.get(key) for key in ("width", "height")]
    known = [value for value in dimensions if isinstance(value, (int, float)) and value > 0]
    return not known or min(known) <= limit


def download_worker(url, quality, folder):
    from yt_dlp import YoutubeDL
    url, platform = video_url(url)
    js = runtime()
    if platform == "YouTube" and not js:
        raise ValueError("O suporte JavaScript do YouTube não está instalado. Execute INICIAR_WINDOWS.cmd novamente.")
    destination = Path(folder).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    limit = QUALITIES[quality]
    selector = None

    def format_selector(context):
        scoped = dict(context)
        scoped["formats"] = [item for item in context["formats"] if within_resolution(item, limit)]
        yield from selector(scoped)

    def check_video(info, *, incomplete):
        if info.get("is_live") or info.get("live_status") == "is_live":
            return "Transmissões ao vivo não são suportadas."
        if (info.get("duration") or 0) > 7200:
            return "O limite é de duas horas por vídeo."
        if (info.get("filesize") or info.get("filesize_approx") or 0) > MAX_BYTES:
            return "O limite é de 2 GB por arquivo."
        if info.get("title"):
            emit({"state": "checking", "title": info["title"][:240], "duration": info.get("duration")})
        return None

    def progress(data):
        if data["status"] == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            received = data.get("downloaded_bytes", 0)
            emit({"state": "downloading", "bytes": received, "total": total,
                  "percent": min(99, received / total * 100) if total else None,
                  "speed": data.get("speed"), "eta": data.get("eta")})
            if received > MAX_BYTES:
                raise ValueError("O download excedeu o limite de 2 GB.")
        elif data["status"] == "finished":
            emit({"state": "processing", "percent": None})

    class Logger:
        def debug(self, message):
            pass
        def warning(self, message):
            pass
        def error(self, message):
            pass

    options = {
        "format": format_selector, "merge_output_format": "mp4", "noplaylist": True,
        "outtmpl": str(destination / "%(title).100B [%(id)s].%(ext)s"),
        "restrictfilenames": True, "windowsfilenames": True,
        "max_filesize": MAX_BYTES, "socket_timeout": 20, "retries": 2, "fragment_retries": 2,
        "concurrent_fragment_downloads": 1, "overwrites": False, "cachedir": False,
        "quiet": True, "no_warnings": True, "logger": Logger(),
        "match_filter": check_video, "progress_hooks": [progress],
        "ffmpeg_location": ffmpeg_path(), "remote_components": [],
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
    }
    if js:
        options["js_runtimes"] = {js[0]: {"path": js[1]}}
    from yt_dlp.extractor import get_info_extractor
    with YoutubeDL(options, auto_init=False) as ydl:
        selector = ydl.build_format_selector("bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b")
        for name in ("Youtube", "TikTok", "TikTokVM"):
            ydl.add_info_extractor(get_info_extractor(name)())
        # The accepted input is canonicalized above. Never enable generic URL extraction.
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise ValueError("O vídeo foi recusado pelo limite de duração, tamanho ou transmissão ao vivo.")
        paths = [p for p in destination.glob("*.mp4") if p.is_file()]
        if len(paths) != 1:
            raise ValueError("O vídeo não foi finalizado em MP4. A plataforma pode ter bloqueado o download.")
        emit({"state": "complete", "filename": paths[0].name, "title": info.get("title", "Vídeo")[:240]})


def user_error(message):
    lower = message.lower()
    if any(word in lower for word in ("sign in", "login", "cookies", "private video", "age-restricted", "age restricted", "confirm your age", "not a bot")):
        return "A plataforma pediu login ou verificação para este vídeo. O baixador não acessa suas contas. Tente outro vídeo público."
    if any(word in lower for word in ("403", "429", "blocked", "captcha", "unable to extract", "failed to extract")):
        return "A plataforma bloqueou este download ou mudou o formato do link. Tente outro vídeo público ou atualize o extrator."
    if any(word in lower for word in ("network", "timeout", "timed out", "resolve", "connection")):
        return "Não foi possível alcançar a plataforma. Confira a internet e tente novamente."
    if any(word in lower for word in ("2 gb", "duas horas", "ao vivo", "javascript", "ffmpeg")):
        return message[:400]
    return "Não foi possível concluir este vídeo. Ele pode estar indisponível, restrito ou em um formato ainda não suportado."


class Downloads:
    def __init__(self, destination, worker_factory=None):
        self.destination = Path(destination).resolve()
        self.destination.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.worker_factory = worker_factory
        self.processes = {}
        self.closing = False

    def list(self):
        with self.lock:
            return [dict(value) for value in reversed(list(self.jobs.values()))]

    def submit(self, raw, quality):
        url, platform = video_url(raw)
        if quality not in QUALITIES:
            raise ValueError("Escolha 720p, 1080p ou a qualidade original.")
        with self.lock:
            if self.closing:
                raise ValueError("O baixador está encerrando.")
            pending = [j for j in self.jobs.values() if j["state"] not in TERMINAL]
            if any(j.get("fingerprint") == hashlib.sha256((url + quality).encode()).hexdigest() for j in pending):
                raise ValueError("Esse vídeo já está na fila.")
            if len(pending) >= 4:
                raise ValueError("A fila está cheia. Aguarde um download terminar.")
            # History is RAM-only, capped, and never contains source URLs.
            for old in list(self.jobs):
                if len(self.jobs) < 24:
                    break
                if self.jobs[old]["state"] in TERMINAL:
                    del self.jobs[old]
            key = uuid.uuid4().hex
            self.jobs[key] = {"id": key, "platform": platform, "title": "Preparando seu vídeo…",
                              "quality": quality, "state": "queued", "percent": None,
                              "fingerprint": hashlib.sha256((url + quality).encode()).hexdigest()}
            self.pool.submit(self._run, key, url, quality)
            return key

    def _run(self, key, url, quality):
        folder = self.destination / ".work" / key
        folder.mkdir(parents=True, exist_ok=True)
        command = (self.worker_factory(folder) if self.worker_factory else
                   [sys.executable, str(BASE / "app.py"), "--worker", "--url", url,
                    "--quality", quality, "--destination", str(folder)])
        process = None
        timer = None
        try:
            with self.lock:
                if self.closing:
                    raise ValueError("O baixador está encerrando.")
                self.jobs[key]["state"] = "checking"
            environment = dict(os.environ)
            environment["PYTHONIOENCODING"] = "utf-8"
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
                                       text=True, encoding="utf-8", errors="replace",
                                       start_new_session=os.name != "nt",
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            with self.lock:
                self.processes[key] = process
                if self.closing:
                    self.stop_process(process)
            def timeout():
                self.stop_process(process)
            timer = threading.Timer(1800, timeout)
            timer.daemon = True
            timer.start()
            completed = None
            error = None
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if event.get("state") == "complete":
                    completed = event
                elif event.get("state") == "error":
                    error = event.get("error")
                elif event.get("state") in {"checking", "downloading", "processing"}:
                    with self.lock:
                        self.jobs[key].update({k: v for k, v in event.items()
                                               if k in {"state", "percent", "bytes", "total", "speed", "eta", "title", "duration"}})
            if process.wait() != 0 or not completed:
                raise ValueError(error or "Não foi possível concluir o vídeo no prazo de 30 minutos.")
            output = (folder / completed["filename"]).resolve()
            if output.parent != folder.resolve() or not output.is_file() or output.suffix.lower() != ".mp4":
                raise ValueError("O extrator retornou um arquivo inválido.")
            if output.stat().st_size > MAX_BYTES:
                raise ValueError("O arquivo final excedeu o limite de 2 GB.")
            # Include a unique job suffix, avoiding overwrites even for repeated titles.
            final = self.destination / f"{output.stem[:130]}-{key[:8]}.mp4"
            if final.exists():
                raise ValueError("Já existe um arquivo com esse nome.")
            shutil.move(str(output), final)
            with self.lock:
                self.jobs[key].update(state="done", percent=100, filename=final.name,
                                      title=completed.get("title", "Vídeo"), size=final.stat().st_size)
        except Exception as error:
            with self.lock:
                self.jobs[key].update(state="error", error=user_error(str(error)), percent=None)
        finally:
            if timer:
                timer.cancel()
            if process and process.poll() is None:
                self.stop_process(process)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process and process.stdout:
                process.stdout.close()
            with self.lock:
                self.processes.pop(key, None)
            # This folder contains only this job's disposable fragments, never user files.
            shutil.rmtree(folder, ignore_errors=True)

    def close(self):
        with self.lock:
            self.closing = True
            for process in self.processes.values():
                self.stop_process(process)
        self.pool.shutdown(wait=True, cancel_futures=True)

    @staticmethod
    def stop_process(process):
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            process.terminate()


def create_server(destination, port=8767, worker_factory=None):
    downloads = Downloads(destination, worker_factory)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def headers_ok(self):
            try:
                host = urlsplit("http://" + self.headers.get("Host", ""))
                allowed = host.hostname in {"127.0.0.1", "localhost"} and host.port == self.server.server_port
                return allowed
            except ValueError:
                return False

        def authorized(self, write=False):
            jar = http.cookies.SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie", ""))
            except http.cookies.CookieError:
                return False
            if not secrets.compare_digest(jar.get("milena", http.cookies.Morsel()).value or "", token):
                return False
            if write:
                expected = "http://" + self.headers.get("Host", "")
                if self.headers.get("Origin") != expected or self.headers.get("X-Milena-Token") != token:
                    return False
            return True

        def reply(self, status, payload, content_type="application/json; charset=utf-8", cookie=False):
            body = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, (dict, list)) else payload
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header("Set-Cookie", f"milena={token}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.headers_ok():
                return self.reply(403, {"error": "Host não autorizado."})
            route = urlsplit(self.path).path
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if route in assets:
                file, mime = assets[route]
                body = (BASE / "web" / file).read_bytes().replace(b"__MILENA_TOKEN__", token.encode())
                return self.reply(200, body, mime, cookie=route == "/")
            if not self.authorized():
                return self.reply(403, {"error": "Abra a página do baixador neste navegador."})
            if route == "/api/status":
                return self.reply(200, {"destination": str(downloads.destination), "preview": False,
                                       "jsReady": bool(runtime()), "jobs": downloads.list()})
            match = re.fullmatch(r"/files/([a-f0-9]{32})", route)
            if match:
                job = next((j for j in downloads.list() if j["id"] == match[1] and j["state"] == "done"), None)
                if not job:
                    return self.reply(404, {"error": "Download não encontrado nesta sessão."})
                file = (downloads.destination / job["filename"]).resolve()
                if file.parent != downloads.destination or not file.is_file():
                    return self.reply(404, {"error": "O arquivo foi movido ou removido."})
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(file.stat().st_size))
                self.send_header("Content-Disposition", f'attachment; filename="{file.name}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with file.open("rb") as stream:
                    shutil.copyfileobj(stream, self.wfile, length=256 * 1024)
                return
            self.reply(404, {"error": "Página não encontrada."})

        def do_POST(self):
            if not self.headers_ok() or not self.authorized(write=True):
                return self.reply(403, {"error": "Pedido não autorizado. Reabra a página local."})
            if self.path != "/api/downloads":
                return self.reply(404, {"error": "Operação não encontrada."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096 or not self.headers.get("Content-Type", "").startswith("application/json"):
                    raise ValueError("Pedido inválido.")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Pedido inválido.")
                if payload.get("quality", "1080") not in QUALITIES:
                    raise ValueError("Qualidade inválida.")
                key = downloads.submit(payload.get("url"), payload.get("quality", "1080"))
                self.reply(202, {"id": key})
            except (ValueError, TypeError) as error:
                self.reply(400, {"error": str(error)[:400]})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.downloads = downloads
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8767)))
    parser.add_argument("--destination", type=Path, default=Path.home() / "Videos" / "MilenaStudio" / "downloads")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--url")
    parser.add_argument("--quality", choices=QUALITIES, default="1080")
    args = parser.parse_args()
    if args.worker:
        try:
            download_worker(args.url, args.quality, args.destination)
        except Exception as error:
            emit({"state": "error", "error": user_error(str(error))})
            raise SystemExit(1)
        return
    server = create_server(args.destination, args.port)
    address = f"http://127.0.0.1:{server.server_port}"
    print(f"Milena Baixar: {address}\nDestino: {server.downloads.destination}\nDeixe esta janela aberta. Ctrl+C encerra o site.", flush=True)
    if not args.no_browser:
        threading.Timer(.5, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.downloads.close()


if __name__ == "__main__":
    main()
