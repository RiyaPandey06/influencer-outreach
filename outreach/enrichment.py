"""Stage 4: profile enrichment. Only extracts what the creator has *published*; never guesses."""
from __future__ import annotations

import re

from .db import DB
from .utils import EMAIL_RE, NOT_FOUND, log, valid_email

NA_PUBLIC = "Not Available (not exposed by public API)"
BLOCKED_EMAIL_DOMAINS = {"example.com", "email.com", "domain.com", "yourdomain.com", "sentry.io"}
PREFERRED = ("business", "collab", "contact", "partner", "hello", "pr", "brand", "work", "enquir", "inquir", "mail")
SOCIAL_HOSTS = ("youtube.com", "youtu.be", "instagram.com", "tiktok.com", "facebook.com", "fb.com",
                "twitter.com", "x.com", "wa.me", "t.me", "amzn.to", "bit.ly", "goo.gl")


def extract_email(text: str) -> str:
    """Return a published email from free text, or 'Not Found'."""
    if not text:
        return NOT_FOUND
    cleaned = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", text, flags=re.I)
    cleaned = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", cleaned, flags=re.I)
    found = []
    for m in EMAIL_RE.findall(cleaned):
        m = m.rstrip(".")
        domain = m.split("@")[1].lower()
        if domain in BLOCKED_EMAIL_DOMAINS or re.search(r"\.(png|jpe?g|gif|webp)$", m, re.I):
            continue
        if valid_email(m) and m.lower() not in [x.lower() for x in found]:
            found.append(m)
    if not found:
        return NOT_FOUND
    for e in found:
        if any(p in e.split("@")[0].lower() for p in PREFERRED):
            return e
    return found[0]


def extract_links(text: str) -> dict:
    text = text or ""
    ig = None
    m = re.search(r"instagram\.com/([A-Za-z0-9._]{2,30})", text, re.I)
    if m and m.group(1).lower() not in {"p", "reel", "reels", "explore", "stories", "accounts"}:
        ig = f"https://www.instagram.com/{m.group(1).rstrip('.')}"
    else:
        m = re.search(r"(?:instagram|insta|ig)\s*[:\-]?\s*@([A-Za-z0-9._]{2,30})", text, re.I)
        if m:
            ig = f"https://www.instagram.com/{m.group(1).rstrip('.')}"
    tt = None
    m = re.search(r"tiktok\.com/@([A-Za-z0-9._]{2,30})", text, re.I)
    if m:
        tt = f"https://www.tiktok.com/@{m.group(1).rstrip('.')}"
    site = None
    for url in re.findall(r"https?://[^\s<>\"')]+", text):
        url = url.rstrip(".,;")
        if not any(h in url.lower() for h in SOCIAL_HOSTS):
            site = url
            break
    return {"instagram_url": ig or NOT_FOUND, "tiktok_url": tt or NOT_FOUND, "website": site or NOT_FOUND}


def detect_themes(inf: dict, themes_cfg: dict, top_n: int = 4) -> list[str]:
    titles = " ".join(v["title"] for v in (inf.get("recent_videos") or []))
    tags = " ".join(inf.get("tags") or [])
    desc = inf.get("description") or ""
    scores = {}
    for theme, kws in themes_cfg.items():
        s = 0
        for kw in kws:
            pat = re.compile(rf"\b{re.escape(kw)}\b", re.I)
            s += 3 * len(pat.findall(titles)) + 1 * len(pat.findall(tags)) + 1 * min(len(pat.findall(desc)), 2)
        if s:
            scores[theme] = s
    return [t for t, _ in sorted(scores.items(), key=lambda kv: -kv[1])][:top_n]


def enrich(db: DB, cfg: dict) -> int:
    rows = db.influencers("metrics_collected=1 AND enriched=0")
    for r in rows:
        email = extract_email(r.get("description", ""))
        links = extract_links(r.get("description", ""))
        db.update(
            r["channel_id"],
            email=email,
            email_source="Published in YouTube channel description" if email != NOT_FOUND else None,
            content_themes=detect_themes(r, cfg.get("themes", {})) or ["Not Found"],
            audience_age=NA_PUBLIC, audience_gender=NA_PUBLIC,
            audience_geo=r.get("country") and f"Channel country: {r['country']} (audience split {NA_PUBLIC.lower()})" or NA_PUBLIC,
            enriched=1, **links)
    log.info("Enriched %d profiles", len(rows))
    return len(rows)
