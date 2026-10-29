"""SQLite storage: influencers, generated messages, outreach log."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

JSON_FIELDS = {"recent_videos", "tags", "niche_scores", "content_themes", "filter_reasons"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
    channel_id TEXT PRIMARY KEY,
    name TEXT, platform TEXT, profile_url TEXT, handle TEXT,
    followers INTEGER, subs_hidden INTEGER DEFAULT 0,
    engagement_pct REAL, engagement_note TEXT,
    country TEXT, description TEXT, uploads_playlist TEXT,
    video_count INTEGER, last_upload TEXT,
    recent_videos TEXT, tags TEXT, metrics_collected INTEGER DEFAULT 0,
    primary_category TEXT, niche_label TEXT, niche_scores TEXT, content_themes TEXT,
    email TEXT, email_source TEXT,
    instagram_url TEXT, tiktok_url TEXT, website TEXT,
    audience_age TEXT, audience_gender TEXT, audience_geo TEXT,
    enriched INTEGER DEFAULT 0,
    filter_status TEXT DEFAULT 'Pending', filter_reasons TEXT,
    discovery_query TEXT, discovered_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    channel_id TEXT PRIMARY KEY,
    email_subject TEXT, email_body TEXT, instagram_dm TEXT, collab_angle TEXT,
    generator TEXT, model TEXT, generated_at TEXT,
    approved INTEGER DEFAULT 0,
    dm_status TEXT DEFAULT 'Pending manual send', dm_marked_at TEXT
);
CREATE TABLE IF NOT EXISTS outreach_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT, influencer TEXT, email TEXT,
    message_generated INTEGER, sent INTEGER,
    sent_at TEXT, status TEXT, mode TEXT, error TEXT
);
-- Hard guarantee against duplicate outreach, enforced by the database itself:
CREATE UNIQUE INDEX IF NOT EXISTS uq_sent ON outreach_log(email) WHERE status = 'Sent';
CREATE UNIQUE INDEX IF NOT EXISTS uq_simulated ON outreach_log(email) WHERE status = 'Simulated';
"""


class DB:
    def __init__(self, path: str = "data/outreach.db"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(influencers)")}

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _enc(key: str, value):
        return json.dumps(value, ensure_ascii=False) if key in JSON_FIELDS and value is not None else value

    @staticmethod
    def _dec(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        for k in JSON_FIELDS & d.keys():
            if d[k]:
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    d[k] = None
        return d

    # -- influencers ---------------------------------------------------
    def upsert_influencer(self, data: dict) -> None:
        bad = set(data) - self._columns
        if bad:
            raise KeyError(f"Unknown influencer columns: {bad}")
        cols = list(data)
        placeholders = ",".join("?" for _ in cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "channel_id")
        sql = (f"INSERT INTO influencers ({','.join(cols)}) VALUES ({placeholders}) "
               f"ON CONFLICT(channel_id) DO UPDATE SET {updates}")
        self.conn.execute(sql, [self._enc(c, data[c]) for c in cols])
        self.conn.commit()

    def update(self, channel_id: str, **fields) -> None:
        self.upsert_influencer({"channel_id": channel_id, **fields})

    def influencers(self, where: str = "1=1", params: tuple = ()) -> list[dict]:
        rows = self.conn.execute(f"SELECT * FROM influencers WHERE {where} ORDER BY followers DESC", params)
        return [self._dec(r) for r in rows]

    def count(self, where: str = "1=1", params: tuple = ()) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM influencers WHERE {where}", params).fetchone()[0]

    # -- messages ------------------------------------------------------
    def save_message(self, channel_id: str, **fields) -> None:
        cols = ["channel_id", *fields]
        sql = (f"INSERT INTO messages ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
               f"ON CONFLICT(channel_id) DO UPDATE SET "
               + ",".join(f"{c}=excluded.{c}" for c in fields))
        self.conn.execute(sql, [channel_id, *fields.values()])
        self.conn.commit()

    def message(self, channel_id: str) -> dict | None:
        return self._dec(self.conn.execute("SELECT * FROM messages WHERE channel_id=?", (channel_id,)).fetchone())

    def approve_all(self) -> int:
        cur = self.conn.execute("UPDATE messages SET approved=1 WHERE approved=0")
        self.conn.commit()
        return cur.rowcount

    def approve(self, channel_ids: list[str]) -> int:
        n = 0
        for cid in channel_ids:
            n += self.conn.execute("UPDATE messages SET approved=1 WHERE channel_id=?", (cid,)).rowcount
        self.conn.commit()
        return n
