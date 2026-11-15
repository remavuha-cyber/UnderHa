"""Help choose a scene: list scene cuts and (optionally) dialogue from a .srt with timestamps.

    python shorts/find_scenes.py films/movie.mkv [--srt films/movie.ru.srt] [--threshold 0.35]

Prints audio tracks (to pick the Russian dub index), scene cuts, and dialogue lines.
Paste the dialogue dump to Claude to get suggested segments + hook text.
"""
import argparse
import re
import subprocess


def fmt(t: float) -> str:
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


ap = argparse.ArgumentParser()
ap.add_argument("film")
ap.add_argument("--srt")
ap.add_argument("--threshold", type=float, default=0.35)
ap.add_argument("--no-scenes", action="store_true")
a = ap.parse_args()

tracks = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                         "stream=index:stream_tags=language,title", "-of", "csv=p=0", a.film],
                        capture_output=True, text=True).stdout.strip().splitlines()
print("AUDIO TRACKS (audio_track = position in this list, from 0):")
for i, t in enumerate(tracks):
    print(f"  {i}: {t}")

if not a.no_scenes:
    print("\nSCENE CUTS:")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", a.film, "-map", "0:v:0", "-vf",
                        f"scale=320:-2,select='gt(scene,{a.threshold})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    for m in re.finditer(r"pts_time:([\d.]+)", r.stderr):
        print("  " + fmt(float(m.group(1))))

if a.srt:
    print("\nDIALOGUE:")
    txt = open(a.srt, encoding="utf-8-sig", errors="ignore").read()
    for block in re.split(r"\n\s*\n", txt):
        m = re.search(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)\s*\n(.*)", block, re.S)
        if m:
            line = re.sub(r"<[^>]+>", "", m.group(3)).replace("\n", " ").strip()
            print(f"  {m.group(1)[:8]}  {line}")
