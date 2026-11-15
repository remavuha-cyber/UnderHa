"""Upload a rendered MP4 as a YouTube Short via Data API v3 (videos.insert, 1600 quota units)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from yt import client

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def build_metadata(script: dict) -> dict:
    is_edit = "source" in script
    base_tags = CONFIG["edit_hashtags"] if is_edit else CONFIG["default_hashtags"]
    tags_hash = " ".join(base_tags + ["#" + t for t in script.get("tags", [])])
    title = script.get("title") or script["hook"]
    suffix = " " + " ".join(base_tags[:2])
    if "#" not in title and len(title) + len(suffix) <= 100:
        title += suffix
    body = script.get("description") or ("Фильм: " + script["film"] if is_edit else " ".join(script["lines"]))
    footer = CONFIG["edit_footer"] if is_edit else CONFIG["description_footer"]
    description = "\n\n".join([body, footer, tags_hash])
    return {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["фильмы", "кино", "эдит", script.get("film", "")] + script.get("tags", []),
            "categoryId": CONFIG.get("category_id", "1"),
            "defaultLanguage": "ru",
            "defaultAudioLanguage": "ru",
        },
        "status": {
            "privacyStatus": CONFIG.get("privacy_status", "public"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": not is_edit,
        },
    }


def upload(video: Path, script: dict) -> str:
    yt = client()
    req = yt.videos().insert(
        part="snippet,status",
        body=build_metadata(script),
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True),
    )
    resp, retries = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retries < 5:
                retries += 1
                time.sleep(2 ** retries)
                continue
            raise
    vid = resp["id"]
    print(f"uploaded https://youtube.com/shorts/{vid} (privacy: {resp['status']['privacyStatus']})")
    return vid


if __name__ == "__main__":
    import sys
    v, s = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    upload(v, s)
