# Automated Micro-Influencer Outreach System
**EDXSO AI Engineer Intern – Assignment 1** · Niche implemented end-to-end: **Fashion & Beauty** · Platform: **YouTube**

A modular Python pipeline that discovers micro-influencers, classifies and filters them (with a written reason for every pass/fail), enriches profiles using only published data, generates personalized email + Instagram DM copy with an LLM, and sends (or simulates sending) with duplicate protection and a full outreach log.

```
Discovery → Data Collection → Filtering → Enrichment → AI Personalization → Review → Sending → Tracking
 YouTube      recent videos     rules +     email, links,   Claude API (+       human    SMTP /     CSV tracker
 search API   + engagement      reasons     themes          validated fallback) approve  dry-run    + SQLite log
```

> **Data integrity:** no influencer, email, or metric is fabricated or guessed. Anything unavailable is written as `Not Found` / `Not Available`. The only synthetic records in this repo live in `tests/` (clearly labelled) and are never written to `data/`.

---
## 1. Technology stack
Python 3.10+, `requests`, `PyYAML`, `python-dotenv`, SQLite (stdlib), `smtplib` (stdlib), `pytest`. No scraping frameworks, no browser automation.

## 2. APIs / tools used
| Purpose | Tool |
|---|---|
| Discovery + metrics | **YouTube Data API v3** (`search`, `channels`, `playlistItems`, `videos`) |
| Personalization | **Anthropic Claude Messages API** (model set by `ANTHROPIC_MODEL`, default `claude-sonnet-5-5`) |
| Email sending | **SMTP** (Gmail App Password works) – or dry-run simulation |
| Storage | SQLite (`data/outreach.db`) |

## 3. Data sources
Only the official YouTube Data API. Instagram/TikTok are **not scraped** (against their ToS); their handles are recorded only when the creator publishes them in their own channel description.

## 4. Discovery methodology
`config.yaml → discovery.queries` holds ~20 niche search phrases (skincare routine, outfit ideas, thrift haul, GRWM …). For each query the system pages through `search.list(type=channel)`, loads channel details in batches of 50, and stores every channel (pass or fail). It keeps searching until `target_in_range` (default **60**) channels fall inside the 5k–100k subscriber range, so the 50+ requirement is met by genuine micro-influencers. De-duplicates by channel id; stops gracefully if the API quota is exhausted.

**Data collection:** for in-range channels only (saves quota) the last 10 uploads are fetched. **Engagement rate = mean over recent videos of (likes + comments) ÷ views × 100.** If fewer than 3 videos expose likes/views the rate is stored as *Not Available* – never estimated.

## 5. Filtering & classification logic
Implemented for **Fashion & Beauty** (`filter.target_categories`); other niches are already defined as keyword dictionaries in `config.yaml` and only need the target list changed.

*Classification:* each category scores by the number of **distinct** keywords found in channel name + description + recent video titles + tags; the highest score is the primary niche (`Fashion`, `Beauty`, `Fashion & Beauty` when both are strong).

A channel **Passes** only if all checks succeed (all failures are listed, not just the first):
| Check | Rule (configurable) |
|---|---|
| Platform / followers | YouTube; 5,000 ≤ subscribers ≤ 100,000; hidden count = fail |
| Niche | primary category ∈ {fashion, beauty} and ≥ 4 distinct target keywords |
| Content relevance | ≥ 2 distinct target keywords in recent video titles/tags |
| Engagement | ≥ 2.0 % (must be measurable) |
| Activity | last upload ≤ 90 days ago |
| Geography | optional allow-list of countries (`allowed_countries`); channel country is self-declared |
| Brand safety | no negative keywords (casino, betting, NSFW …) |

Every record in `influencer_dataset.csv` has `Status` + `Filter Reason`, e.g. `Failed – followers 1,200 below micro minimum 5,000; engagement 0.8% below 2.0%`.

## 6. Enrichment process
For each profile (`enrichment.py`) – **extract, never infer**:
* **Email:** regex over the channel description; handles `name [at] domain [dot] com`; ignores placeholder domains; prefers business-style addresses (collab/business/contact…). No email published → `Not Found`. Nothing is guessed or pattern-generated.
* **Instagram / TikTok / website:** parsed from links or `IG: @handle` text in the description.
* **Content themes:** top themes (skincare, makeup, outfit styling, thrift fashion …) scored from recent titles, tags and description.
* **Audience age / gender / geography:** these are only visible to the channel owner (YouTube Analytics), so they are marked `Not Available (not exposed by public API)`; geography shows the channel's declared country.

## 7. AI model & prompt (runtime)
`personalize.py`, system prompt (excerpt – full text in `SYSTEM_PROMPT`):
> *You write short, genuine outreach messages from a brand to a micro-influencer. Use ONLY the facts in the JSON … Never invent videos, quotes, statistics, past collaborations … Reference at least one concrete signal … EMAIL: 60-90 words in total including greeting and sign-off … INSTAGRAM DM: 15-30 words … Output ONLY valid JSON with keys email_subject, email_body, instagram_dm, collab_angle.*

The user message is a JSON object of **real signals** from the profile: greeting name, niche, content themes, 5 recent video titles, a featured recent video, follower count, engagement, suggested collaboration angle and the campaign (brand, product, sender).

## 8. Personalization logic
1. **Signals** come only from collected data (recent video, themes, niche, size).
2. **Collab angle** is chosen by rule: review-style channels → UGC; <20k → barter; 20–50k → affiliate; ≥50k → paid sponsorship (restricted to `campaign.collab_types`).
3. **Validation (hard gate):** email 60–90 words, DM 15–30 words, no placeholders, creator greeted by name, and at least one concrete signal (theme or recent-video words) referenced.
4. **Retry:** on failure the exact problems are sent back to the model (up to 3 attempts).
5. **Fallback:** if there is no API key or the LLM fails, a rule-based generator (3 phrasing variants chosen per creator, length-controlled) produces compliant copy; each message records `generator` = `llm` or `template-fallback`.
6. **Review gate:** nothing is sent until messages are approved (`approve`).

## 9. Sending mechanism
* Selects shortlisted influencers with a **valid email** and an **approved** message; others are logged as skipped.
* **Dry-run by default** (`send`) → status `Simulated`. Real delivery only with `send --live` (SMTP). A short opt-out footer is appended.
* **Duplicate prevention at two levels:** application check + SQLite partial unique indexes on `outreach_log(email)` for `Sent` / `Simulated`. A failed send is logged with the error and may be retried; a simulation never blocks a later live send.
* **Outreach log:** table `outreach_log` + `logs/outreach.log` + `outreach_tracker.csv` (Influencer, Email, Message Generated, Sent, Date, Status, Mode, Error).
* **Instagram DMs:** Instagram's API doesn't permit cold DMs, so nothing is automated or bypassed. `instagram_dm_queue.csv` provides copy-paste DMs + profile links; `mark-dm <channel_id>` records a manual send.

## 10. Limitations (honest)
* YouTube only; Instagram/TikTok metrics are not collected.
* Emails exist only when the creator **publishes one in the description** (YouTube's "business email" field is behind a CAPTCHA and is intentionally not scraped). Expect a minority of profiles to have an email – the rest are `Not Found`.
* Subscriber counts are rounded by YouTube (3 significant figures); some channels hide them.
* Engagement is per-view (likes + comments)/views, not per-follower, and Shorts/long-form are not separated.
* Audience demographics are unavailable publicly. Country is self-declared and often blank.
* Keyword-based niche classification can misjudge channels with sparse text; thresholds are configurable.
* The greeting uses the channel name (e.g. "Hi Style With Sana") because real first names aren't reliably available.
* YouTube quota: 10,000 units/day (search = 100 units/page).

## 11. Setup & usage
```bash
git clone <your-repo> && cd influencer_outreach
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # add YOUTUBE_API_KEY (+ ANTHROPIC_API_KEY, SMTP_* for live sending)
# edit config.yaml → campaign.brand_name / product / sender_name
```
Get a YouTube key: Google Cloud Console → enable *YouTube Data API v3* → Credentials → API key.

```bash
python main.py run-all                 # discover → collect → enrich → filter → personalize → export
python main.py export                  # (re)write CSV/MD deliverables in data/output/
# review data/output/personalized_messages.csv, then:
python main.py approve --all           # or: approve --ids <channel_id> ...
python main.py send                    # DRY-RUN (simulated) – default
python main.py send --live             # real SMTP delivery
python main.py export                  # tracker now shows Sent/Simulated + dates
python main.py mark-dm <channel_id>    # after manually sending an Instagram DM
python main.py status
```
Each stage is also runnable alone: `discover`, `collect`, `enrich`, `filter`, `personalize [--force]`. All stages are idempotent and resumable.

**Outputs (`data/output/`)**: `influencer_dataset.csv` (all discovered, with status + reason) · `personalized_messages.csv/.md` · `outreach_tracker.csv` · `instagram_dm_queue.csv`.

**Tests:** `python -m pytest -q` (11 tests: filtering reasons, never-guess emails, message length rules, LLM retry/fallback, duplicate prevention, live-send failure/retry). Tests use a fake client with synthetic fixtures.

## 12. Scalability (50 → 500+)
Stages are decoupled and idempotent; add more `queries` or raise `target_in_range`. ~500 in-range channels needs roughly 50 search pages (≈5,000 units) + 2 units per collected channel, i.e. 1–2 days of free quota (or request a quota extension). For scale, swap SQLite for Postgres, run `collect`/`personalize` in worker queues, and add more platform adapters beside `youtube.py`.

## 13. AI assistance disclosure
This project was built with the help of an AI assistant (Claude). The prompt I gave and how I used the output are documented in [`docs/AI_ASSISTANCE.md`](docs/AI_ASSISTANCE.md).
