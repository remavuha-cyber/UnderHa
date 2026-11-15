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
    tags_hash = " ".join(CONFIG["default_hashtags"] + ["#" + t for t in script.get("tags", [])])
    title = script["title"]
    if "#shorts" not in title.lower() and len(title) + 8 <= 100:
        title += " #shorts"
    description = "\n\n".join([" ".join(script["lines"]), CONFIG["description_footer"], tags_hash])
    return {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["фильмы", "кино", "факты о кино", script["film"]] + script.get("tags", []),
            "categoryId": CONFIG.get("category_id", "1"),
            "defaultLanguage": "ru",
            "defaultAudioLanguage": "ru",
        },
        "status": {
            "privacyStatus": CONFIG.get("privacy_status", "public"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
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
