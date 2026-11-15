"""Render one Shorts script (JSON) into a 1080x1920 MP4 with AI voice and karaoke captions.

Usage:
    python shorts/render.py shorts/content/queue/001-interstellar-corn.json [-o out/]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

W, H = 1080, 1920
TICKS = 10_000_000  # edge-tts offsets are in 100ns ticks

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    custom = CONFIG.get("font_path")
    for p in ([custom] if custom else []) + FONT_CANDIDATES:
        if p and Path(p).exists():
            return ImageFont.truetype(p, size)
    sys.exit("No bold TTF font found; set font_path in shorts/config.json")


# ---------- voice ----------

@dataclass
class Word:
    text: str
    start: float
    end: float


def _patch_ssl() -> None:
    # Behind a TLS-intercepting proxy the system CA bundle must be used instead of certifi's.
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if ca and Path(ca).exists():
        edge_tts.communicate._SSL_CTX = ssl.create_default_context(cafile=ca)


async def _tts(text: str, mp3: Path) -> list[Word]:
    _patch_ssl()
    com = edge_tts.Communicate(
        text,
        CONFIG["voice"],
        rate=CONFIG.get("rate", "+0%"),
        pitch=CONFIG.get("pitch", "+0Hz"),
        boundary="WordBoundary",
    )
    words: list[Word] = []
    with mp3.open("wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / TICKS
                words.append(Word(chunk["text"], s, s + chunk["duration"] / TICKS))
    return words


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


# ---------- captions ----------

def attach_punctuation(words: list[Word], full_text: str) -> list[Word]:
    """WordBoundary drops punctuation; re-attach it from the source text so captions read naturally."""
    tokens = full_text.split()
    out, ti = [], 0
    for w in words:
        text = w.text
        # find the source token containing this word
        while ti < len(tokens) and w.text.lower() not in tokens[ti].lower():
            ti += 1
        if ti < len(tokens):
            text = tokens[ti]
            ti += 1
        out.append(Word(text, w.start, w.end))
    return out


def group_captions(words: list[Word], max_words: int = 3, max_chars: int = 18) -> list[list[int]]:
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        chars = sum(len(words[j].text) + 1 for j in cur)
        if len(cur) >= max_words or chars >= max_chars or re.search(r"[.!?…:—»]$", w.text):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


# ---------- drawing ----------

def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def background(script: dict) -> Image.Image:
    seed = int(hashlib.md5(script["id"].encode()).hexdigest(), 16)
    palettes = CONFIG["palettes"]
    top, bottom = (hex_rgb(c) for c in palettes[seed % len(palettes)])
    img = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        px.line([(0, y), (W, y)], fill=tuple(int(top[k] * (1 - t) + bottom[k] * t) for k in range(3)))

    # soft light blobs for depth
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for k in range(3):
        r = 260 + (seed >> (k * 7)) % 220
        cx = (seed >> (k * 5)) % W
        cy = 300 + (seed >> (k * 9)) % (H - 600)
        g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 28))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img.convert("RGBA"), glow)

    # film strip edges
    d = ImageDraw.Draw(img)
    for x in (24, W - 64):
        d.rectangle([x, 0, x + 40, H], fill=(0, 0, 0, 120))
        for y in range(10, H, 70):
            d.rounded_rectangle([x + 8, y, x + 32, y + 40], 6, fill=(255, 255, 255, 40))

    # header: label + film
    accent = hex_rgb(CONFIG["accent"])
    label = CONFIG.get("label", "ФАКТ О ФИЛЬМЕ")
    f_label, f_film = font(46), font(64)
    lw = d.textlength(label, font=f_label)
    d.rounded_rectangle([(W - lw) / 2 - 30, 210, (W + lw) / 2 + 30, 290], 40, fill=accent)
    d.text((W / 2, 250), label, font=f_label, fill=(15, 15, 15), anchor="mm")
    film = script["film"]
    size = 64
    while d.textlength(film, font=f_film) > W - 200 and size > 36:
        size -= 4
        f_film = font(size)
    d.text((W / 2, 370), film, font=f_film, fill=(255, 255, 255), anchor="mm",
           stroke_width=3, stroke_fill=(0, 0, 0))

    # footer handle
    d.text((W / 2, H - 230), CONFIG["channel_handle"], font=font(42), fill=(255, 255, 255, 200), anchor="mm")
    return img


def wrap_words(d: ImageDraw.ImageDraw, words: list[str], f, max_w: int) -> list[list[int]]:
    lines, cur = [], []
    for i, w in enumerate(words):
        test = " ".join(words[j] for j in cur + [i])
        if cur and d.textlength(test, font=f) > max_w:
            lines.append(cur)
            cur = [i]
        else:
            cur.append(i)
    if cur:
        lines.append(cur)
    return lines


def caption_frame(bg: Image.Image, words: list[str], active: int, progress: float) -> Image.Image:
    img = bg.copy()
    d = ImageDraw.Draw(img)
    words = [w.upper() for w in words]
    size = 110
    f = font(size)
    max_w = W - 200
    lines = wrap_words(d, words, f, max_w)
    while size > 60 and (len(lines) > 3 or max(d.textlength(w, font=f) for w in words) > max_w):
        size -= 6
        f = font(size)
        lines = wrap_words(d, words, f, max_w)
    lh = int(size * 1.25)
    y0 = H / 2 - lh * len(lines) / 2 + lh / 2
    accent = hex_rgb(CONFIG["accent"])
    space = d.textlength(" ", font=f)
    for li, line in enumerate(lines):
        widths = [d.textlength(words[i], font=f) for i in line]
        x = (W - (sum(widths) + space * (len(line) - 1))) / 2
        y = y0 + li * lh
        for i, wd in zip(line, widths):
            fill = accent if i == active else (255, 255, 255)
            d.text((x, y), words[i], font=f, fill=fill, anchor="lm", stroke_width=8, stroke_fill=(0, 0, 0))
            x += wd + space

    # progress bar
    d.rounded_rectangle([90, H - 150, W - 90, H - 136], 7, fill=(60, 60, 60))
    d.rounded_rectangle([90, H - 150, 90 + max(14, (W - 180) * progress), H - 136], 7, fill=accent)
    return img.convert("RGB")


# ---------- assembly ----------

def render(script_path: Path, out_dir: Path) -> Path:
    script = json.loads(script_path.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{script['id']}.mp4"
    text = " ".join(script["lines"])

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        mp3 = tmp / "voice.mp3"
        words = asyncio.run(_tts(text, mp3))
        if not words:
            sys.exit("TTS returned no word timings")
        words = attach_punctuation(words, text)
        total = audio_duration(mp3) + 0.6

        bg = background(script)
        groups = group_captions(words)
        concat = []
        n = 0
        for gi, group in enumerate(groups):
            texts = [words[i].text for i in group]
            for k, wi in enumerate(group):
                start = 0.0 if n == 0 else words[wi].start
                if k + 1 < len(group):
                    end = words[group[k + 1]].start
                elif gi + 1 < len(groups):
                    end = words[groups[gi + 1][0]].start
                else:
                    end = total
                frame = tmp / f"f{n:04d}.png"
                caption_frame(bg, texts, k, end / total).save(frame)
                concat.append(f"file '{frame}'\nduration {max(end - start, 0.04):.3f}")
                n += 1
        concat.append(f"file '{tmp / f'f{n - 1:04d}.png'}'")  # concat demuxer needs the last frame repeated
        (tmp / "list.txt").write_text("\n".join(concat))

        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
               "-i", str(mp3)]
        music = CONFIG.get("music_path")
        if music and Path(music).exists():
            cmd += ["-stream_loop", "-1", "-i", music,
                    "-filter_complex", f"[2:a]volume={CONFIG.get('music_volume', 0.12)}[m];"
                                       "[1:a][m]amix=inputs=2:duration=first[a]",
                    "-map", "0:v", "-map", "[a]"]
        else:
            cmd += ["-map", "0:v", "-map", "1:a", "-af", "apad"]
        cmd += ["-t", f"{total:.2f}", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)
    print(f"rendered {out} ({total:.1f}s)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scripts", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "out")
    a = ap.parse_args()
    for s in a.scripts:
        render(s, a.out)


if __name__ == "__main__":
    main()
