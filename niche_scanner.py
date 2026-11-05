#!/usr/bin/env python3
"""
YouTube Niche Scanner
=====================
Находит "аутлайдеры" — небольшие каналы с непропорционально большими
просмотрами (views / subscribers), то есть растущие форматы/ниши.

Как работает:
  1. Для каждого ключевого запроса делает search.list (ищет свежие видео).
  2. Собирает статистику видео (videos.list) и каналов (channels.list).
  3. Считает метрики: отношение просмотров к подписчикам, частоту загрузок и т.д.
  4. Выводит таблицу и сохраняет CSV, отсортированный по "выстрелу".

Квота YouTube Data API (бесплатно 10 000 ед./день):
  - search.list          = 100 ед. за запрос  (это основной расход)
  - videos.list          = 1 ед.
  - channels.list        = 1 ед.
  Значит ~90 поисковых запросов в день. Скрипт экономит квоту: батчит
  videos.list и channels.list по 50 id за вызов.

Запуск:
  export YOUTUBE_API_KEY="ВАШ_КЛЮЧ"
  python3 niche_scanner.py --queries "страшные истории,факты о космосе" --per-query 25
  # или из файла (по запросу на строку):
  python3 niche_scanner.py --queries-file queries.txt

Зависимости: только стандартная библиотека Python 3 (urllib). Ничего ставить не нужно.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

API_BASE = "https://www.googleapis.com/youtube/v3"


def api_get(endpoint: str, params: dict, api_key: str) -> dict:
    """Один GET-запрос к YouTube Data API с базовой обработкой ошибок."""
    params = {**params, "key": api_key}
    url = f"{API_BASE}/{endpoint}?{urlencode(params)}"
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 403 and "quotaExceeded" in body:
            sys.exit("❌ Квота YouTube Data API на сегодня исчерпана. "
                     "Подождите до сброса (полночь по тихоокеанскому времени) "
                     "или уменьшите --per-query / число запросов.")
        sys.exit(f"❌ Ошибка API ({e.code}): {body[:500]}")
    except URLError as e:
        sys.exit(f"❌ Сеть недоступна: {e.reason}. "
                 "Проверьте, что домен www.googleapis.com разрешён в Network access.")


def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def iso8601_duration_to_seconds(dur: str) -> int:
    """Переводит длительность вида 'PT1M30S' в секунды. Shorts обычно <= 60с."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s


def search_videos(query: str, per_query: int, published_after: str, api_key: str,
                  video_duration: str = "any"):
    """Ищет видео по запросу. Возвращает список videoId (с пагинацией).
    video_duration: 'short' (<4 мин, сужает выдачу для Shorts) или 'any'."""
    video_ids = []
    page_token = None
    while len(video_ids) < per_query:
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "viewCount",          # сначала самые просматриваемые
            "maxResults": min(50, per_query - len(video_ids)),
            "publishedAfter": published_after,  # только свежие -> ищем растущее
            "relevanceLanguage": "ru",
            "videoDuration": video_duration,
        }
        if page_token:
            params["pageToken"] = page_token
        data = api_get("search", params, api_key)
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid:
                video_ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return video_ids


def get_videos_stats(video_ids, api_key: str) -> dict:
    """videos.list батчами по 50. Возвращает {videoId: {...}}."""
    out = {}
    for batch in chunked(video_ids, 50):
        data = api_get("videos", {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
        }, api_key)
        for item in data.get("items", []):
            stats = item.get("statistics", {})
            sn = item.get("snippet", {})
            duration = item.get("contentDetails", {}).get("duration", "")
            out[item["id"]] = {
                "title": sn.get("title", ""),
                "channel_id": sn.get("channelId", ""),
                "channel_title": sn.get("channelTitle", ""),
                "published_at": sn.get("publishedAt", ""),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "duration_sec": iso8601_duration_to_seconds(duration),
            }
    return out


def get_channels_stats(channel_ids, api_key: str) -> dict:
    """channels.list батчами по 50. Возвращает {channelId: {...}}."""
    out = {}
    uniq = list({c for c in channel_ids if c})
    for batch in chunked(uniq, 50):
        data = api_get("channels", {
            "part": "statistics,snippet",
            "id": ",".join(batch),
        }, api_key)
        for item in data.get("items", []):
            stats = item.get("statistics", {})
            out[item["id"]] = {
                "subs": int(stats.get("subscriberCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "hidden_subs": stats.get("hiddenSubscriberCount", False),
            }
    return out


def scan(queries, per_query, days_back, min_views, max_subs, api_key,
         shorts_only=False, max_duration=60):
    published_after = (datetime.now(timezone.utc) -
                       timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Для Shorts сужаем поиск до коротких видео (<4 мин) — экономит обработку.
    search_duration = "short" if shorts_only else "any"
    rows = []
    for q in queries:
        q = q.strip()
        if not q:
            continue
        tag = " [Shorts]" if shorts_only else ""
        print(f"🔎 Поиск: {q!r}{tag} (за последние {days_back} дн.)...", file=sys.stderr)
        vids = search_videos(q, per_query, published_after, api_key, search_duration)
        if not vids:
            print(f"   (ничего не найдено)", file=sys.stderr)
            continue
        vstats = get_videos_stats(vids, api_key)
        cstats = get_channels_stats([v["channel_id"] for v in vstats.values()], api_key)

        for vid, v in vstats.items():
            ch = cstats.get(v["channel_id"], {})
            subs = ch.get("subs", 0)
            # Фильтр Shorts: оставляем только короткие вертикальные ролики по длительности.
            if shorts_only and not (0 < v["duration_sec"] <= max_duration):
                continue
            if v["views"] < min_views:
                continue
            if max_subs and subs > max_subs:
                continue
            # Главная метрика: сколько просмотров на одного подписчика.
            # Высокое значение = ролик "выстрелил" относительно размера канала.
            ratio = round(v["views"] / subs, 1) if subs > 0 else float(v["views"])
            engagement = round((v["likes"] + v["comments"]) / v["views"] * 100, 2) if v["views"] else 0
            is_short = 0 < v["duration_sec"] <= max_duration
            url = (f"https://www.youtube.com/shorts/{vid}" if is_short
                   else f"https://youtu.be/{vid}")
            rows.append({
                "query": q,
                "outlier_ratio": ratio,
                "views": v["views"],
                "subs": subs,
                "duration_sec": v["duration_sec"],
                "video_count": ch.get("video_count", 0),
                "engagement_%": engagement,
                "channel": v["channel_title"],
                "title": v["title"][:70],
                "published": v["published_at"][:10],
                "video_url": url,
            })
        time.sleep(0.2)  # лёгкая пауза между запросами

    rows.sort(key=lambda r: r["outlier_ratio"], reverse=True)
    return rows


def print_table(rows, top):
    if not rows:
        print("\nНичего не прошло по фильтрам. Попробуйте снизить --min-views "
              "или повысить --max-subs.")
        return
    print(f"\n{'RATIO':>8}  {'VIEWS':>10}  {'SUBS':>9}  {'ENG%':>5}  CHANNEL / TITLE")
    print("-" * 100)
    for r in rows[:top]:
        print(f"{r['outlier_ratio']:>8}  {r['views']:>10,}  {r['subs']:>9,}  "
              f"{r['engagement_%']:>5}  {r['channel'][:22]:<22} | {r['title']}")
        print(f"{'':>38}{r['video_url']}")


def main():
    p = argparse.ArgumentParser(description="YouTube Niche Scanner — ищет растущие форматы")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--queries", help="запросы через запятую")
    src.add_argument("--queries-file", help="файл: один запрос на строку")
    p.add_argument("--per-query", type=int, default=25,
                   help="сколько видео брать на запрос (кратно 50 экономит квоту). По умолч. 25")
    p.add_argument("--days-back", type=int, default=90,
                   help="искать видео за последние N дней (свежесть = рост). По умолч. 90")
    p.add_argument("--min-views", type=int, default=50000,
                   help="минимум просмотров у видео. По умолч. 50000")
    p.add_argument("--max-subs", type=int, default=100000,
                   help="максимум подписчиков у канала (ищем мелкие). По умолч. 100000. 0 = без лимита")
    p.add_argument("--shorts", action="store_true",
                   help="только Shorts (короткие вертикальные ролики по длительности)")
    p.add_argument("--max-duration", type=int, default=60,
                   help="граница длительности Shorts в секундах. По умолч. 60 (можно 180)")
    p.add_argument("--top", type=int, default=30, help="сколько строк показать. По умолч. 30")
    p.add_argument("--out", default="niche_results.csv", help="CSV с результатами")
    args = p.parse_args()

    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        sys.exit("❌ Не задан ключ. Выполните: export YOUTUBE_API_KEY=\"ВАШ_КЛЮЧ\"")

    if args.queries_file:
        with open(args.queries_file, encoding="utf-8") as f:
            queries = [line.strip() for line in f if line.strip()]
    else:
        queries = args.queries.split(",")

    print(f"⚙️  Запросов: {len(queries)} | квота ≈ {len(queries) * 100 + len(queries) * 2} ед. "
          f"(лимит 10000/день)", file=sys.stderr)

    rows = scan(queries, args.per_query, args.days_back,
                args.min_views, args.max_subs, api_key,
                shorts_only=args.shorts, max_duration=args.max_duration)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print_table(rows, args.top)
    print(f"\n✅ Сохранено: {args.out} ({len(rows)} строк)")


if __name__ == "__main__":
    main()
