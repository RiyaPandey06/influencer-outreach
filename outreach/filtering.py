"""Stage 3: classification + filtering. Every decision is explained in `filter_reasons`."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .db import DB
from .utils import log


def _count_matches(text: str, keywords: list[str]) -> set[str]:
    return {kw for kw in keywords if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text, re.I)}


def _corpora(inf: dict) -> tuple[str, str]:
    titles = " ".join(v["title"] for v in (inf.get("recent_videos") or []))
    tags = " ".join(inf.get("tags") or [])
    profile = f"{inf.get('name','')} {inf.get('description','')}"
    return f"{profile} {titles} {tags}", f"{titles} {tags}"


def classify(inf: dict, cfg: dict) -> tuple[str, dict]:
    """Return (primary_category, {category: distinct_keyword_matches})."""
    full, _ = _corpora(inf)
    scores = {cat: len(_count_matches(full, kws)) for cat, kws in cfg["categories"].items()}
    best = max(scores, key=scores.get) if scores else "Unclassified"
    return (best if scores.get(best, 0) > 0 else "Unclassified"), scores


def evaluate(inf: dict, cfg: dict, now: datetime | None = None) -> tuple[str, list[str], str, str]:
    """Return (status, reasons, primary_category, niche_label)."""
    f = cfg["filter"]
    now = now or datetime.now(timezone.utc)
    targets = f["target_categories"]
    fails: list[str] = []
    passes: list[str] = []

    primary, scores = classify(inf, cfg)
    full, recent_text = _corpora(inf)

    # 1. follower count (platform is YouTube for every record)
    fol = inf.get("followers")
    in_range = False
    if fol is None:
        fails.append("subscriber count hidden or unavailable")
    elif fol < f["min_followers"]:
        fails.append(f"followers {fol:,} below micro minimum {f['min_followers']:,}")
    elif fol > f["max_followers"]:
        fails.append(f"followers {fol:,} above micro maximum {f['max_followers']:,}")
    else:
        in_range = True
        passes.append(f"followers {fol:,} within {f['min_followers']:,}-{f['max_followers']:,}")

    # 2. niche / category + content relevance
    target_kws = sorted({kw for t in targets for kw in cfg["categories"].get(t, [])})
    target_hits = _count_matches(full, target_kws)
    content_hits = _count_matches(recent_text, target_kws)
    target_scores = {t: scores.get(t, 0) for t in targets}
    best_target = max(target_scores, key=target_scores.get)
    niche_label = "Unclassified"
    if primary in targets and len(target_hits) >= f["min_niche_keywords"]:
        niche_label = best_target.title()
        others = [t for t in targets if t != best_target and target_scores[t] >= max(1, target_scores[best_target] * 0.5)]
        if others:
            niche_label = " & ".join([best_target.title()] + [o.title() for o in others])
        passes.append(f"niche {niche_label} ({len(target_hits)} {f['target_group_label']} keywords)")
    else:
        niche_label = primary.title() if primary != "Unclassified" else primary
        if primary not in targets:
            fails.append(f"primary niche is '{primary}', not {f['target_group_label']}")
        else:
            fails.append(f"only {len(target_hits)} {f['target_group_label']} keywords (need {f['min_niche_keywords']})")
    if in_range and inf.get("metrics_collected"):
        if len(content_hits) >= f["min_content_matches"]:
            passes.append(f"content relevant ({len(content_hits)} niche terms in recent videos)")
        else:
            fails.append(f"recent videos not relevant ({len(content_hits)} niche terms, need {f['min_content_matches']})")

    # 3. engagement + activity (only evaluated when metrics were collected)
    if in_range:
        er = inf.get("engagement_pct")
        if not inf.get("metrics_collected"):
            fails.append("metrics not collected")
        elif er is None:
            fails.append("engagement rate unavailable (likes hidden / too few videos)")
        elif er < f["min_engagement_pct"]:
            fails.append(f"engagement {er}% below {f['min_engagement_pct']}%")
        else:
            passes.append(f"engagement {er}% >= {f['min_engagement_pct']}%")
        lu = inf.get("last_upload")
        if inf.get("metrics_collected"):
            if not lu:
                fails.append("no recent uploads found")
            else:
                days = (now - datetime.fromisoformat(lu.replace("Z", "+00:00"))).days
                if days > f["max_days_since_upload"]:
                    fails.append(f"inactive: last upload {days} days ago (max {f['max_days_since_upload']})")
                else:
                    passes.append(f"active (last upload {days}d ago)")

    # 4. geography
    allowed = f.get("allowed_countries") or []
    if allowed:
        c = inf.get("country")
        if not c and f.get("require_known_country"):
            fails.append("country not listed")
        elif c and c not in allowed:
            fails.append(f"country {c} not in allowed list {allowed}")
        else:
            passes.append(f"geography ok ({c or 'unlisted'})")

    # 5. brand safety
    bad = _count_matches(f"{inf.get('name','')} {inf.get('description','')} {recent_text}", f.get("negative_keywords", []))
    if bad:
        fails.append(f"brand-safety keywords found: {sorted(bad)}")

    if fails:
        return "Failed", fails, primary, niche_label
    return "Passed", passes, primary, niche_label


def run_filter(db: DB, cfg: dict) -> dict:
    counts = {"Passed": 0, "Failed": 0}
    for r in db.influencers():
        status, reasons, primary, label = evaluate(r, cfg)
        _, scores = classify(r, cfg)
        db.update(r["channel_id"], filter_status=status, filter_reasons=reasons,
                  primary_category=primary, niche_label=label, niche_scores=scores)
        counts[status] += 1
    log.info("Filtering done: %s", counts)
    return counts
