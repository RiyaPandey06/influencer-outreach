"""Stage 5: AI personalization (Claude API) with strict validation and a rule-based fallback."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

import requests

from .config import env
from .db import DB
from .utils import log, request_json, word_count

API_URL = "https://api.anthropic.com/v1/messages"
EMAIL_WORDS = (60, 90)
DM_WORDS = (15, 30)

SYSTEM_PROMPT = """You write short, genuine outreach messages from a brand to a micro-influencer.

RULES
1. Use ONLY the facts in the JSON the user sends. Never invent videos, quotes, statistics, past collaborations, \
tone claims or anything about the creator that is not in the JSON.
2. Reference at least one concrete signal: a recent video title or one of the content themes.
3. Address the creator with `greeting_name` exactly as given.
4. Propose the collaboration in `suggested_collab_angle` (or a better fit from `allowed_collab_types`) and state a \
clear value for the creator. Do not invent prices or numbers.
5. Sound like a real person: no "I hope this email finds you well", no buzzword stacking, no hashtags. \
No emojis in the email; at most one in the DM.
6. EMAIL: 60-90 words in total, INCLUDING the greeting line and the sign-off. Sign off with `sender_name`. \
Provide a short subject line (max 8 words).
7. INSTAGRAM DM: 15-30 words, casual, one idea, ends with a light question or call to action.
8. Output ONLY valid JSON with exactly these keys: email_subject, email_body, instagram_dm, collab_angle. \
No markdown fences, no commentary."""


# --------------------------------------------------------------------------- signals
def clean_name(title: str) -> str:
    seg = re.split(r"\s[|•–—\-:]\s|\(|\||•", title or "")[0].strip()
    return seg or (title or "there").strip() or "there"


_DANGLING = {"for", "and", "the", "with", "to", "of", "in", "a", "an", "on", "my", "your", "at", "or", "|", "&", "-"}


def short_title(title: str, n: int = 7) -> str:
    """Truncate a video title at a word boundary without leaving a dangling word or ellipsis."""
    words = re.sub(r"\s+", " ", re.sub(r"#\w+", "", title or "")).strip().split()[:n]
    while len(words) > 1 and words[-1].lower().strip(",.:;!?") in _DANGLING:
        words.pop()
    return " ".join(words).strip(" -|:,.!?")


def suggest_angle(inf: dict, cfg: dict) -> str:
    allowed = cfg["campaign"]["collab_types"]
    f = inf.get("followers") or 0
    themes = " ".join(inf.get("content_themes") or []).lower()
    if "reviews" in themes and "UGC content creation" in allowed:
        pick = "UGC content creation"
    elif f < 20000:
        pick = "Barter collaboration"
    elif f < 50000:
        pick = "Affiliate campaign"
    else:
        pick = "Paid sponsorship"
    return pick if pick in allowed else allowed[0]


def build_signals(inf: dict, cfg: dict) -> dict:
    vids = inf.get("recent_videos") or []
    themes = [t for t in (inf.get("content_themes") or []) if t != "Not Found"]
    # prefer a recent video that actually matches a theme word; else most recent
    pick = vids[0]["title"] if vids else ""
    for v in vids[:5]:
        if any(w in v["title"].lower() for t in themes for w in t.split()[:1]):
            pick = v["title"]
            break
    c = cfg["campaign"]
    return {
        "greeting_name": clean_name(inf["name"]),
        "channel_name": inf["name"],
        "platform": inf["platform"],
        "niche": inf.get("niche_label"),
        "content_themes": themes,
        "recent_video_titles": [v["title"] for v in vids[:5]],
        "featured_recent_video": pick,
        "followers": inf.get("followers"),
        "engagement_pct": inf.get("engagement_pct"),
        "suggested_collab_angle": suggest_angle(inf, cfg),
        "allowed_collab_types": c["collab_types"],
        "brand_name": c["brand_name"],
        "product": c["product"],
        "sender_name": c["sender_name"],
    }


# --------------------------------------------------------------------------- validation
def validate(msg: dict, signals: dict) -> list[str]:
    problems = []
    for key in ("email_subject", "email_body", "instagram_dm"):
        if not isinstance(msg.get(key), str) or not msg[key].strip():
            problems.append(f"missing {key}")
    if problems:
        return problems
    ew, dw = word_count(msg["email_body"]), word_count(msg["instagram_dm"])
    if not EMAIL_WORDS[0] <= ew <= EMAIL_WORDS[1]:
        problems.append(f"email_body has {ew} words; must be {EMAIL_WORDS[0]}-{EMAIL_WORDS[1]} including greeting and sign-off")
    if not DM_WORDS[0] <= dw <= DM_WORDS[1]:
        problems.append(f"instagram_dm has {dw} words; must be {DM_WORDS[0]}-{DM_WORDS[1]}")
    if re.search(r"[\[\]{}<>]", msg["email_body"] + msg["instagram_dm"]):
        problems.append("contains placeholder-like brackets")
    text = (msg["email_body"] + " " + msg["instagram_dm"]).lower()
    themes_ok = any(t.lower() in text for t in signals["content_themes"])
    title_words = {w for t in signals["recent_video_titles"] for w in re.findall(r"[a-z]{4,}", t.lower())}
    title_ok = len(title_words & set(re.findall(r"[a-z]{4,}", text))) >= 2
    if signals["content_themes"] or signals["recent_video_titles"]:
        if not (themes_ok or title_ok):
            problems.append("must reference a concrete signal (a content theme or recent video)")
    if msg["email_body"].lstrip()[:60].lower().find(signals["greeting_name"].lower()[:20]) == -1:
        problems.append("email must greet the creator using greeting_name")
    return problems


# --------------------------------------------------------------------------- LLM generation
def call_anthropic(payload: dict, api_key: str, session: requests.Session | None = None) -> dict:
    return request_json("POST", API_URL, session=session, json=payload, timeout=60,
                        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                                 "content-type": "application/json"})


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def llm_generate(signals: dict, api_key: str, model: str, attempts: int = 3) -> dict:
    messages = [{"role": "user", "content": "Creator data (JSON):\n" + json.dumps(signals, ensure_ascii=False)}]
    last_problems: list[str] = ["no attempt made"]
    for n in range(1, attempts + 1):
        resp = call_anthropic({"model": model, "max_tokens": 700, "system": SYSTEM_PROMPT, "messages": messages}, api_key)
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        try:
            msg = _parse_json(text)
        except (json.JSONDecodeError, ValueError):
            last_problems = ["response was not valid JSON"]
        else:
            last_problems = validate(msg, signals)
            if not last_problems:
                msg.setdefault("collab_angle", signals["suggested_collab_angle"])
                return msg
        log.info("LLM attempt %d/%d rejected: %s", n, attempts, "; ".join(last_problems))
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "Rejected: " + "; ".join(last_problems) +
                      ". Rewrite and return ONLY the corrected JSON."}]
    raise ValueError("LLM output failed validation: " + "; ".join(last_problems))


# --------------------------------------------------------------------------- rule-based fallback
ANGLE_PHRASE = {
    "Barter collaboration": ("a barter collaboration", "We'd send {product} for you to try, with complete creative freedom in how you feature it."),
    "Affiliate campaign": ("an affiliate partnership", "You'd earn a commission on every sale through your own link, plus free {product} to try."),
    "UGC content creation": ("a UGC content collaboration", "We'd send {product} and pay for content you create in your own style."),
    "Paid sponsorship": ("a paid sponsorship", "We'd offer a paid sponsorship and send {product}, keeping your creative direction intact."),
}
EXTRA = ["Happy to share details, timelines and deliverables whenever suits you.",
         "There's no pressure, and we're flexible on format and schedule."]


def _themes_phrase(themes: list[str]) -> str:
    t = [x.lower() for x in themes[:2]] or ["your niche"]
    return " and ".join(t)


def fallback_generate(signals: dict) -> dict:
    s = signals
    angle = s["suggested_collab_angle"]
    phrase, offer = ANGLE_PHRASE.get(angle, ANGLE_PHRASE["Barter collaboration"])
    offer = offer.format(product=s["product"])
    variant = int(hashlib.md5(s["channel_name"].encode()).hexdigest()[:8], 16) % 3
    themes = _themes_phrase(s["content_themes"])
    niche = (s["niche"] or "niche").lower()

    def email(title_words: int, extras: int) -> str:
        t = short_title(s["featured_recent_video"], title_words) or "your latest upload"
        lead = [
            f'I recently watched "{t}" and really enjoyed how you cover {themes}.',
            f'Your recent video "{t}" stood out to me, especially your {themes} content.',
            f'I\'ve been following your {themes} videos, and "{t}" was a favourite.',
        ][variant]
        fit = [
            f"Your {niche} audience looks like a natural fit for {s['brand_name']}, and we'd love to explore {phrase} with you.",
            f"We're {s['brand_name']}, and your {niche} community feels like exactly who we want to work with on {phrase}.",
            f"At {s['brand_name']} we think your {niche} audience would genuinely connect with us, so we'd like to propose {phrase}.",
        ][variant]
        cta = ["Would you be open to a quick chat about it?", "Could I send over the details?",
               "Would you like to hear more?"][variant]
        parts = [f"Hi {s['greeting_name']},", "", lead, fit, offer, *EXTRA[:extras], cta, "", "Best,", s["sender_name"]]
        return "\n".join(parts)

    body = None
    for tw, ex in [(6, 0), (6, 1), (6, 2), (4, 0), (3, 0), (4, 1), (3, 1)]:
        cand = email(tw, ex)
        if EMAIL_WORDS[0] <= word_count(cand) <= EMAIL_WORDS[1]:
            body = cand
            break
    body = body or email(4, 0)

    def dm(title_words: int) -> str:
        t = short_title(s["featured_recent_video"], title_words)
        who = s["greeting_name"]
        return [
            f'Hi {who}, loved your video "{t}". Your {niche} audience looks like a great fit for {s["brand_name"]}\'s {phrase} - open to chatting?',
            f'Hey {who}! Really enjoyed "{t}". We think your {themes} audience would love {s["brand_name"]} - up for {phrase}?',
            f'Hi {who}, your {themes} content is great, especially "{t}". Would you be interested in {phrase} with {s["brand_name"]}?',
        ][variant]

    dm_text = None
    for tw in (5, 4, 3, 2):
        cand = dm(tw)
        if DM_WORDS[0] <= word_count(cand) <= DM_WORDS[1]:
            dm_text = cand
            break
    dm_text = dm_text or dm(2)
    return {"email_subject": f"{s['brand_name']} x {s['greeting_name']}: {angle.lower()}"[:90],
            "email_body": body, "instagram_dm": dm_text, "collab_angle": angle}


# --------------------------------------------------------------------------- pipeline step
def run_personalize(db: DB, cfg: dict, force: bool = False) -> dict:
    api_key, model = env("ANTHROPIC_API_KEY"), env("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    if cfg["campaign"]["brand_name"] == "YourBrand":
        log.warning("campaign.brand_name is still the placeholder 'YourBrand' - edit config.yaml before real outreach.")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set - using the rule-based fallback generator.")
    stats = {"llm": 0, "fallback": 0, "skipped": 0}
    for inf in db.influencers("filter_status='Passed' AND enriched=1"):
        if db.message(inf["channel_id"]) and not force:
            stats["skipped"] += 1
            continue
        signals = build_signals(inf, cfg)
        generator, used_model = "template-fallback", None
        msg = None
        if api_key:
            try:
                msg = llm_generate(signals, api_key, model, cfg.get("personalization", {}).get("max_attempts", 3))
                generator, used_model = "llm", model
            except Exception as exc:
                log.warning("LLM generation failed for %s (%s) - using fallback", inf["name"], exc)
        if msg is None:
            msg = fallback_generate(signals)
        problems = validate(msg, signals)
        if problems:
            log.error("Message for %s still invalid (%s); not saved.", inf["name"], problems)
            continue
        db.save_message(inf["channel_id"], email_subject=msg["email_subject"].strip(),
                        email_body=msg["email_body"].strip(), instagram_dm=msg["instagram_dm"].strip(),
                        collab_angle=msg.get("collab_angle"), generator=generator, model=used_model,
                        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        stats["llm" if generator == "llm" else "fallback"] += 1
    log.info("Personalization done: %s", stats)
    return stats
