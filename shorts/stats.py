"""Print views/likes/comments for every published Short (Data API v3, 1 unit per 50 videos).

    python shorts/stats.py [--json]
"""
import json
import sys
from pathlib import Path

from yt import client

LOG = Path(__file__).resolve().parent / "content" / "published.json"

published = json.loads(LOG.read_text(encoding="utf-8"))
ids = [p["video_id"] for p in published]
rows = []
yt = client()
for i in range(0, len(ids), 50):
    resp = yt.videos().list(part="statistics,snippet", id=",".join(ids[i:i + 50])).execute()
    for it in resp["items"]:
        s = it["statistics"]
        rows.append({"id": it["id"], "title": it["snippet"]["title"], "views": int(s.get("viewCount", 0)),
                     "likes": int(s.get("likeCount", 0)), "comments": int(s.get("commentCount", 0))})
rows.sort(key=lambda r: r["views"], reverse=True)
if "--json" in sys.argv:
    print(json.dumps(rows, ensure_ascii=False, indent=2))
else:
    print(f"{'views':>9} {'likes':>6} {'comm':>5}  title")
    for r in rows:
        print(f"{r['views']:>9} {r['likes']:>6} {r['comments']:>5}  {r['title']}")
    ch = yt.channels().list(part="statistics", mine=True).execute()["items"][0]["statistics"]
    print(f"\nchannel: {ch.get('subscriberCount')} subs, {ch.get('viewCount')} views, {ch.get('videoCount')} videos")
