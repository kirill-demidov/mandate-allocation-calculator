"""Генерация и хранение выжимок избирательных законов через Claude API."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; electoral-laws-bot/1.0; "
        "+https://github.com/kirill-demidov/mandate-allocation-calculator)"
    )
}

_SYSTEM_PROMPT = """\
You are an expert in comparative electoral systems.
Given a text excerpt from an electoral law (or just the country and law name \
if no text is available), write a concise 2–3 sentence summary explaining:
1. The electoral system type (proportional, majoritarian, or mixed).
2. The seat allocation method (D'Hondt, Sainte-Laguë, Hare, etc.) if specified.
3. The electoral threshold (%) if mentioned.
Respond ONLY with valid JSON and nothing else: {"en": "...", "ru": "..."}"""

_lock = threading.Lock()


def _summaries_path() -> Path:
    raw = os.getenv("PARLGOV_DATA_DIR", "").strip()
    base = Path(raw) if raw else Path(os.getenv("TMPDIR", "/tmp")) / "parlgov"
    base.mkdir(parents=True, exist_ok=True)
    return base / "country_summaries.json"


def load_summaries() -> dict[str, object]:
    p = _summaries_path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_summaries(data: dict[str, object]) -> None:
    p = _summaries_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── law lookup ────────────────────────────────────────────────────────────────

def _find_law(country_name: str) -> tuple[str | None, str | None]:
    """Return (law_name, law_url) from electoral.db, or (None, None)."""
    db_path = os.getenv("ELECTORAL_DB_PATH", "").strip()
    if not db_path:
        db_path = "electoral.db"
    if not Path(db_path).is_file():
        logger.info("ELECTORAL_DB_PATH not found (%s), skipping law lookup", db_path)
        return None, None
    try:
        conn = sqlite3.connect(db_path)
        name_norm = country_name.strip().lower()
        rows = conn.execute(
            """
            SELECT el.law_name, el.law_url
            FROM electoral_laws el
            JOIN countries c ON c.id = el.country_id
            WHERE el.law_type = 'electoral_system'
            ORDER BY c.country_name, el.id
            """
        ).fetchall()
        conn.close()

        # exact match first
        for law_name, law_url in rows:
            pass  # just to warm up

        # normalised match
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            """
            SELECT c.country_name, el.law_name, el.law_url, el.law_type
            FROM electoral_laws el
            JOIN countries c ON c.id = el.country_id
            WHERE el.law_type = 'electoral_system'
            ORDER BY el.id
            """
        ).fetchall()
        conn.close()

        for db_country, law_name, law_url, _ in rows:
            if db_country.strip().lower() == name_norm:
                return law_name, law_url

        # fuzzy: check if name_norm is contained
        for db_country, law_name, law_url, _ in rows:
            if name_norm in db_country.strip().lower() or db_country.strip().lower() in name_norm:
                return law_name, law_url

        return None, None
    except Exception as exc:
        logger.warning("Law lookup failed: %s", exc)
        return None, None


# ── text extraction ───────────────────────────────────────────────────────────

def _extract_text(url: str, max_chars: int = 6000) -> str:
    """Fetch law page and return plain text excerpt."""
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").lower()

        if "pdf" in content_type or url.lower().endswith(".pdf"):
            return _extract_pdf(resp.content, max_chars)

        # HTML / plain text
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
        except Exception:
            text = resp.text

        return text[:max_chars]
    except Exception as exc:
        logger.warning("Text extraction failed for %s: %s", url, exc)
        return ""


def _extract_pdf(content: bytes, max_chars: int) -> str:
    try:
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        import io

        out = io.StringIO()
        extract_text_to_fp(BytesIO(content), out, laparams=LAParams())
        return out.getvalue()[:max_chars]
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        return ""


# ── Claude API ────────────────────────────────────────────────────────────────

def _call_claude(
    anthropic_key: str,
    country_name: str,
    law_name: str | None,
    text: str,
) -> dict[str, str]:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed")

    user_content = f"Country: {country_name}\n"
    if law_name:
        user_content += f"Law: {law_name}\n"
    if text:
        user_content += f"\nText excerpt:\n{text}"
    else:
        user_content += "\n(No law text available — summarize based on country name only.)"

    client = anthropic.Anthropic(api_key=anthropic_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    raw = msg.content[0].text.strip()

    # strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
        return {"en": str(result.get("en", "")), "ru": str(result.get("ru", ""))}
    except json.JSONDecodeError:
        return {"en": raw, "ru": ""}


# ── public API ────────────────────────────────────────────────────────────────

def generate_summary(
    country_code: str,
    country_name: str,
    anthropic_key: str,
) -> dict[str, object]:
    """Generate and persist a law summary for one country."""
    law_name, law_url = _find_law(country_name)
    logger.info(
        "generate_summary: %s (%s) law=%s url=%s",
        country_code, country_name, law_name, law_url,
    )

    text = _extract_text(law_url) if law_url else ""
    if text:
        logger.info("Extracted %d chars from %s", len(text), law_url)
    else:
        logger.info("No text extracted, using name-only context")

    summaries = _call_claude(anthropic_key, country_name, law_name, text)

    record: dict[str, object] = {
        "summary_en": summaries["en"],
        "summary_ru": summaries["ru"],
        "law_name": law_name,
        "law_url": law_url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        data = load_summaries()
        data[country_code] = record
        _save_summaries(data)

    return {"country_code": country_code, **record}
