"""Stage 8: CSV / Markdown deliverables (dataset, messages, outreach tracker, DM queue)."""
from __future__ import annotations

import csv
from pathlib import Path

from .db import DB
from .utils import NOT_FOUND, log

NA = "Not Available"


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:  # utf-8-sig so Excel opens it correctly
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _join(v) -> str:
    return "; ".join(v) if isinstance(v, list) else (v if v else NA)


def export_all(db: DB, out_dir: str = "data/output") -> dict:
    out = Path(out_dir)
    infl = db.influencers()

    # A. dataset ------------------------------------------------------
    header = ["Name", "Platform", "Followers", "Engagement (%)", "Niche", "Email", "Profile URL", "Content Theme",
              "Status", "Filter Reason", "Country", "Instagram", "TikTok", "Website", "Audience Age",
              "Audience Gender", "Audience Geography", "Last Upload", "Email Source", "Discovery Query"]
    rows = []
    for r in infl:
        rows.append([
            r["name"], r["platform"],
            r["followers"] if r["followers"] is not None else f"{NA} (hidden)",
            r["engagement_pct"] if r["engagement_pct"] is not None else
            (r.get("engagement_note") or f"{NA} (not collected: outside follower range)"),
            r["niche_label"] or NA,
            r["email"] if r["email"] else "Not Enriched",
            r["profile_url"], _join(r["content_themes"]) if r["content_themes"] else NA,
            r["filter_status"], _join(r["filter_reasons"]), r["country"] or NOT_FOUND,
            r["instagram_url"] or NOT_FOUND, r["tiktok_url"] or NOT_FOUND, r["website"] or NOT_FOUND,
            r["audience_age"] or NA, r["audience_gender"] or NA, r["audience_geo"] or NA,
            r["last_upload"] or NA, r["email_source"] or NA, r["discovery_query"]])
    _write(out / "influencer_dataset.csv", header, rows)

    # C. messages -----------------------------------------------------
    shortlisted = db.influencers("filter_status='Passed'")
    mrows, md = [], ["# Personalized outreach messages (shortlisted influencers)\n"]
    for r in shortlisted:
        m = db.message(r["channel_id"])
        if not m:
            continue
        mrows.append([r["name"], r["email"], r["profile_url"], m["collab_angle"], m["email_subject"],
                      m["email_body"], m["instagram_dm"], m["generator"], m["model"] or "", "Yes" if m["approved"] else "No"])
        md += [f"## {r['name']}", f"- Profile: {r['profile_url']}", f"- Email: {r['email']}",
               f"- Angle: {m['collab_angle']}  |  Generator: {m['generator']}",
               f"\n**Email subject:** {m['email_subject']}\n", "```", m["email_body"], "```",
               f"\n**Instagram DM:** {m['instagram_dm']}\n"]
    _write(out / "personalized_messages.csv",
           ["Influencer", "Email", "Profile URL", "Collab Angle", "Email Subject", "Email Body", "Instagram DM",
            "Generator", "Model", "Approved"], mrows)
    (out / "personalized_messages.md").write_text("\n".join(md), encoding="utf-8")

    # D. outreach tracker --------------------------------------------
    trows = []
    for r in shortlisted:
        m = db.message(r["channel_id"])
        logs = db.conn.execute("SELECT * FROM outreach_log WHERE channel_id=? ORDER BY id DESC", (r["channel_id"],)).fetchall()
        if logs:
            for l in logs:
                trows.append([r["name"], l["email"], "Yes" if l["message_generated"] else "No",
                              "Yes" if l["sent"] else "No", l["sent_at"] or "", l["status"], l["mode"], l["error"] or ""])
        else:
            if r["email"] == NOT_FOUND or not r["email"]:
                status = "Skipped - email Not Found (Instagram DM queued for manual send)"
            elif m and not m["approved"]:
                status = "Pending review/approval"
            else:
                status = "Ready to send"
            trows.append([r["name"], r["email"] or NOT_FOUND, "Yes" if m else "No", "No", "", status, "", ""])
    _write(out / "outreach_tracker.csv",
           ["Influencer", "Email", "Message Generated", "Sent", "Date", "Status", "Mode", "Error"], trows)

    # Instagram DM manual queue ---------------------------------------
    drows = []
    for r in shortlisted:
        m = db.message(r["channel_id"])
        if m:
            drows.append([r["name"], r["instagram_url"] or NOT_FOUND, r["profile_url"], m["instagram_dm"], m["dm_status"],
                          m["dm_marked_at"] or ""])
    _write(out / "instagram_dm_queue.csv",
           ["Influencer", "Instagram URL", "YouTube Profile", "DM Text (copy-paste)", "DM Status", "Marked At"], drows)

    summary = {"dataset_rows": len(rows), "shortlisted": len(shortlisted), "messages": len(mrows),
               "tracker_rows": len(trows), "dm_queue": len(drows), "out_dir": str(out)}
    log.info("Exported: %s", summary)
    return summary
