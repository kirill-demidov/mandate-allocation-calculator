"""
electoral_laws.py — collect parliamentary electoral law URLs from three sources.

Sources (all three run; ACE/IFES supplement GLOBALCIT):
  1. GLOBALCIT  https://globalcit.eu/national-electoral-laws/
  2. ACE        https://aceproject.org/epic-en
  3. IFES       https://www.electionguide.org/countries/

Outputs:
  electoral.db              SQLite (append/create)
  electoral_laws.csv        flat export
  laws_coverage_report.txt  summary by source
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time

# ── auto-install ──────────────────────────────────────────────────────────────

def _ensure_deps() -> None:
    missing = []
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")
    try:
        import bs4  # noqa: F401
    except ImportError:
        missing.append("beautifulsoup4")
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])

_ensure_deps()

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

# ── constants ─────────────────────────────────────────────────────────────────

DB_PATH = "electoral.db"
CSV_PATH = "electoral_laws.csv"
REPORT_PATH = "laws_coverage_report.txt"
CACHE_DIR = "cache"
ERROR_LOG = "scrape_errors.log"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; electoral-laws-bot/1.0; "
        "+https://github.com/kirill-demidov/mandate-allocation-calculator)"
    )
}

# Names that are clearly not countries/territories — navigation noise
_SKIP_NAMES: frozenset[str] = frozenset({
    "cookie setting", "cookie settings", "home", "back", "next", "previous",
    "search", "login", "log in", "sign in", "menu", "contact", "about",
    "privacy", "terms", "sitemap", "subscribe", "newsletter", "donate",
    "share", "print", "download", "more", "read more", "see more",
    "comparative data",
})

# Primary keywords: laws specifically about electoral/seat-allocation system
_PRIMARY_KEYWORDS = (
    "electoral system", "election code", "electoral code", "election law",
    "electoral law", "parliament act", "parliamentary elections act",
    "proportional representation", "seat allocation", "constituency act",
    "voting act", "suffrage", "wahlgesetz", "wahlrecht", "code électoral",
    "ley electoral", "legge elettorale", "избирательный кодекс",
    "избирательный закон",
)

# Secondary keywords: broader electoral/legal documents
_SECONDARY_KEYWORDS = (
    "law", "act", "code", "constitution", "election", "electoral",
    "parliament", "loi", "ley", "gesetz", "legge", ".pdf",
)

# ── DB ────────────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS countries (
            id INTEGER PRIMARY KEY,
            country_name TEXT NOT NULL UNIQUE,
            iso_alpha2 TEXT,
            region TEXT
        );
        CREATE TABLE IF NOT EXISTS electoral_laws (
            id INTEGER PRIMARY KEY,
            country_id INTEGER REFERENCES countries(id),
            law_name TEXT,
            law_url TEXT NOT NULL,
            language TEXT,
            source TEXT,
            law_type TEXT,
            UNIQUE(country_id, law_url)
        );
        """
    )
    # safe migration: add law_type if missing in existing DB
    cols = {r[1] for r in conn.execute("PRAGMA table_info(electoral_laws)").fetchall()}
    if "law_type" not in cols:
        conn.execute("ALTER TABLE electoral_laws ADD COLUMN law_type TEXT")
    conn.commit()


def upsert_country(
    conn: sqlite3.Connection,
    name: str,
    iso2: str | None = None,
    region: str | None = None,
) -> int:
    name = name.strip()
    conn.execute(
        "INSERT OR IGNORE INTO countries(country_name, iso_alpha2, region) VALUES(?,?,?)",
        (name, iso2, region),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM countries WHERE country_name = ?", (name,)
    ).fetchone()
    return int(row[0])


def upsert_law(
    conn: sqlite3.Connection,
    country_id: int,
    name: str | None,
    url: str,
    lang: str | None,
    source: str,
    law_type: str = "general",
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO electoral_laws
            (country_id, law_name, law_url, language, source, law_type)
        VALUES (?,?,?,?,?,?)
        """,
        (country_id, name, url, lang, source, law_type),
    )
    conn.commit()


# ── HTTP + cache ──────────────────────────────────────────────────────────────

_last_fetch_time: float = 0.0


def fetch(url: str, cache: bool = True) -> str:
    global _last_fetch_time

    cache_key = hashlib.md5(url.encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, f"{cache_key}.html")

    if cache and os.path.exists(cache_path):
        print(f"    [cache] {url}")
        with open(cache_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    elapsed = time.time() - _last_fetch_time
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    print(f"    [GET]   {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text
        _last_fetch_time = time.time()
        print(f"    [OK]    {resp.status_code} — {len(html)} chars")
    except Exception as exc:
        logging.error("FETCH ERROR %s: %s", url, exc)
        print(f"    [ERR]   {url} — {exc}")
        _last_fetch_time = time.time()
        return ""

    if cache:
        with open(cache_path, "w", encoding="utf-8") as f:
            f.write(html)

    return html


# ── law classifier ────────────────────────────────────────────────────────────

def classify_law(url: str, text: str) -> str | None:
    """Return 'electoral_system', 'general', or None (skip)."""
    combined = (url + " " + text).lower()
    if any(kw in combined for kw in _PRIMARY_KEYWORDS):
        return "electoral_system"
    if any(kw in combined for kw in _SECONDARY_KEYWORDS):
        return "general"
    return None


def _looks_like_law(url: str, text: str, strict: bool = False) -> bool:
    combined = (url + " " + text).lower()
    keywords = _PRIMARY_KEYWORDS if strict else _PRIMARY_KEYWORDS + _SECONDARY_KEYWORDS
    return any(kw in combined for kw in keywords)


def _is_valid_name(name: str) -> bool:
    """Filter out navigation noise."""
    return len(name) >= 3 and name.lower() not in _SKIP_NAMES


# ── GLOBALCIT ─────────────────────────────────────────────────────────────────

GLOBALCIT_URL = "https://globalcit.eu/national-electoral-laws/"
GLOBALCIT_BASE = "https://globalcit.eu"


def scrape_globalcit(conn: sqlite3.Connection) -> None:
    print("\n=== GLOBALCIT ===")
    html = fetch(GLOBALCIT_URL)
    if not html:
        print("GLOBALCIT: failed to fetch index page")
        return

    soup = BeautifulSoup(html, "html.parser")

    # Attempt 1: find embedded JSON/JS array in <script> tags (DataTables data)
    if _globalcit_try_script_data(conn, html):
        return

    # Attempt 2: find DataTables ajax URL in JS config
    if _globalcit_try_ajax_url(conn, html):
        return

    # Attempt 3: WP REST API — laws as custom post type
    if _globalcit_try_wp_rest(conn):
        return

    # Attempt 4: static <table> in HTML
    table = soup.find("table")
    if table:
        print("GLOBALCIT: table found, parsing rows…")
        _globalcit_parse_table(conn, table)
        return

    # Attempt 5: headings fallback
    print("GLOBALCIT: no structured data found — using headings fallback")
    _scrape_globalcit_fallback(conn, soup)


def _globalcit_try_script_data(conn: sqlite3.Connection, html: str) -> bool:
    """Try to extract DataTables JSON embedded in <script> tags."""
    # Look for patterns like: var data = [...] or tableData([...]) or initTable([...])
    patterns = [
        r'var\s+\w*[Dd]ata\w*\s*=\s*(\[.*?\])\s*;',
        r'initDataTable\s*\(\s*(\[.*?\])\s*\)',
        r'"data"\s*:\s*(\[.*?\])',
        r'aaData\s*[=:]\s*(\[.*?\])',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list) or not data:
            continue
        print(f"GLOBALCIT: found embedded JSON array ({len(data)} rows)")
        count = _globalcit_parse_json_rows(conn, data)
        if count > 0:
            print(f"GLOBALCIT: done — {count} law URLs from embedded JSON")
            return True
    return False


def _globalcit_try_ajax_url(conn: sqlite3.Connection, html: str) -> bool:
    """Find DataTables ajax source URL and fetch it."""
    patterns = [
        r'"ajax"\s*:\s*["\']([^"\']+)["\']',
        r"'ajax'\s*:\s*'([^']+)'",
        r'"url"\s*:\s*"(https?://[^"]+(?:json|data|ajax)[^"]*)"',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if not m:
            continue
        ajax_url = m.group(1)
        if not ajax_url.startswith("http"):
            ajax_url = GLOBALCIT_BASE + ajax_url
        print(f"GLOBALCIT: found ajax URL → {ajax_url}")
        resp_text = fetch(ajax_url)
        if not resp_text:
            continue
        try:
            payload = json.loads(resp_text)
        except json.JSONDecodeError:
            continue
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        if not rows:
            continue
        count = _globalcit_parse_json_rows(conn, rows)
        if count > 0:
            print(f"GLOBALCIT: done — {count} law URLs from ajax endpoint")
            return True
    return False


def _globalcit_try_wp_rest(conn: sqlite3.Connection) -> bool:
    """Try WordPress REST API for custom post types."""
    candidates = [
        f"{GLOBALCIT_BASE}/wp-json/wp/v2/electoral-laws?per_page=100",
        f"{GLOBALCIT_BASE}/wp-json/wp/v2/posts?per_page=100&categories=electoral-laws",
        f"{GLOBALCIT_BASE}/wp-json/wp/v2/resource?per_page=100",
    ]
    for url in candidates:
        text = fetch(url)
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, list) or not data:
            continue
        print(f"GLOBALCIT: WP REST returned {len(data)} posts from {url}")
        count = 0
        for post in data:
            title = post.get("title", {}).get("rendered", "") or post.get("title", "")
            link = post.get("link", "") or post.get("url", "")
            country = post.get("country", "") or ""
            if not link:
                continue
            if country:
                cid = upsert_country(conn, country)
            else:
                continue
            law_type = classify_law(link, str(title)) or "general"
            upsert_law(conn, cid, str(title) or None, link, None, "GLOBALCIT", law_type)
            print(f"    + [{law_type}] {title} — {link}")
            count += 1
        if count > 0:
            print(f"GLOBALCIT: done — {count} law URLs from WP REST")
            return True
    return False


def _globalcit_parse_json_rows(conn: sqlite3.Connection, rows: list) -> int:
    """Parse DataTables-style JSON rows: each row is list or dict."""
    count = 0
    for row in rows:
        if isinstance(row, list):
            # Columns assumed: [country, title, year, language, type, link_html]
            country = str(row[0]).strip() if len(row) > 0 else ""
            title = str(row[1]).strip() if len(row) > 1 else ""
            lang = str(row[3]).strip() if len(row) > 3 else None
            link_cell = str(row[5]) if len(row) > 5 else str(row[-1])
        elif isinstance(row, dict):
            country = str(row.get("country", row.get("Country", ""))).strip()
            title = str(row.get("title", row.get("Title", row.get("law_name", "")))).strip()
            lang = str(row.get("language", row.get("Language", ""))) or None
            link_cell = str(row.get("link", row.get("Link", row.get("url", ""))))
        else:
            continue

        if not country or not _is_valid_name(country):
            continue

        # Extract URL from HTML fragment or plain URL
        urls = re.findall(r'href=["\']([^"\']+)["\']', link_cell)
        if not urls and link_cell.startswith("http"):
            urls = [link_cell]
        if not urls:
            continue

        cid = upsert_country(conn, country)
        for url in urls:
            law_type = classify_law(url, title) or "electoral_system"
            upsert_law(conn, cid, title or None, url, lang or None, "GLOBALCIT", law_type)
            print(f"    + [{law_type}] {country} — {title or '(no name)'} {url}")
            count += 1
    return count


def _globalcit_parse_table(conn: sqlite3.Connection, table) -> None:
    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr")
    print(f"GLOBALCIT: {len(rows)} table rows")
    current_country: str | None = None
    country_id: int | None = None
    total = 0

    for tr in rows:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        first_text = cells[0].get_text(strip=True)
        if first_text and first_text != current_country and len(cells) >= 2:
            first_link = cells[0].find("a")
            if first_link is None or not str(first_link.get("href", "")).startswith("http"):
                if _is_valid_name(first_text):
                    current_country = first_text
                    country_id = upsert_country(conn, current_country)
                    print(f"  country: {current_country}")

        if country_id is None:
            continue

        law_links = _extract_law_links(tr)
        if not law_links:
            continue

        law_name = cells[1].get_text(strip=True) if len(cells) > 1 else None
        lang = _detect_language_from_cells(cells)

        for link_url, link_text in law_links:
            lname = law_name or link_text or None
            law_type = classify_law(link_url, lname or "") or "electoral_system"
            upsert_law(conn, country_id, lname, link_url, lang, "GLOBALCIT", law_type)
            print(f"    + [{law_type}] {lname or '(no name)'} [{lang or '?'}] {link_url}")
            total += 1

    print(f"GLOBALCIT: done — {total} law URLs from table")


def _scrape_globalcit_fallback(conn: sqlite3.Connection, soup: BeautifulSoup) -> None:
    counts: dict[str, int] = {}
    current_country: str | None = None
    country_id: int | None = None

    for tag in soup.find_all(["h2", "h3", "h4", "p", "li", "a"]):
        if tag.name in ("h2", "h3", "h4"):
            text = tag.get_text(strip=True)
            if text and _is_valid_name(text):
                current_country = text
                country_id = upsert_country(conn, current_country)
                counts.setdefault(current_country, 0)
        elif tag.name == "a" and current_country and country_id is not None:
            href = str(tag.get("href", ""))
            text = tag.get_text(strip=True)
            if href.startswith("http") and _looks_like_law(href, text):
                law_type = classify_law(href, text) or "general"
                upsert_law(conn, country_id, text or None, href, None, "GLOBALCIT", law_type)
                counts[current_country] = counts.get(current_country, 0) + 1
                print(f"    + [{law_type}] {text or '(no name)'} {href}")

    total = sum(counts.values())
    print(f"GLOBALCIT(fallback): {total} URLs across {sum(1 for n in counts.values() if n)} countries")


def _extract_law_links(tag) -> list[tuple[str, str]]:
    results = []
    for a in tag.find_all("a"):
        href = str(a.get("href", "")).strip()
        text = a.get_text(strip=True)
        if href.startswith("http"):
            results.append((href, text))
    return results


def _detect_language_from_cells(cells: list) -> str | None:
    for cell in cells:
        text = cell.get_text(strip=True).lower()
        for lang in ("english", "french", "spanish", "german", "arabic", "russian",
                     "portuguese", "italian", "dutch", "japanese", "chinese",
                     "korean", "turkish", "polish", "czech", "hungarian"):
            if lang in text:
                return lang.capitalize()
    return None


# ── ACE ───────────────────────────────────────────────────────────────────────

ACE_INDEX_URL = "https://aceproject.org/epic-en"
ACE_BASE = "https://aceproject.org"

_ACE_SECTION_KEYWORDS = (
    "legal framework", "electoral law", "legislation", "legal basis",
    "electoral system", "election code", "statutes", "constitutional",
    "laws and regulations", "loi électorale", "marco legal",
)


def scrape_ace(conn: sqlite3.Connection) -> None:
    print("\n=== ACE Electoral Knowledge Network ===")
    html = fetch(ACE_INDEX_URL)
    if not html:
        print("ACE: failed to fetch index page")
        return

    soup = BeautifulSoup(html, "html.parser")
    country_links = _ace_country_links(soup)
    print(f"ACE: found {len(country_links)} country links")

    total = 0
    for i, (country_name, country_url) in enumerate(country_links, 1):
        print(f"  [{i}/{len(country_links)}] {country_name}")
        n = _ace_scrape_country(conn, country_name, country_url)
        if n > 0:
            print(f"    → {n} laws found")
        else:
            print(f"    → no law links")
        total += n

    print(f"ACE: done — {total} law URLs across {len(country_links)} countries")


def _ace_country_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        text = a.get_text(strip=True)
        if not text or len(text) < 2:
            continue
        if "/epic-en/" in href or "/ero/en/" in href or "/acereo/en/" in href:
            full = href if href.startswith("http") else ACE_BASE + href
            links.append((text, full))
    seen: set[str] = set()
    result = []
    for name, url in links:
        if url not in seen:
            seen.add(url)
            result.append((name, url))
    return result


def _ace_scrape_country(conn: sqlite3.Connection, country_name: str, url: str) -> int:
    html = fetch(url)
    if not html:
        return 0

    soup = BeautifulSoup(html, "html.parser")
    country_id = upsert_country(conn, country_name)
    count = 0

    legal_section = _find_section(soup, _ACE_SECTION_KEYWORDS)
    if legal_section:
        print(f"    [section found] scanning section only (strict=True)")
        strict = True
        search_root = legal_section
    else:
        print(f"    [no section] full page scan (strict=False)")
        strict = False
        search_root = soup

    for a in search_root.find_all("a", href=True):
        href = str(a["href"]).strip()
        text = a.get_text(strip=True)
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full = href if href.startswith("http") else ACE_BASE + href
        if _looks_like_law(full, text, strict=strict):
            law_type = classify_law(full, text) or "general"
            upsert_law(conn, country_id, text or None, full, None, "ACE", law_type)
            print(f"    + [{law_type}] {text or '(no name)'} {full}")
            count += 1

    return count


def _find_section(soup: BeautifulSoup, keywords: tuple[str, ...]):
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = heading.get_text(strip=True).lower()
        if any(kw in text for kw in keywords):
            parent = heading.find_parent(["section", "div", "article"])
            return parent if parent else heading.parent
    return None


# ── IFES ──────────────────────────────────────────────────────────────────────

IFES_INDEX_URL = "https://www.electionguide.org/countries/"
IFES_BASE = "https://www.electionguide.org"

_IFES_SECTION_KEYWORDS = (
    "legal framework", "electoral law", "legislation", "legal basis",
    "election law", "electoral system", "loi", "marco legal",
)


def scrape_ifes(conn: sqlite3.Connection) -> None:
    print("\n=== IFES ElectionGuide ===")
    html = fetch(IFES_INDEX_URL)
    if not html:
        print("IFES: failed to fetch index page")
        return

    soup = BeautifulSoup(html, "html.parser")
    country_links = _ifes_country_links(soup)
    print(f"IFES: found {len(country_links)} country links")

    total = 0
    for i, (country_name, country_url) in enumerate(country_links, 1):
        print(f"  [{i}/{len(country_links)}] {country_name}")
        n = _ifes_scrape_country(conn, country_name, country_url)
        if n > 0:
            print(f"    → {n} laws found")
        else:
            print(f"    → no law links")
        total += n

    print(f"IFES: done — {total} law URLs across {len(country_links)} countries")


def _ifes_country_links(soup: BeautifulSoup) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"])
        text = a.get_text(strip=True)
        if not text or not _is_valid_name(text):
            continue
        if "/countries/" in href and href != "/countries/":
            full = href if href.startswith("http") else IFES_BASE + href
            links.append((text, full))
    seen: set[str] = set()
    result = []
    for name, url in links:
        if url not in seen:
            seen.add(url)
            result.append((name, url))
    return result


def _ifes_scrape_country(conn: sqlite3.Connection, country_name: str, url: str) -> int:
    html = fetch(url)
    if not html:
        return 0

    soup = BeautifulSoup(html, "html.parser")
    country_id = upsert_country(conn, country_name)
    count = 0

    legal_section = _find_section(soup, _IFES_SECTION_KEYWORDS)
    if legal_section:
        print(f"    [section found] scanning section only (strict=True)")
        strict = True
        search_root = legal_section
    else:
        strict = False
        search_root = soup

    for a in search_root.find_all("a", href=True):
        href = str(a["href"]).strip()
        text = a.get_text(strip=True)
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full = href if href.startswith("http") else IFES_BASE + href
        if _looks_like_law(full, text, strict=strict):
            law_type = classify_law(full, text) or "general"
            upsert_law(conn, country_id, text or None, full, None, "IFES", law_type)
            print(f"    + [{law_type}] {text or '(no name)'} {full}")
            count += 1

    return count


# ── EXPORT ────────────────────────────────────────────────────────────────────

def export_csv(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT c.country_name, c.iso_alpha2, c.region,
               el.law_name, el.law_url, el.language, el.source, el.law_type
        FROM electoral_laws el
        JOIN countries c ON c.id = el.country_id
        ORDER BY c.country_name, el.law_type DESC, el.source, el.law_name
        """
    ).fetchall()

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["country_name", "iso_alpha2", "region",
                         "law_name", "law_url", "language", "source", "law_type"])
        writer.writerows(rows)

    print(f"\nCSV exported: {CSV_PATH} ({len(rows)} rows)")


def write_coverage_report(conn: sqlite3.Connection) -> None:
    total_countries = conn.execute("SELECT COUNT(*) FROM countries").fetchone()[0]

    with_laws = conn.execute(
        """
        SELECT c.country_name FROM countries c
        WHERE EXISTS (SELECT 1 FROM electoral_laws el WHERE el.country_id = c.id)
        ORDER BY c.country_name
        """
    ).fetchall()
    with_law_names = [r[0] for r in with_laws]

    without_laws = conn.execute(
        """
        SELECT c.country_name FROM countries c
        WHERE NOT EXISTS (SELECT 1 FROM electoral_laws el WHERE el.country_id = c.id)
        ORDER BY c.country_name
        """
    ).fetchall()
    without_law_names = [r[0] for r in without_laws]

    source_counts = conn.execute(
        "SELECT source, COUNT(*) FROM electoral_laws GROUP BY source ORDER BY source"
    ).fetchall()

    type_counts = conn.execute(
        "SELECT law_type, COUNT(*) FROM electoral_laws GROUP BY law_type ORDER BY law_type"
    ).fetchall()

    lines = [
        "=" * 60,
        "ELECTORAL LAWS COVERAGE REPORT",
        "=" * 60,
        f"Total countries in DB: {total_countries}",
        f"Countries WITH at least one law: {len(with_law_names)}",
        f"Countries WITHOUT any law: {len(without_law_names)}",
        "",
        "--- Laws by source ---",
        *[f"  {src}: {cnt}" for src, cnt in source_counts],
        "",
        "--- Laws by type ---",
        *[f"  {lt or 'None'}: {cnt}" for lt, cnt in type_counts],
        "",
        "--- Countries WITH laws ---",
        *[f"  {n}" for n in with_law_names],
        "",
        "--- Countries WITHOUT laws ---",
        *[f"  {n}" for n in without_law_names],
        "=" * 60,
    ]

    report = "\n".join(lines)
    print("\n" + report)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"Report written: {REPORT_PATH}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(CACHE_DIR, exist_ok=True)
    logging.basicConfig(
        filename=ERROR_LOG,
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        scrape_globalcit(conn)
        scrape_ace(conn)
        scrape_ifes(conn)
        export_csv(conn)
        write_coverage_report(conn)
    finally:
        conn.close()

    print("\nDone.")
