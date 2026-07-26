# Scout Project Structure

Reference analysis of [kiryano/Scout](https://github.com/kiryano/Scout) (v1.3.1) — a Python CLI for social lead generation (scrape → enrich → CSV export).

Source inspected: `https://github.com/kiryano/Scout` on `main`.

## Integration in this app

Scout scrapers are vendored under `app/scrapers/` (MIT attribution in `app/scrapers/NOTICE`) and wired for operator lead generation:

| Piece | Path |
|-------|------|
| Scrapers + enrichment | `app/scrapers/` |
| Service | `app/services/lead_gen.py` |
| Routes / API | `app/lead_gen/routes.py` |
| UI | `app/templates/leads.html` (`/leads`) |
| Model | `Lead` in `app/models/__init__.py` |
| Migration | `migrations/versions/002_leads_table.py` |

Operator flow: open **Leads** → pick platform → enter usernames → scrape (optional enrich) → filter / export CSV. Config knobs live in `example.env` (`LINKEDIN_COOKIE`, `HUNTER_API_KEY`, `SCOUT_*`).

## Overview

Scout is a flat CLI monorepo:

- One entry script (`scout.py`) for the interactive Rich UI
- One package (`app/scrapers/`) for platform scrapers, stealth helpers, and enrichment
- No web server, database, or in-repo tests
- Config via `.env` (+ optional proxy list file)

## Directory layout

```text
Scout/
├── scout.py                 # CLI: menu, scrape loops, CSV export (~1139 LOC)
├── requirements.txt         # requests, httpx, dnspython, free-proxy, rich
├── .env.example             # LINKEDIN_COOKIE, HUNTER_API_KEY, proxy knobs
├── proxies.example.txt
├── README.md
├── LICENSE
├── screenshot.png
└── app/
    ├── __init__.py          # __version__ = "1.3.1"
    └── scrapers/
        ├── __init__.py      # public scrape_* re-exports
        ├── instagram.py
        ├── tiktok.py
        ├── linkedin.py      # requires li_at cookie
        ├── github.py
        ├── youtube.py
        ├── twitch.py
        ├── pinterest.py
        ├── linktree.py      # Linktree / Stan / Linkr / Bio.link
        ├── enrichment.py    # LeadEnricher + SMTP / optional Hunter.io
        ├── stealth.py       # UA rotation, proxies, retry decorator
        └── utils.py         # email / phone / abbreviated-number helpers
```

Approximate size: ~3.3k lines of Python across `scout.py` + scrapers.

## Runtime flow

```text
scout.py:main()
  → load .env
  → optional GitHub release version check (can hard-exit if outdated)
  → show_menu()
  → platform interactive scraper
       → _collect_usernames()
       → _standard_scrape_loop(scraper_func, items)
       → enrich_profiles()  # optional LeadEnricher
       → CSV export via csv.DictWriter
```

| Stage | Owner | Responsibility |
|-------|--------|----------------|
| Boot | `scout.py` | `.env`, logging, update check |
| Menu | `show_menu()` | Platforms 1–8, bulk (9), exports (10), settings (11) |
| Scrape | `app/scrapers/*` | HTTP fetch + parse → normalized profile dict |
| Enrich | `LeadEnricher` | Bio/website/SMTP/Hunter → scores |
| Export | `_standard_export` | `{platform}_export_{timestamp}.csv` |

## Layers

### CLI shell (`scout.py`)

Owns UX (Rich panels/tables/progress), shared scrape loop, enrichment prompt, CSV I/O, and settings that rewrite `.env`.

Important helpers:

- `_standard_scrape_loop` — per-item spinner, delay, error handling
- `_standard_export` — summary → enrich → CSV
- `_collect_usernames` — interactive username list input
- `enrich_profiles` — wraps `LeadEnricher`
- `settings_menu` — proxy, delay, LinkedIn cookie, clear exports

### Scraper package (`app/scrapers/`)

Each platform module exposes one primary function returning `Optional[Dict]`. Cross-cutting modules:

- `stealth.py` — user-agent rotation, proxy selection (single / file / free pool), delay, retry
- `utils.py` — `extract_email`, `extract_phone`, `parse_abbreviated_number`
- `enrichment.py` — post-scrape contact discovery and scoring

Public exports from `app/scrapers/__init__.py`:

`scrape_instagram`, `scrape_tiktok`, `scrape_linkedin`, `scrape_github`, `scrape_youtube`, `scrape_twitch`, `scrape_linktree`, `scrape_linkbio`, `scrape_pinterest`.

## Platform scrapers

| Module | Entry function | Auth | Notes |
|--------|----------------|------|-------|
| `instagram.py` | `scrape_profile_no_login` | None | Mobile UA + HTML regex; retries + proxy rotate |
| `tiktok.py` | `scrape_tiktok_profile` | None | httpx; CAPTCHA risk by region/IP |
| `linkedin.py` | `scrape_linkedin_profile` | `LINKEDIN_COOKIE` | `li_at` session; `validate_cookie()` |
| `github.py` | `scrape_profile` | None | Public API; 60 req/h without token |
| `youtube.py` | `scrape_channel` | None | Channel HTML + redirect cleanup |
| `twitch.py` | `scrape_profile` | None | Falls back to direct if proxy fails |
| `pinterest.py` | `scrape_profile` | None | Walks `__PWS_DATA__` JSON |
| `linktree.py` | `scrape_all` / `scrape_linktree` | None | Multi link-in-bio platforms |

## Normalized profile contract

Scrapers converge on a flat dict. Instagram example fields:

```python
{
    "username": "...",
    "full_name": "...",
    "bio": "...",
    "follower_count": 0,
    "following_count": 0,
    "post_count": 0,
    "is_verified": False,
    "is_private": False,
    "is_business": False,
    "website": "",
    "email": "",
    "phone": "",
    "platform": "instagram",
    "profile_url": "https://www.instagram.com/.../",
}
```

Enrichment may add: `email_score`, `email_source`, `email_verified`, `company_domain`, `lead_score`, `possible_emails`.

## Enrichment pipeline

`LeadEnricher.enrich_lead()` (`app/scrapers/enrichment.py`):

1. Extract email/phone from bio text
2. Deep-scrape website `/contact` and `/about` pages
3. Detect company domain from headline + DNS MX
4. Infer email patterns from emails found on site
5. Generate candidates (`first.last@`, `first@`, …)
6. Verify candidates over SMTP
7. Optional Hunter.io lookup when `HUNTER_API_KEY` is set
8. Score email confidence and overall `lead_score` (0–100)

No paid API is required for the default path.

## Configuration

| Variable | Purpose |
|----------|---------|
| `LINKEDIN_COOKIE` | LinkedIn `li_at` cookie |
| `HUNTER_API_KEY` | Optional email finder |
| `SCOUT_PROXY` | Single HTTP proxy URL |
| `SCOUT_PROXY_FILE` | Rotating proxy list path |
| `SCOUT_FREE_PROXY` | Enable free-proxy pool (`true`/`false`) |
| `SCOUT_DELAY_MIN` / `SCOUT_DELAY_MAX` | Inter-scrape delay range (seconds) |

## Dependencies

From `requirements.txt`:

- `requests>=2.28.0`
- `httpx>=0.27.0`
- `dnspython>=2.4.0`
- `free-proxy>=1.1.1`
- `rich>=13.7.0`

No lockfile is published.

## Design notes

**Strengths**

- Clear scrape → enrich → export pipeline
- Consistent profile dict across platforms
- Shared CLI loop helpers keep per-platform interactive code thin
- Stealth concerns isolated from HTML/API parsers

**Gaps (relevant if building a web/CRM follow-on)**

- No tests, packaging metadata, or typed models
- CSV-only persistence (no DB)
- Update checker can hard-exit the CLI when a newer release exists
- Upstream README positions dashboard/CRM/team features as future work

## Related

Interactive canvas: `.cursor/projects/workspace/canvases/scout-project-structure.canvas.tsx` (local agent canvas; not committed to git).
