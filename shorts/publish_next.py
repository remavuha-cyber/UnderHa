"""Pick the next unpublished script from content/queue, render it, upload it, record it.

    python shorts/publish_next.py            # render + upload
    python shorts/publish_next.py --dry-run  # render only
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from render import render

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "content" / "queue"
CLIPS = ROOT / "clips"
LOG = ROOT / "content" / "published.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--edits", action="store_true", help="publish movie edits from shorts/clips/ (run locally, needs film files)")
    a = ap.parse_args()
    queue = CLIPS if a.edits else QUEUE

    published = json.loads(LOG.read_text(encoding="utf-8"))
    done = {p["id"] for p in published}
    pending = [p for p in sorted(queue.glob("*.json")) if p.stem not in done]
    print(f"queue: {len(pending)} unpublished")
    if not pending:
        sys.exit("Queue is empty - add new specs to shorts/clips/ or shorts/content/queue/")
    if len(pending) <= 3:
        print(f"::warning::Only {len(pending)} scripts left in the queue")

    for path in pending[: a.count]:
        script = json.loads(path.read_text(encoding="utf-8"))
        if a.edits:
            from edit import render_edit
            video = render_edit(path, ROOT / "out")
        else:
            video = render(path, ROOT / "out")
        if a.dry_run:
            continue
        from upload import upload
        vid = upload(video, script)
        published.append({"id": script["id"], "video_id": vid,
                          "published_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
        LOG.write_text(json.dumps(published, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
