"""Command-line entry point:  python -m outreach.pipeline <command>"""
from __future__ import annotations

import argparse
import sys

from .config import env, load_config
from .db import DB
from .utils import log, setup_logging


def _client():
    from .youtube import YouTubeClient
    return YouTubeClient(env("YOUTUBE_API_KEY") or "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="outreach", description="Automated micro-influencer outreach pipeline")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--db", default="data/outreach.db")
    p.add_argument("--out", default="data/output")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="search YouTube for candidate channels")
    sub.add_parser("collect", help="fetch recent videos + engagement for in-range channels")
    sub.add_parser("enrich", help="extract email/links/themes from published profile data")
    sub.add_parser("filter", help="classify + filter, with reasons")
    pz = sub.add_parser("personalize", help="generate email + DM for shortlisted influencers")
    pz.add_argument("--force", action="store_true", help="regenerate existing messages")
    ap = sub.add_parser("approve", help="human review gate before sending")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--ids", nargs="*", default=[])
    sd = sub.add_parser("send", help="simulate (default) or send approved emails")
    sd.add_argument("--live", action="store_true", help="really send via SMTP")
    sd.add_argument("--limit", type=int)
    md = sub.add_parser("mark-dm", help="record that an Instagram DM was sent manually")
    md.add_argument("channel_id")
    sub.add_parser("export", help="write CSV/MD deliverables")
    ra = sub.add_parser("run-all", help="discover -> collect -> filter -> enrich -> personalize [-> approve -> simulate send] -> export")
    ra.add_argument("--auto-approve", action="store_true", help="skip manual review (demo only)")
    sub.add_parser("status", help="show counts")
    a = p.parse_args(argv)

    setup_logging()
    cfg, db = load_config(a.config), DB(a.db)
    from . import discovery, enrichment, export, filtering, personalize, sender

    try:
        if a.cmd == "discover":
            discovery.discover(_client(), db, cfg)
        elif a.cmd == "collect":
            discovery.collect(_client(), db, cfg)
        elif a.cmd == "enrich":
            enrichment.enrich(db, cfg)
        elif a.cmd == "filter":
            filtering.run_filter(db, cfg)
        elif a.cmd == "personalize":
            personalize.run_personalize(db, cfg, a.force)
        elif a.cmd == "approve":
            n = db.approve_all() if a.all else db.approve(a.ids)
            log.info("Approved %d message(s)", n)
        elif a.cmd == "send":
            sender.run_send(db, cfg, live=a.live, limit=a.limit)
        elif a.cmd == "mark-dm":
            log.info("Marked." if sender.mark_dm_sent(db, a.channel_id) else "Unknown channel_id")
        elif a.cmd == "export":
            export.export_all(db, a.out)
        elif a.cmd == "status":
            print({"total": db.count(), "in_micro_range": db.count("followers BETWEEN ? AND ?",
                   (cfg["filter"]["min_followers"], cfg["filter"]["max_followers"])),
                   "passed": db.count("filter_status='Passed'"), "failed": db.count("filter_status='Failed'")})
        elif a.cmd == "run-all":
            c = _client()
            discovery.discover(c, db, cfg)
            discovery.collect(c, db, cfg)
            enrichment.enrich(db, cfg)
            filtering.run_filter(db, cfg)
            personalize.run_personalize(db, cfg)
            if a.auto_approve:
                db.approve_all()
                sender.run_send(db, cfg, live=False)
            else:
                log.info("Review personalized_messages.csv, then run: approve --all  and  send")
            export.export_all(db, a.out)
    except ValueError as exc:  # configuration problems (e.g. missing API key): no traceback needed
        log.error("%s", exc)
        return 2
    except Exception as exc:
        log.exception("Command failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
