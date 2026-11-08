# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
"""Strict SRT input: validate the whole file before making any edits."""

import html
import math
import re
from pathlib import Path

MAX_SRT_BYTES = 5 * 1024 * 1024
MAX_CUES = 10000
TIMING = re.compile(
    r"^(\d{1,3}):([0-5]\d):([0-5]\d)[,.](\d{3})\s+-->\s+"
    r"(\d{1,3}):([0-5]\d):([0-5]\d)[,.](\d{3})$"
)
STYLE_TAG = re.compile(r"</?(?:b|i|u|font)(?:\s+[^>]*)?>", re.IGNORECASE)


def parse_srt(text: str, offset_seconds: float = 0) -> list[dict]:
    """Keep line breaks and Unicode; strip presentation tags, never interpret them."""
    if not math.isfinite(offset_seconds):
        raise ValueError("O deslocamento deve ser um número finito.")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("O arquivo SRT está vazio.")
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n[ \t]*\n", text.strip())
    if len(blocks) > MAX_CUES:
        raise ValueError(f"O limite é {MAX_CUES} legendas por importação.")
    cues = []
    previous = -1.0
    for number, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit():
            lines.pop(0)
        timing = TIMING.fullmatch(lines.pop(0).strip()) if lines else None
        if not timing:
            raise ValueError(f"Tempo inválido na legenda {number}.")
        values = [int(x) for x in timing.groups()]

        def stamp(i):
            return (values[i] * 3600 + values[i+1] * 60
                    + values[i+2] + values[i+3] / 1000 + offset_seconds)

        start, end = stamp(0), stamp(4)
        content = html.unescape(STYLE_TAG.sub("", "\n".join(lines))).strip()
        if start < 0 or end <= start or start < previous:
            raise ValueError(f"Ordem ou duração inválida na legenda {number}.")
        if not content or "\x00" in content:
            raise ValueError(f"Texto vazio ou inválido na legenda {number}.")
        cues.append({"start": start, "end": end, "text": content})
        previous = start
    return cues


def read_srt(path: Path, offset_seconds: float = 0) -> list[dict]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_SRT_BYTES + 1)
    if len(raw) > MAX_SRT_BYTES:
        raise ValueError("O SRT excede 5 MiB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Salve a legenda em UTF-8 para preservar os acentos.") from error
    return parse_srt(text, offset_seconds)
