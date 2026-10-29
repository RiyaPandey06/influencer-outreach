"""Stage 7: sending layer - email via SMTP (or dry-run simulation) + manual Instagram DM queue."""
from __future__ import annotations

import smtplib
import sqlite3
import time
from datetime import datetime, timezone
from email.message import EmailMessage

from .config import env
from .db import DB
from .utils import NOT_FOUND, log, valid_email


def _send_smtp(to: str, subject: str, body: str, footer: str) -> None:
    host, port = env("SMTP_HOST"), int(env("SMTP_PORT", "587"))
    user, pwd, sender = env("SMTP_USER"), env("SMTP_PASSWORD"), env("SMTP_FROM") or env("SMTP_USER")
    if not (host and user and pwd and sender):
        raise RuntimeError("SMTP_HOST / SMTP_USER / SMTP_PASSWORD / SMTP_FROM must be set in .env for live sending")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content(body + (f"\n\n--\n{footer}" if footer else ""))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)


def run_send(db: DB, cfg: dict, live: bool = False, limit: int | None = None) -> dict:
    """Send (live) or simulate (default) approved emails to shortlisted influencers with a valid email."""
    s_cfg = cfg.get("sending", {})
    limit = limit or s_cfg.get("max_per_run", 25)
    footer = s_cfg.get("email_footer", "")
    mode = "LIVE" if live else "DRY-RUN"
    stats = {"sent": 0, "simulated": 0, "skipped_no_email": 0, "skipped_not_approved": 0,
             "skipped_duplicate": 0, "failed": 0}
    rows = db.conn.execute(
        "SELECT i.channel_id, i.name, i.email, m.email_subject, m.email_body, m.approved "
        "FROM influencers i JOIN messages m USING(channel_id) WHERE i.filter_status='Passed' "
        "ORDER BY i.followers DESC").fetchall()
    attempted = 0
    for r in rows:
        if not valid_email(r["email"]):
            stats["skipped_no_email"] += 1
            continue
        if not r["approved"]:
            stats["skipped_not_approved"] += 1
            continue
        email = r["email"].strip().lower()
        blocked = ("Sent",) if live else ("Sent", "Simulated")
        dup = db.conn.execute(
            f"SELECT 1 FROM outreach_log WHERE lower(email)=? AND status IN ({','.join('?' for _ in blocked)})",
            (email, *blocked)).fetchone()
        if dup:
            stats["skipped_duplicate"] += 1
            continue
        if attempted >= limit:
            log.info("Reached max_per_run=%d; stopping.", limit)
            break
        attempted += 1
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        status, sent, err = "Simulated", 0, None
        if live:
            try:
                _send_smtp(r["email"], r["email_subject"], r["email_body"], footer)
                status, sent = "Sent", 1
            except Exception as exc:  # keep going; record failure; retry allowed next run
                status, err = "Failed", str(exc)[:300]
        try:
            db.conn.execute(
                "INSERT INTO outreach_log (channel_id, influencer, email, message_generated, sent, sent_at, status, mode, error) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (r["channel_id"], r["name"], email, 1, sent, now if status in ("Sent", "Simulated") else None,
                 status, mode, err))
            db.conn.commit()
        except sqlite3.IntegrityError:  # DB-level duplicate guard
            stats["skipped_duplicate"] += 1
            continue
        key = {"Sent": "sent", "Simulated": "simulated", "Failed": "failed"}[status]
        stats[key] += 1
        log.info("[%s] %s -> %s : %s%s", mode, r["name"], r["email"], status, f" ({err})" if err else "")
        if live and status == "Sent":
            time.sleep(s_cfg.get("delay_seconds", 5))
    log.info("Sending summary (%s): %s", mode, stats)
    return stats


def mark_dm_sent(db: DB, channel_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur = db.conn.execute("UPDATE messages SET dm_status='Sent manually', dm_marked_at=? WHERE channel_id=?",
                          (now, channel_id))
    db.conn.commit()
    return cur.rowcount > 0
