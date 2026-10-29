"""Stage 1 & 2: discovery (find channels) and data collection (engagement metrics)."""
from __future__ import annotations

from .db import DB
from .utils import log
from .youtube import QuotaExceeded, YouTubeClient, compute_engagement, parse_channel


def _in_range(db: DB, cfg: dict) -> int:
    f = cfg["filter"]
    return db.count("followers BETWEEN ? AND ?", (f["min_followers"], f["max_followers"]))


def discover(client: YouTubeClient, db: DB, cfg: dict) -> dict:
    """Search by niche keywords until `target_in_range` micro-influencers are stored."""
    d = cfg["discovery"]
    seen = {r[0] for r in db.conn.execute("SELECT channel_id FROM influencers")}
    stats = {"searched_queries": 0, "new_channels": 0}
    try:
        for q in d["queries"]:
            if _in_range(db, cfg) >= d["target_in_range"]:
                break
            log.info("Searching: %r", q)
            stats["searched_queries"] += 1
            for ids in client.search_channels(q, d.get("max_pages_per_query", 3),
                                              d.get("region_code"), d.get("relevance_language")):
                new = [i for i in dict.fromkeys(ids) if i not in seen]
                if new:
                    for item in client.get_channels(new):
                        db.upsert_influencer(parse_channel(item, q))
                        seen.add(item["id"])
                        stats["new_channels"] += 1
                if _in_range(db, cfg) >= d["target_in_range"]:
                    break
    except QuotaExceeded:
        log.error("YouTube quota exhausted - stopping discovery with what we have.")
    stats["in_micro_range"] = _in_range(db, cfg)
    log.info("Discovery done: %s", stats)
    return stats


def collect(client: YouTubeClient, db: DB, cfg: dict) -> int:
    """Fetch recent videos and compute engagement for channels inside the follower range.

    (Out-of-range channels are not worth API quota; they are failed on follower count.)
    """
    f, c = cfg["filter"], cfg.get("collect", {})
    rows = db.influencers("followers BETWEEN ? AND ? AND metrics_collected=0", (f["min_followers"], f["max_followers"]))
    done = 0
    for r in rows:
        try:
            videos = client.get_recent_videos(r["uploads_playlist"], c.get("recent_videos", 10))
        except QuotaExceeded:
            log.error("Quota exhausted during collection; %d profiles collected so far.", done)
            break
        except Exception as exc:  # one bad channel must not stop the run
            log.warning("Skipping %s (%s): %s", r["name"], r["channel_id"], exc)
            continue
        er, note = compute_engagement(videos, c.get("min_videos_for_er", 3))
        tags = sorted({t.lower() for v in videos for t in v["tags"]})[:40]
        db.update(r["channel_id"],
                  recent_videos=[{k: v[k] for k in ("title", "published", "views", "likes", "comments", "url")}
                                 for v in videos],
                  tags=tags, engagement_pct=er, engagement_note=note,
                  last_upload=videos[0]["published"] if videos else None, metrics_collected=1)
        done += 1
    log.info("Collected metrics for %d profiles", done)
    return done
