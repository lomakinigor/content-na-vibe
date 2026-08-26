"""YouTube Trend Finder.

Finds trending videos by ratio = views / channel_subs using YouTube Data API v3.
Three modes: --urls (list of URLs), --search (query), --channel (@handle).
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from googleapiclient.discovery import build


ISO_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")

SHORT_MAX_SEC = 180  # YouTube classifies videos ≤ 3 min as Shorts (heuristic, ~99% accurate).


def iso_duration_to_seconds(s: str) -> int:
    m = ISO_DURATION.fullmatch(s)
    if not m:
        return 0
    h, mi, se = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + se


@dataclass
class VideoRow:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    views: int
    published_at: datetime
    duration_sec: int
    subs: int | None = None
    subs_hidden: bool = False
    ratio: float | None = None
    views_per_hour: float | None = None

    @property
    def is_short(self) -> bool:
        return self.duration_sec <= SHORT_MAX_SEC


def youtube_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


VIDEO_ID_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})"),
    re.compile(r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})"),
]


def parse_video_id(url: str) -> str | None:
    url = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    for pattern in VIDEO_ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def fetch_videos(client, video_ids: list[str]) -> list[VideoRow]:
    rows: list[VideoRow] = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        resp = client.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(batch),
            maxResults=50,
        ).execute()
        for item in resp.get("items", []):
            snip = item["snippet"]
            stats = item.get("statistics", {})
            rows.append(VideoRow(
                video_id=item["id"],
                title=snip["title"],
                channel_id=snip["channelId"],
                channel_title=snip["channelTitle"],
                views=int(stats.get("viewCount", 0)),
                published_at=datetime.fromisoformat(snip["publishedAt"].replace("Z", "+00:00")),
                duration_sec=iso_duration_to_seconds(item["contentDetails"]["duration"]),
            ))
    return rows


def attach_channel_stats(client, rows: list[VideoRow]) -> None:
    ch_ids = sorted({r.channel_id for r in rows})
    subs_map: dict[str, tuple[int | None, bool]] = {}
    for i in range(0, len(ch_ids), 50):
        batch = ch_ids[i : i + 50]
        resp = client.channels().list(part="statistics", id=",".join(batch), maxResults=50).execute()
        for item in resp.get("items", []):
            st = item.get("statistics", {})
            hidden = bool(st.get("hiddenSubscriberCount", False))
            subs = None if hidden else int(st.get("subscriberCount", 0))
            subs_map[item["id"]] = (subs, hidden)
    for r in rows:
        subs, hidden = subs_map.get(r.channel_id, (None, True))
        r.subs = subs
        r.subs_hidden = hidden


def search_video_ids(client, query: str, region: str, days: int, max_pages: int = 3) -> list[str]:
    published_after = None
    if days and days > 0:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        published_after = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "part": "id",
        "q": query,
        "type": "video",
        "order": "viewCount",
        "maxResults": 50,
    }
    if published_after:
        params["publishedAfter"] = published_after
    if region and region.lower() != "worldwide":
        params["regionCode"] = region.upper()

    ids: list[str] = []
    page_token = None
    for _ in range(max_pages):
        if page_token:
            params["pageToken"] = page_token
        resp = client.search().list(**params).execute()
        for item in resp.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid:
                ids.append(vid)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def resolve_channel_id(client, handle_or_id: str) -> str | None:
    h = handle_or_id.lstrip("@")
    if handle_or_id.startswith("UC") and len(handle_or_id) == 24:
        return handle_or_id
    resp = client.search().list(part="snippet", q=h, type="channel", maxResults=5).execute()
    for item in resp.get("items", []):
        snip = item.get("snippet", {})
        ch_id = item.get("id", {}).get("channelId")
        if ch_id and h.lower() in snip.get("channelTitle", "").lower().replace(" ", ""):
            return ch_id
    items = resp.get("items", [])
    return items[0].get("id", {}).get("channelId") if items else None


def fetch_recent_channel_videos(client, channel_id: str, limit: int) -> list[str]:
    resp = client.channels().list(part="contentDetails", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        return []
    uploads_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    video_ids: list[str] = []
    page_token = None
    while len(video_ids) < limit:
        params = {"part": "contentDetails", "playlistId": uploads_id, "maxResults": min(50, limit - len(video_ids))}
        if page_token:
            params["pageToken"] = page_token
        r = client.playlistItems().list(**params).execute()
        for it in r.get("items", []):
            video_ids.append(it["contentDetails"]["videoId"])
        page_token = r.get("nextPageToken")
        if not page_token:
            break
    return video_ids[:limit]


def compute_metrics(rows: list[VideoRow]) -> None:
    now = datetime.now(timezone.utc)
    for r in rows:
        if r.subs and r.subs > 0:
            r.ratio = r.views / r.subs
        age_hours = max(1.0, (now - r.published_at).total_seconds() / 3600)
        r.views_per_hour = r.views / age_hours


def apply_filters(
    rows: list[VideoRow],
    min_ratio: float,
    min_views: int,
    days: int,
    exclude_shorts: bool,
    only_shorts: bool = False,
) -> list[VideoRow]:
    now = datetime.now(timezone.utc)
    cutoff_hours = days * 24
    kept: list[VideoRow] = []
    for r in rows:
        if (now - r.published_at).total_seconds() / 3600 > cutoff_hours:
            continue
        if r.views < min_views:
            continue
        if exclude_shorts and r.is_short:
            continue
        if only_shorts and not r.is_short:
            continue
        if min_ratio > 0 and (r.ratio is None or r.ratio < min_ratio):
            continue
        kept.append(r)
    return kept


def load_urls(path: Path) -> list[str]:
    ids: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        vid = parse_video_id(line)
        if vid:
            ids.append(vid)
        else:
            print(f"WARN: can't parse video ID from: {line}", file=sys.stderr)
    return ids


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find trending YouTube videos by views/subs ratio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--urls", metavar="FILE", help="File with URLs (one per line)")
    mode.add_argument("--search", metavar="QUERY", help="Search query")
    mode.add_argument("--channel", metavar="@handle", help="Channel handle or ID")

    p.add_argument("--last", type=int, default=20, help="Videos to fetch per channel (default: 20)")
    p.add_argument("--min-ratio", type=float, default=0.0, help="Minimum views/subs ratio")
    p.add_argument("--min-views", type=int, default=0, help="Minimum view count")
    p.add_argument("--days", type=int, default=60, help="Published within last N days (default: 60)")
    p.add_argument("--region", default="worldwide", help="Region: RU, US, worldwide (default: worldwide)")
    shorts_group = p.add_mutually_exclusive_group()
    shorts_group.add_argument("--exclude-shorts", action="store_true",
                              help=f"Exclude Shorts (videos ≤ {SHORT_MAX_SEC}s)")
    shorts_group.add_argument("--only-shorts", action="store_true",
                              help=f"Only Shorts (videos ≤ {SHORT_MAX_SEC}s)")
    p.add_argument("--output", help="Output .md path (default: output/trends-YYYY-MM-DD.md)")

    return p.parse_args()


def default_output_path() -> Path:
    today = datetime.now().strftime("%Y-%m-%d")
    return Path(__file__).parent / "output" / f"trends-{today}.md"


def fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def write_report(path: Path, rows: list[VideoRow], meta: dict) -> None:
    rows_sorted = sorted(
        rows,
        key=lambda r: (r.ratio if r.ratio is not None else -1, r.views),
        reverse=True,
    )
    shorts_note = ""
    if meta.get("exclude_shorts"):
        shorts_note = f", long only (>{SHORT_MAX_SEC}s)"
    elif meta.get("only_shorts"):
        shorts_note = f", shorts only (≤{SHORT_MAX_SEC}s)"

    lines = [
        f"# YouTube Trends Report — {meta['date']}",
        "",
        f"- Mode: `{meta['mode']}`",
        f"- Filters: ratio≥{meta['min_ratio']}, views≥{meta['min_views']}, days≤{meta['days']}{shorts_note}",
        f"- Total processed: {meta['total_processed']}, passed filters: {len(rows)}",
        "",
        "## Results (sorted by ratio)",
        "",
        "| # | Type | Title | Channel | Views | Subs | Ratio | V/h | Date | URL |",
        "|---|------|-------|---------|-------|------|-------|-----|------|-----|",
    ]
    for i, r in enumerate(rows_sorted, 1):
        subs = "hidden" if r.subs_hidden else fmt_int(r.subs or 0)
        ratio = f"×{r.ratio:.1f}" if r.ratio is not None else "—"
        vph = f"{int(r.views_per_hour or 0):,}".replace(",", " ")
        title = r.title.replace("|", "\\|")[:70]
        ch = r.channel_title.replace("|", "\\|")[:25]
        vtype = "⚡ Short" if r.is_short else "🎬 Long"
        lines.append(
            f"| {i} | {vtype} | {title} | {ch} | {fmt_int(r.views)} | {subs} | {ratio} | {vph} | "
            f"{r.published_at.date()} | https://youtu.be/{r.video_id} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    load_dotenv(Path(__file__).parent / ".env")
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("ERROR: YOUTUBE_API_KEY not set. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 1

    args = parse_args()
    output_path = Path(args.output) if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mode = "urls" if args.urls else "search" if args.search else "channel"
    print(f"Mode: {mode} | Filters: ratio≥{args.min_ratio}, views≥{args.min_views}, days≤{args.days}")

    client = youtube_client(api_key)

    if args.urls:
        video_ids = load_urls(Path(args.urls))
        if not video_ids:
            print("ERROR: no valid video IDs in input file.", file=sys.stderr)
            return 1
        print(f"Fetching stats for {len(video_ids)} videos...")
        rows = fetch_videos(client, video_ids)
        attach_channel_stats(client, rows)
    elif args.search:
        print(f"Searching: {args.search!r} (region: {args.region}, last {args.days} days)...")
        video_ids = search_video_ids(client, args.search, args.region, args.days)
        if not video_ids:
            print("ERROR: no videos found for this query.", file=sys.stderr)
            return 1
        print(f"Found {len(video_ids)} videos. Fetching stats...")
        rows = fetch_videos(client, video_ids)
        attach_channel_stats(client, rows)
    else:
        print(f"Resolving channel: {args.channel!r}...")
        ch_id = resolve_channel_id(client, args.channel)
        if not ch_id:
            print(f"ERROR: channel {args.channel!r} not found.", file=sys.stderr)
            return 1
        print(f"Channel ID: {ch_id}. Fetching last {args.last} videos...")
        video_ids = fetch_recent_channel_videos(client, ch_id, args.last)
        if not video_ids:
            print("ERROR: no videos found in uploads playlist.", file=sys.stderr)
            return 1
        rows = fetch_videos(client, video_ids)
        attach_channel_stats(client, rows)

    total_processed = len(rows)
    compute_metrics(rows)
    filtered = apply_filters(
        rows, args.min_ratio, args.min_views, args.days,
        args.exclude_shorts, args.only_shorts,
    )

    meta = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "mode": mode,
        "min_ratio": args.min_ratio,
        "min_views": args.min_views,
        "days": args.days,
        "exclude_shorts": args.exclude_shorts,
        "only_shorts": args.only_shorts,
        "total_processed": total_processed,
    }
    write_report(output_path, filtered, meta)

    print(f"Done. Passed filters: {len(filtered)}/{total_processed}. Report: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
