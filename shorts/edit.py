"""Movie "edit" Shorts: cut scene(s) from a film file into 1080x1920 with a white hook header.

Clip spec (JSON), e.g. shorts/clips/the-founder.json:
{
  "id": "e001-founder",
  "source": "films/The.Founder.2016.mkv",      # your local film file
  "audio_track": 0,                             # index among audio streams (pick the Russian dub)
  "hook": "От провала до революции фастфуда",  # text in the white header
  "segments": [ {"start": "00:41:10.5", "end": "00:41:52", "focus": 0.5} ],
  "subs": "films/The.Founder.ru.srt",           # optional: burn subtitles
  "title": "От провала до революции фастфуда",
  "tags": ["основатель", "макдональдс"]
}
"focus" = horizontal crop position 0 (left) .. 1 (right) for that segment.

    python shorts/edit.py shorts/clips/the-founder.json [-o shorts/out]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from render import CONFIG, font

W, H = 1080, 1920
HEADER = int(CONFIG.get("edit_header_px", 330))
GRADE = CONFIG.get(
    "edit_grade",
    "eq=contrast=1.10:saturation=1.28:gamma=0.97,unsharp=5:5:0.6,vignette=PI/6",
)


def ts(t: str | float) -> float:
    if isinstance(t, (int, float)):
        return float(t)
    sec = 0.0
    for part in t.replace(",", ".").split(":"):
        sec = sec * 60 + float(part)
    return sec


def probe_size(path: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", path], capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def header_png(text: str, path: Path) -> None:
    img = Image.new("RGB", (W, HEADER), "white")
    d = ImageDraw.Draw(img)
    text = text.upper()
    size = 76
    while True:
        f = font(size)
        words, lines, cur = text.split(), [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if d.textlength(test, font=f) > W - 110 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = test
        lines.append(cur)
        if len(lines) <= 3 or size <= 44:
            break
        size -= 6
    lh = int(size * 1.18)
    y = HEADER / 2 - lh * (len(lines) - 1) / 2
    for line in lines:
        d.text((W / 2, y), line, font=f, fill="black", anchor="mm")
        y += lh
    img.save(path)


def srt_escape(p: str) -> str:
    return p.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def render_edit(spec_path: Path, out_dir: Path) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    base = spec_path.parent
    src = str((base / spec["source"]).resolve()) if not Path(spec["source"]).is_absolute() else spec["source"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{spec['id']}.mp4"
    sw, sh = probe_size(src)
    vh = H - HEADER
    scaled_w = round(sw * vh / sh / 2) * 2  # scale to fill height, then crop width
    if scaled_w < W:
        scaled_w, vh_scaled = W, round(sh * W / sw / 2) * 2
    else:
        vh_scaled = vh

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        hdr = tmp / "header.png"
        header_png(spec["hook"], hdr)

        inputs, filters, concat_in = [], [], ""
        segs = spec["segments"]
        for i, seg in enumerate(segs):
            start, end = ts(seg["start"]), ts(seg["end"])
            inputs += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src]
            focus = float(seg.get("focus", 0.5))
            x = f"(iw-{W})*{focus:.3f}"
            v = (f"[{i}:v:0]scale={scaled_w}:{vh_scaled},crop={W}:{vh}:{x}:(ih-{vh})/2,"
                 f"{GRADE},setsar=1,fps=30")
            if spec.get("subs"):
                subs = str((base / spec["subs"]).resolve())
                # subtitles filter uses source timestamps; shift by segment start
                v += (f",setpts=PTS+{start:.3f}/TB,subtitles='{srt_escape(subs)}':force_style="
                      "'FontName=DejaVu Sans,Bold=1,FontSize=13,Outline=2,MarginV=40',setpts=PTS-STARTPTS")
            filters.append(v + f"[v{i}]")
            filters.append(f"[{i}:a:{spec.get('audio_track', 0)}]aresample=48000,"
                           f"aformat=channel_layouts=stereo[a{i}]")
            concat_in += f"[v{i}][a{i}]"
        n = len(segs)
        hi = n  # header input index
        inputs += ["-loop", "1", "-i", str(hdr)]
        total = sum(ts(s["end"]) - ts(s["start"]) for s in segs)
        filters.append(f"{concat_in}concat=n={n}:v=1:a=1[vc][ac]")
        filters.append(f"[{hi}:v]format=rgb24[h];[h][vc]vstack=inputs=2,format=yuv420p,"
                       f"fade=t=out:st={max(total - 0.4, 0):.2f}:d=0.4[vout]")
        filters.append(f"[ac]loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st={max(total - 0.4, 0):.2f}:d=0.4[aout]")

        cmd = (["ffmpeg", "-y", "-loglevel", "error", *inputs,
                "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
                "-t", f"{total:.3f}", "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)])
        subprocess.run(cmd, check=True)
    print(f"rendered {out} ({total:.1f}s)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path(__file__).resolve().parent / "out")
    a = ap.parse_args()
    for s in a.specs:
        render_edit(s, a.out)


if __name__ == "__main__":
    main()
