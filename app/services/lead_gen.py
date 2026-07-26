"""Scout-powered lead generation service.

Wraps app.scrapers (adapted from kiryano/Scout) with tenant-scoped persistence
and CSV export for the operator dashboard.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from typing import Any, Callable, Optional

from app.models import Lead
from app.models.base import utcnow
from app.scrapers import (
    scrape_github,
    scrape_instagram,
    scrape_linkbio,
    scrape_linkedin,
    scrape_pinterest,
    scrape_tiktok,
    scrape_twitch,
    scrape_youtube,
)
from app.scrapers.enrichment import LeadEnricher
from app.scrapers.stealth import random_delay

logger = logging.getLogger(__name__)

SUPPORTED_PLATFORM_KEYS = (
    "instagram",
    "tiktok",
    "linkedin",
    "github",
    "youtube",
    "twitch",
    "linktree",
    "pinterest",
)

MAX_USERNAMES_PER_REQUEST = 10
DEFAULT_DELAY_RANGE = (0.4, 1.0)


def _platform_scrapers() -> dict[str, Callable[[str], Optional[dict]]]:
    # Resolve at call time so tests can patch scraper callables on this module.
    return {
        "instagram": scrape_instagram,
        "tiktok": scrape_tiktok,
        "linkedin": scrape_linkedin,
        "github": scrape_github,
        "youtube": scrape_youtube,
        "twitch": scrape_twitch,
        "linktree": scrape_linkbio,
        "pinterest": scrape_pinterest,
    }


class LeadGenError(Exception):
    """Base error for lead generation failures."""


class UnsupportedPlatformError(LeadGenError):
    def __init__(self, platform: str):
        self.platform = platform
        super().__init__(f"Unsupported platform: {platform}")


class LeadGenValidationError(LeadGenError):
    pass


def list_platforms() -> list[dict[str, Any]]:
    return [
        {"key": "instagram", "label": "Instagram", "auth_required": False},
        {"key": "tiktok", "label": "TikTok", "auth_required": False},
        {"key": "linkedin", "label": "LinkedIn", "auth_required": True},
        {"key": "github", "label": "GitHub", "auth_required": False},
        {"key": "youtube", "label": "YouTube", "auth_required": False},
        {"key": "twitch", "label": "Twitch", "auth_required": False},
        {"key": "linktree", "label": "Linktree / link-in-bio", "auth_required": False},
        {"key": "pinterest", "label": "Pinterest", "auth_required": False},
    ]


def normalize_usernames(raw_usernames: list[str] | str) -> list[str]:
    if isinstance(raw_usernames, str):
        parts = raw_usernames.replace(",", "\n").splitlines()
    else:
        parts = list(raw_usernames)

    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = str(part or "").strip().lstrip("@")
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return cleaned


def _delay_range(app: Any | None = None) -> tuple[float, float]:
    if app is not None:
        try:
            d_min = float(app.config.get("SCOUT_DELAY_MIN", DEFAULT_DELAY_RANGE[0]))
            d_max = float(app.config.get("SCOUT_DELAY_MAX", DEFAULT_DELAY_RANGE[1]))
            if d_max >= d_min >= 0:
                return (d_min, d_max)
        except (TypeError, ValueError):
            pass

    try:
        d_min = float(os.environ.get("SCOUT_DELAY_MIN", str(DEFAULT_DELAY_RANGE[0])))
        d_max = float(os.environ.get("SCOUT_DELAY_MAX", str(DEFAULT_DELAY_RANGE[1])))
        if d_max >= d_min >= 0:
            return (d_min, d_max)
    except ValueError:
        pass
    return DEFAULT_DELAY_RANGE


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def serialize_lead(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "tenant_id": lead.tenant_id,
        "platform": lead.platform,
        "username": lead.username,
        "full_name": lead.full_name or "",
        "bio": lead.bio or "",
        "profile_url": lead.profile_url or "",
        "website": lead.website or "",
        "email": lead.email or "",
        "phone": lead.phone or "",
        "follower_count": lead.follower_count,
        "following_count": lead.following_count,
        "email_score": lead.email_score,
        "email_source": lead.email_source or "",
        "email_verified": bool(lead.email_verified),
        "lead_score": lead.lead_score,
        "company_domain": lead.company_domain or "",
        "scraped_at": lead.scraped_at.isoformat() if lead.scraped_at else None,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


def _upsert_lead(session, tenant_id: str, platform: str, profile: dict[str, Any]) -> Lead:
    username = str(profile.get("username") or "").strip().lstrip("@")
    if not username:
        raise LeadGenValidationError("Scraped profile is missing username.")

    existing = (
        session.query(Lead)
        .filter(
            Lead.tenant_id == tenant_id,
            Lead.platform == platform,
            Lead.username == username,
        )
        .one_or_none()
    )

    now = utcnow()
    payload = {
        "full_name": (profile.get("full_name") or "")[:255] or None,
        "bio": profile.get("bio") or None,
        "profile_url": (profile.get("profile_url") or "")[:500] or None,
        "website": (profile.get("website") or "")[:500] or None,
        "email": (profile.get("email") or "")[:255] or None,
        "phone": (profile.get("phone") or "")[:64] or None,
        "follower_count": _as_int(profile.get("follower_count")),
        "following_count": _as_int(profile.get("following_count")),
        "email_score": _as_int(profile.get("email_score")),
        "email_source": (profile.get("email_source") or "")[:80] or None,
        "email_verified": bool(profile.get("email_verified")),
        "lead_score": _as_int(profile.get("lead_score")),
        "company_domain": (profile.get("company_domain") or "")[:255] or None,
        "raw_json": json.dumps(profile, default=str),
        "scraped_at": now,
        "updated_at": now,
    }

    if existing is None:
        lead = Lead(
            tenant_id=tenant_id,
            platform=platform,
            username=username,
            created_at=now,
            **payload,
        )
        session.add(lead)
        return lead

    for key, value in payload.items():
        setattr(existing, key, value)
    return existing


def _sync_scout_env(app: Any | None) -> None:
    """Push Flask config into process env for Scout modules that read os.environ."""
    if app is None:
        return
    mapping = (
        ("LINKEDIN_COOKIE", "LINKEDIN_COOKIE"),
        ("HUNTER_API_KEY", "HUNTER_API_KEY"),
        ("SCOUT_PROXY", "SCOUT_PROXY"),
        ("SCOUT_PROXY_FILE", "SCOUT_PROXY_FILE"),
        ("SCOUT_DELAY_MIN", "SCOUT_DELAY_MIN"),
        ("SCOUT_DELAY_MAX", "SCOUT_DELAY_MAX"),
    )
    for config_key, env_key in mapping:
        value = app.config.get(config_key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            os.environ[env_key] = text
    free_proxy = bool(app.config.get("SCOUT_FREE_PROXY", False))
    os.environ["SCOUT_FREE_PROXY"] = "true" if free_proxy else "false"


def scrape_and_store(
    db,
    tenant_id: str,
    platform: str,
    usernames: list[str] | str,
    *,
    enrich: bool = True,
    app: Any | None = None,
    hunter_api_key: str | None = None,
) -> dict[str, Any]:
    _sync_scout_env(app)

    platform_key = str(platform or "").strip().lower()
    scraper = _platform_scrapers().get(platform_key)
    if scraper is None:
        raise UnsupportedPlatformError(platform_key)

    cleaned = normalize_usernames(usernames)
    if not cleaned:
        raise LeadGenValidationError("Provide at least one username.")
    if len(cleaned) > MAX_USERNAMES_PER_REQUEST:
        raise LeadGenValidationError(
            f"At most {MAX_USERNAMES_PER_REQUEST} usernames per request."
        )

    if platform_key == "linkedin":
        cookie = ""
        if app is not None:
            cookie = str(app.config.get("LINKEDIN_COOKIE") or "").strip()
        if not cookie:
            cookie = str(os.environ.get("LINKEDIN_COOKIE") or "").strip()
        if not cookie:
            raise LeadGenValidationError(
                "LinkedIn scraping requires LINKEDIN_COOKIE to be configured."
            )

    if hunter_api_key is None and app is not None:
        hunter_api_key = str(app.config.get("HUNTER_API_KEY") or "").strip() or None
    if hunter_api_key is None:
        hunter_api_key = str(os.environ.get("HUNTER_API_KEY") or "").strip() or None

    enricher = LeadEnricher(hunter_api_key=hunter_api_key) if enrich else None
    delay_range = _delay_range(app)

    results: list[dict[str, Any]] = []
    stored: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    session = db.session()
    try:
        for index, username in enumerate(cleaned):
            item: dict[str, Any] = {"username": username, "ok": False}
            try:
                profile = scraper(username)
                if not profile:
                    item["message"] = "Profile not found"
                    errors.append({"username": username, "message": item["message"]})
                    results.append(item)
                else:
                    if enricher is not None:
                        profile = enricher.enrich_lead(profile)
                    lead = _upsert_lead(session, tenant_id, platform_key, profile)
                    session.flush()
                    serialized = serialize_lead(lead)
                    item["ok"] = True
                    item["lead"] = serialized
                    stored.append(serialized)
                    results.append(item)
            except RuntimeError as exc:
                message = str(exc)
                item["message"] = message
                errors.append({"username": username, "message": message})
                results.append(item)
                # Rate limits should stop the batch early.
                if "rate limited" in message.lower() or "429" in message:
                    break
            except Exception as exc:  # noqa: BLE001
                logger.exception("LEAD_GEN_SCRAPE_FAILED platform=%s username=%s", platform_key, username)
                message = str(exc)[:200] or "Scrape failed"
                item["message"] = message
                errors.append({"username": username, "message": message})
                results.append(item)

            if index < len(cleaned) - 1:
                random_delay(*delay_range)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return {
        "platform": platform_key,
        "requested": len(cleaned),
        "stored": len(stored),
        "failed": len(errors),
        "results": results,
        "leads": stored,
        "errors": errors,
    }


def list_leads(
    db,
    tenant_id: str,
    *,
    platform: str | None = None,
    has_email: bool | None = None,
    page: int = 1,
    per_page: int = 25,
) -> dict[str, Any]:
    if page < 1:
        raise LeadGenValidationError("page must be >= 1.")
    if per_page < 1 or per_page > 100:
        raise LeadGenValidationError("per_page must be between 1 and 100.")

    session = db.session()
    try:
        query = session.query(Lead).filter(Lead.tenant_id == tenant_id)
        if platform:
            query = query.filter(Lead.platform == platform.strip().lower())
        if has_email is True:
            query = query.filter(Lead.email.isnot(None), Lead.email != "")
        elif has_email is False:
            query = query.filter((Lead.email.is_(None)) | (Lead.email == ""))

        query = query.order_by(Lead.scraped_at.desc(), Lead.created_at.desc())
        total = query.count()
        rows = query.offset((page - 1) * per_page).limit(per_page).all()
        items = [serialize_lead(row) for row in rows]
        return {
            "page": page,
            "per_page": per_page,
            "total": total,
            "items": items,
        }
    finally:
        session.close()


def export_leads_csv(
    db,
    tenant_id: str,
    *,
    platform: str | None = None,
    has_email: bool | None = None,
) -> str:
    session = db.session()
    try:
        query = session.query(Lead).filter(Lead.tenant_id == tenant_id)
        if platform:
            query = query.filter(Lead.platform == platform.strip().lower())
        if has_email is True:
            query = query.filter(Lead.email.isnot(None), Lead.email != "")
        elif has_email is False:
            query = query.filter((Lead.email.is_(None)) | (Lead.email == ""))

        rows = query.order_by(Lead.scraped_at.desc(), Lead.created_at.desc()).all()
        fieldnames = [
            "platform",
            "username",
            "full_name",
            "email",
            "phone",
            "website",
            "profile_url",
            "follower_count",
            "lead_score",
            "email_score",
            "email_source",
            "email_verified",
            "company_domain",
            "bio",
            "scraped_at",
        ]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "platform": row.platform,
                    "username": row.username,
                    "full_name": row.full_name or "",
                    "email": row.email or "",
                    "phone": row.phone or "",
                    "website": row.website or "",
                    "profile_url": row.profile_url or "",
                    "follower_count": row.follower_count if row.follower_count is not None else "",
                    "lead_score": row.lead_score if row.lead_score is not None else "",
                    "email_score": row.email_score if row.email_score is not None else "",
                    "email_source": row.email_source or "",
                    "email_verified": "yes" if row.email_verified else "no",
                    "company_domain": row.company_domain or "",
                    "bio": (row.bio or "").replace("\n", " ").strip(),
                    "scraped_at": row.scraped_at.isoformat() if row.scraped_at else "",
                }
            )
        return buffer.getvalue()
    finally:
        session.close()
