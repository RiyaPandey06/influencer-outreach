"""End-to-end tests using a FAKE YouTube client.

IMPORTANT: every record in this file is a SYNTHETIC TEST FIXTURE used only to verify code paths.
None of it is ever written to data/ and none of it may be submitted as influencer data.
"""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from outreach import discovery, enrichment, export, filtering, personalize, sender
from outreach.config import load_config
from outreach.db import DB
from outreach.utils import NOT_FOUND, word_count
from outreach.youtube import compute_engagement

NOW = datetime.now(timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def vids(titles, views=10000, likes=500, comments=50, days=3):
    return [{"id": f"v{i}", "title": t, "published": iso(days + i), "views": views, "likes": likes,
             "comments": comments, "tags": ["skincare", "makeup"], "url": f"https://x/{i}"} for i, t in enumerate(titles)]


BEAUTY_TITLES = ["My nightly skincare routine for glowing skin", "Drugstore makeup haul and review",
                 "Get ready with me: everyday makeup look", "Sunscreen serum moisturizer tier list",
                 "Hair care routine for curls"]
FASHION_TITLES = ["Spring outfit ideas and lookbook", "Thrift haul: styling denim", "Capsule wardrobe essentials",
                  "OOTD streetwear sneakers", "Saree styling tips"]

# (id, title, subs, hidden, country, description, videos)
FAKES = [
    ("A1", "Test Beauty One | Skincare", 12000, False, "IN",
     "Skincare and makeup reviews. Business: collab.testbeauty@gmail.com Instagram: @testbeauty1 https://testbeauty.example.org", vids(BEAUTY_TITLES)),
    ("A2", "Test Fashion Two", 45000, False, "US", "Outfit ideas, thrift haul, styling. Contact: hello [at] fashiontwo [dot] co", vids(FASHION_TITLES)),
    ("A3", "Test Beauty NoEmail", 8000, False, None, "Makeup tutorials and skincare routine, GRWM videos.", vids(BEAUTY_TITLES)),
    ("B1", "Too Big Beauty", 900000, False, "US", "makeup skincare beauty", []),
    ("B2", "Tiny Fashion", 800, False, "US", "fashion outfit", []),
    ("B3", "Hidden Subs Beauty", None, True, "US", "makeup skincare", []),
    ("B4", "Low Engagement Beauty", 20000, False, "IN", "skincare makeup beauty routine", vids(BEAUTY_TITLES, views=100000, likes=100, comments=5)),
    ("B5", "Gym Guy", 30000, False, "US", "workout gym fitness protein yoga cardio", vids(["Leg day workout", "Gym cardio routine", "Protein shake", "Yoga flow", "Training split"])),
    ("B6", "Inactive Beauty", 15000, False, "IN", "skincare makeup beauty routine", vids(BEAUTY_TITLES, days=400)),
    ("B7", "Casino Fashion", 15000, False, "IN", "fashion outfit styling lookbook casino betting", vids(FASHION_TITLES)),
    ("B8", "Likes Hidden Beauty", 25000, False, "IN", "skincare makeup beauty routine", [dict(v, likes=None) for v in vids(BEAUTY_TITLES)]),
]


class FakeClient:
    def search_channels(self, q, max_pages=3, region_code=None, relevance_language=None):
        yield [f[0] for f in FAKES]

    def get_channels(self, ids):
        out = []
        for f in FAKES:
            if f[0] in ids:
                st = {"hiddenSubscriberCount": True} if f[3] else {"subscriberCount": str(f[2]), "videoCount": "50"}
                out.append({"id": f[0], "snippet": {"title": f[1], "description": f[5], **({"country": f[4]} if f[4] else {})},
                            "statistics": st, "contentDetails": {"relatedPlaylists": {"uploads": "UU" + f[0]}}})
        return out

    def get_recent_videos(self, playlist, n=10):
        return next(f[6] for f in FAKES if "UU" + f[0] == playlist)


@pytest.fixture()
def env_ctx(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = load_config("config.yaml")
    cfg["discovery"]["target_in_range"] = 3
    cfg["campaign"].update(brand_name="TestBrand", sender_name="Sam from TestBrand")
    return cfg, DB(str(tmp_path / "t.db")), tmp_path


@pytest.fixture()
def piped(env_ctx):
    cfg, db, tmp = env_ctx
    c = FakeClient()
    discovery.discover(c, db, cfg)
    discovery.collect(c, db, cfg)
    enrichment.enrich(db, cfg)
    filtering.run_filter(db, cfg)
    return cfg, db, tmp


def by_id(db, cid):
    return db.influencers("channel_id=?", (cid,))[0]


def test_filter_pass_fail_with_reasons(piped):
    cfg, db, _ = piped
    for cid in ("A1", "A2", "A3"):
        assert by_id(db, cid)["filter_status"] == "Passed", by_id(db, cid)["filter_reasons"]
    expect = {"B1": "above micro maximum", "B2": "below micro minimum", "B3": "hidden",
              "B4": "engagement", "B5": "primary niche", "B6": "inactive", "B7": "brand-safety",
              "B8": "engagement rate unavailable"}
    for cid, frag in expect.items():
        r = by_id(db, cid)
        assert r["filter_status"] == "Failed", cid
        assert any(frag in x for x in r["filter_reasons"]), (cid, r["filter_reasons"])


def test_email_extraction_never_guesses(piped):
    _, db, _ = piped
    assert by_id(db, "A1")["email"] == "collab.testbeauty@gmail.com"
    assert by_id(db, "A2")["email"] == "hello@fashiontwo.co"      # published in obfuscated form
    assert by_id(db, "A3")["email"] == NOT_FOUND                    # nothing published -> Not Found
    assert enrichment.extract_email("write me at name@example.com") == NOT_FOUND
    assert enrichment.extract_email("") == NOT_FOUND


def test_enrichment_fields(piped):
    _, db, _ = piped
    r = by_id(db, "A1")
    assert r["instagram_url"] == "https://www.instagram.com/testbeauty1"
    assert r["website"].startswith("https://testbeauty.example.org")
    assert r["content_themes"] and r["content_themes"][0] != "Not Found"
    assert r["audience_age"].startswith("Not Available")


def test_engagement_never_fabricated():
    assert compute_engagement([], 3)[0] is None
    v = vids(["a", "b", "c"], views=1000, likes=40, comments=10)
    assert compute_engagement(v, 3)[0] == 5.0


def test_fallback_messages_meet_length_rules(piped):
    cfg, db, _ = piped
    personalize.run_personalize(db, cfg)
    for cid in ("A1", "A2", "A3"):
        m = db.message(cid)
        assert 60 <= word_count(m["email_body"]) <= 90, m["email_body"]
        assert 15 <= word_count(m["instagram_dm"]) <= 30, m["instagram_dm"]
        assert m["generator"] == "template-fallback"
    assert db.message("A1")["email_body"] != db.message("A2")["email_body"]  # not one fixed template


def test_fallback_lengths_on_many_names(piped):
    cfg, db, _ = piped
    inf = by_id(db, "A1")
    for i in range(300):
        inf2 = dict(inf, name=f"Creator{i} " * (1 + i % 4), followers=1000 * (i + 5))
        inf2["recent_videos"] = [dict(inf["recent_videos"][0], title=" ".join(["Very long title word"] * (1 + i % 8)))]
        s = personalize.build_signals(inf2, cfg)
        msg = personalize.fallback_generate(s)
        assert personalize.validate(msg, s) == [], (i, personalize.validate(msg, s), msg)


def test_llm_path_retries_then_accepts(piped, monkeypatch):
    """First reply per creator is invalid JSON, second breaks the DM length rule, third is valid."""
    import json
    cfg, db, _ = piped
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = {}

    def fake_api(payload, key, session=None):
        signals = json.loads(payload["messages"][0]["content"].split("\n", 1)[1])
        good = personalize.fallback_generate(signals)
        n = calls[signals["channel_name"]] = calls.get(signals["channel_name"], 0) + 1
        text = {1: "not json", 2: json.dumps({**good, "instagram_dm": "too short"})}.get(
            n, "```json\n" + json.dumps(good) + "\n```")
        return {"content": [{"type": "text", "text": text}]}

    monkeypatch.setattr(personalize, "call_anthropic", fake_api)
    st = personalize.run_personalize(db, dict(cfg, personalization={"max_attempts": 3}))
    assert st["llm"] == 3 and st["fallback"] == 0
    assert all(c == 3 for c in calls.values())
    assert db.message("A1")["generator"] == "llm"


def test_llm_failure_falls_back(piped, monkeypatch):
    cfg, db, _ = piped
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    def boom(*a, **k): raise RuntimeError("api down")
    monkeypatch.setattr(personalize, "call_anthropic", boom)
    st = personalize.run_personalize(db, cfg)
    assert st["fallback"] == 3 and st["llm"] == 0


def test_send_flow_dedupe_and_tracker(piped):
    cfg, db, tmp = piped
    personalize.run_personalize(db, cfg)
    s = sender.run_send(db, cfg)                      # nothing approved yet
    assert s["simulated"] == 0 and s["skipped_not_approved"] == 2 and s["skipped_no_email"] == 1
    db.approve_all()
    s = sender.run_send(db, cfg)
    assert s["simulated"] == 2 and s["skipped_no_email"] == 1
    s = sender.run_send(db, cfg)                      # re-run: no duplicates
    assert s["simulated"] == 0 and s["skipped_duplicate"] == 2
    assert db.conn.execute("SELECT COUNT(*) FROM outreach_log").fetchone()[0] == 2
    # DB-level guard: direct duplicate insert must fail
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO outreach_log (email,status) VALUES ('collab.testbeauty@gmail.com','Simulated')")
    out = export.export_all(db, str(tmp / "out"))
    assert out["dataset_rows"] == len(FAKES) and out["shortlisted"] == 3
    assert (tmp / "out" / "outreach_tracker.csv").read_text(encoding="utf-8-sig").count("Skipped - email Not Found") == 1


def test_live_send_failure_is_logged_and_retryable(piped, monkeypatch):
    cfg, db, _ = piped
    personalize.run_personalize(db, cfg)
    db.approve_all()
    monkeypatch.setattr(sender, "_send_smtp", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp down")))
    monkeypatch.setitem(cfg["sending"], "delay_seconds", 0)
    s = sender.run_send(db, cfg, live=True)
    assert s["failed"] == 2 and s["sent"] == 0
    monkeypatch.setattr(sender, "_send_smtp", lambda *a, **k: None)
    s = sender.run_send(db, cfg, live=True)           # failed rows are retried
    assert s["sent"] == 2
    assert sender.run_send(db, cfg, live=True)["skipped_duplicate"] == 2


def test_simulated_does_not_block_live(piped, monkeypatch):
    cfg, db, _ = piped
    personalize.run_personalize(db, cfg)
    db.approve_all()
    sender.run_send(db, cfg)
    monkeypatch.setattr(sender, "_send_smtp", lambda *a, **k: None)
    monkeypatch.setitem(cfg["sending"], "delay_seconds", 0)
    assert sender.run_send(db, cfg, live=True)["sent"] == 2
