"""Единый ETL-store: ParlGov + CLEA → reference.duckdb.

Один файл, одно write-соединение — нет конкурентных writer'ов, нет ATTACH/DETACH.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

VIEW_ELECTION_CSV = (
    "https://parlgov.org/data/parlgov-development_csv-utf-8/view_election.csv"
)
ELECTION_CSV = "https://parlgov.org/data/parlgov-development_csv-utf-8/election.csv"

_CLEA_ALIASES: dict[str, list[str]] = {
    "ctr": ["ctr", "ctr_n", "country", "ccode", "cntry", "iso_n"],
    "yr": ["yr", "year", "elec_yr", "year_elec"],
    "mn": ["mn", "mon", "month", "mo"],
    "dy": ["dy", "day", "day_elec"],
    "cst": ["cst", "const", "constituency", "district", "dist"],
    "pty_n": ["pty_n", "pty_nam", "party_name", "partyname", "pnames", "party"],
    "pty": ["pty", "party_id", "partycode", "party_code"],
    "pv1": ["pv1", "pv_1", "partyvotes", "party_votes", "votes"],
    "vv1": ["vv1", "vv_1", "valid_votes", "validvotes", "totv1"],
    "seat": ["seat", "seats", "seat1", "s"],
    "thr": [
        "tm", "tms", "th", "nthr", "nat_thr", "natthr",
        "ethresh", "ethr", "elthr", "pr_thr", "prthr",
        "thresh", "threshold", "legal_thr", "legal_threshold", "elec_thresh",
    ],
    "mag": ["mag", "mag_n", "dm", "dstm", "district_magnitude", "magnitude"],
    "ctr_n": ["ctr_n", "cntry_n", "country_name", "countryname", "cntry"],
}


def _data_dir() -> Path:
    raw = os.getenv("PARLGOV_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(os.getenv("TMPDIR", "/tmp")) / "parlgov"


def _clea_csv_path() -> Path | None:
    p = os.getenv("CLEA_CSV_PATH", "").strip()
    if p:
        return Path(p)
    clea_dir = os.getenv("CLEA_DATA_DIR", "").strip()
    if not clea_dir:
        return None
    ddir = Path(clea_dir)
    if not ddir.is_dir():
        return None
    for name in ("clea.csv", "clea_constituency.csv", "CLEA.csv"):
        cand = ddir / name
        if cand.is_file():
            return cand
    csvs = sorted(ddir.glob("*.csv"))
    return csvs[0] if csvs else None


def _load_thresholds() -> dict[str, float]:
    p = Path(__file__).parent.parent / "data" / "thresholds.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text())
        return {k: float(v) for k, v in data.items() if not k.startswith("_") and v is not None}
    except Exception:
        return {}


_THRESHOLDS: dict[str, float] = _load_thresholds()


def _qid(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _lower_map(cols: list[str]) -> dict[str, str]:
    return {c.lower(): c for c in cols}


def _pick(cols: set[str], aliases: list[str]) -> str | None:
    lm = _lower_map(list(cols))
    for a in aliases:
        if a.lower() in lm:
            return lm[a.lower()]
    return None


def _valid_election_key(s: str) -> bool:
    return bool(re.fullmatch(r"\d+\|\d{4}\|\d{2}\|\d{2}", s))


def _clea_schema_ok(con: duckdb.DuckDBPyConnection) -> bool:
    try:
        info = con.execute("PRAGMA table_info('clea_elections')").fetchall()
        names = {str(r[1]) for r in info}
        return {"threshold_column", "pr_tier_mode", "aggregation_note"}.issubset(names) and \
               {"seats_pr_tier", "seats_constituency_tier"}.issubset(names)
    except Exception:
        return False


def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    r = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?",
        [name],
    ).fetchone()
    return r is not None and int(r[0]) > 0


def _has_view(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    r = con.execute(
        "SELECT COUNT(*) FROM duckdb_views() WHERE view_name = ?",
        [name],
    ).fetchone()
    return r is not None and int(r[0]) > 0


class ReferenceStore:
    """Единый store: ParlGov + CLEA → один файл reference.duckdb."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._con: duckdb.DuckDBPyConnection | None = None
        self._error: str | None = None

    def _db_path(self) -> Path:
        return _data_dir() / "reference.duckdb"

    def _close_conn(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None

    def reset_connection(self) -> None:
        with self._lock:
            self._close_conn()

    # ------------------------------------------------------------------
    # ParlGov ingest
    # ------------------------------------------------------------------

    def _remote_newer_than_local(self, client: httpx.Client, url: str, local: Path) -> bool:
        if not local.is_file():
            return True
        try:
            r = client.head(url, follow_redirects=True, timeout=60.0)
            r.raise_for_status()
        except Exception:
            return True
        lm = r.headers.get("last-modified")
        if not lm:
            return False
        try:
            remote_ts = parsedate_to_datetime(lm).timestamp()
        except (TypeError, ValueError, OSError):
            return True
        return remote_ts > local.stat().st_mtime + 2.0

    def _download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in resp.iter_bytes(1024 * 1024):
                        f.write(chunk)
        tmp.replace(dest)
        logger.info("Downloaded %s -> %s", url, dest)

    def _ingest_parlgov(
        self, con: duckdb.DuckDBPyConnection, ve_path: Path, el_path: Path
    ) -> None:
        con.execute(
            "CREATE OR REPLACE TABLE view_election AS "
            "SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)",
            [str(ve_path)],
        )
        con.execute(
            "CREATE OR REPLACE TABLE election_meta AS "
            "SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)",
            [str(el_path)],
        )
        con.execute(
            """
            CREATE OR REPLACE VIEW parliament_elections AS
            SELECT
              CAST(election_id AS BIGINT) AS election_id,
              TRY_CAST(election_date AS DATE) AS election_date,
              CAST(country_id AS BIGINT) AS country_id,
              country_name_short,
              country_name,
              CAST(seats_total AS INTEGER) AS seats_total,
              party_id,
              party_name_short,
              party_name,
              NULLIF(TRIM(party_name_english), '') AS party_name_english,
              TRY_CAST(vote_share AS DOUBLE) AS vote_share,
              TRY_CAST(seats AS INTEGER) AS seats
            FROM view_election
            WHERE lower(trim(election_type)) = 'parliament'
              AND election_id IS NOT NULL AND trim(election_id) <> ''
              AND TRY_CAST(vote_share AS DOUBLE) IS NOT NULL
            """
        )
        logger.info("ParlGov: materialized parliament_elections view")

    # ------------------------------------------------------------------
    # CLEA ingest
    # ------------------------------------------------------------------

    def _ingest_clea(self, con: duckdb.DuckDBPyConnection, csv_path: Path, mtime: float) -> None:
        con.execute("DROP TABLE IF EXISTS _clea_raw")
        con.execute(
            "CREATE TABLE _clea_raw AS "
            "SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE, HEADER=TRUE)",
            [str(csv_path)],
        )
        info = con.execute("PRAGMA table_info('_clea_raw')").fetchall()
        cols = {str(r[1]) for r in info}

        c_ctr = _pick(cols, _CLEA_ALIASES["ctr"])
        c_yr = _pick(cols, _CLEA_ALIASES["yr"])
        c_pv1 = _pick(cols, _CLEA_ALIASES["pv1"])
        c_vv1 = _pick(cols, _CLEA_ALIASES["vv1"])
        if not c_ctr or not c_yr or not c_pv1 or not c_vv1:
            raise RuntimeError(
                "CLEA: в CSV не найдены обязательные колонки (ctr, yr, pv1, vv1 или алиасы)."
            )
        c_mn = _pick(cols, _CLEA_ALIASES["mn"])
        c_dy = _pick(cols, _CLEA_ALIASES["dy"])
        c_cst = _pick(cols, _CLEA_ALIASES["cst"])
        c_pty_n = _pick(cols, _CLEA_ALIASES["pty_n"])
        c_pty = _pick(cols, _CLEA_ALIASES["pty"])
        c_seat = _pick(cols, _CLEA_ALIASES["seat"])
        c_ctr_n = _pick(cols, _CLEA_ALIASES["ctr_n"])
        c_mag = _pick(cols, _CLEA_ALIASES["mag"])

        thr_env = os.getenv("CLEA_THRESHOLD_COL", "").strip()
        if thr_env:
            lmthr = _lower_map(list(cols))
            c_thr = lmthr.get(thr_env.lower())
            if c_thr is None:
                logger.warning("CLEA_THRESHOLD_COL=%s не найден — порог не подставляется.", thr_env)
        else:
            c_thr = _pick(cols, _CLEA_ALIASES["thr"])

        pr_only = os.getenv("CLEA_PR_ONLY", "1").strip().lower() not in ("0", "false", "no")

        if not c_cst:
            raise RuntimeError("CLEA: не найдена колонка округа (cst / constituency / district).")

        if c_pty_n and c_pty:
            party_expr = (
                f"CASE WHEN NULLIF(TRIM(COALESCE({_qid(c_pty_n)}, '')), '') IS NOT NULL "
                f"THEN TRIM(COALESCE({_qid(c_pty_n)}, '')) "
                f"ELSE CONCAT('party ', TRIM(CAST({_qid(c_pty)} AS VARCHAR))) END"
            )
        elif c_pty_n:
            party_expr = f"TRIM(COALESCE({_qid(c_pty_n)}, ''))"
        elif c_pty:
            party_expr = f"CONCAT('party ', TRIM(CAST({_qid(c_pty)} AS VARCHAR)))"
        else:
            raise RuntimeError("CLEA: нужна колонка названия партии (pty_n) или кода (pty).")

        mn_sql = f"COALESCE(TRY_CAST({_qid(c_mn)} AS INTEGER), 1)" if c_mn else "CAST(1 AS INTEGER)"
        dy_sql = f"COALESCE(TRY_CAST({_qid(c_dy)} AS INTEGER), 1)" if c_dy else "CAST(1 AS INTEGER)"
        vv_sql = f"TRY_CAST({_qid(c_vv1)} AS DOUBLE)" if c_vv1 else "CAST(NULL AS DOUBLE)"
        seat_sql = f"TRY_CAST({_qid(c_seat)} AS INTEGER)" if c_seat else "CAST(NULL AS INTEGER)"
        thr_sql = f"TRY_CAST({_qid(c_thr)} AS DOUBLE)" if c_thr else "CAST(NULL AS DOUBLE)"
        mag_sql = f"TRY_CAST({_qid(c_mag)} AS INTEGER)" if c_mag else "CAST(NULL AS INTEGER)"
        pr_only_active = bool(pr_only and c_mag)
        mag_filter_sql = " AND (z.mag IS NOT NULL AND z.mag > 1)" if pr_only_active else ""
        ctr_n_src_col = (
            f", TRIM(CAST({_qid(c_ctr_n)} AS VARCHAR)) AS ctr_n_src" if c_ctr_n else ""
        )
        ctr_n_sql = "MAX(ctr_n_src)" if c_ctr_n else "CAST(MIN(ctr) AS VARCHAR)"

        con.execute("DROP VIEW IF EXISTS clea_norm")
        con.execute(
            f"""
            CREATE VIEW clea_norm AS
            SELECT * FROM (
              SELECT
                TRY_CAST({_qid(c_ctr)} AS INTEGER) AS ctr,
                TRY_CAST({_qid(c_yr)} AS INTEGER) AS yr,
                {mn_sql} AS mn,
                {dy_sql} AS dy,
                TRIM(CAST({_qid(c_cst)} AS VARCHAR)) AS cst,
                CAST({party_expr} AS VARCHAR) AS pty_n,
                TRY_CAST({_qid(c_pv1)} AS DOUBLE) AS pv1,
                {vv_sql} AS vv1,
                {seat_sql} AS seat,
                {thr_sql} AS thr_val,
                {mag_sql} AS mag
                {ctr_n_src_col}
              FROM _clea_raw
              WHERE TRY_CAST({_qid(c_ctr)} AS INTEGER) IS NOT NULL
                AND TRY_CAST({_qid(c_yr)} AS INTEGER) IS NOT NULL
                AND TRIM(CAST({_qid(c_cst)} AS VARCHAR)) <> ''
                AND TRY_CAST({_qid(c_pv1)} AS DOUBLE) IS NOT NULL
                AND TRY_CAST({_qid(c_pv1)} AS DOUBLE) >= 0
            ) z
            WHERE 1=1{mag_filter_sql}
            """
        )

        con.execute("DROP TABLE IF EXISTS clea_party_national")
        con.execute("DROP TABLE IF EXISTS clea_elections")
        con.execute("DROP TABLE IF EXISTS clea_build_meta")

        thr_col_lit = (c_thr or "").replace("'", "''")
        mag_col_lit = (c_mag or "").replace("'", "''")
        if pr_only_active:
            pr_mode_lit = f"mag>1 only ({mag_col_lit})"
        elif not c_mag:
            pr_mode_lit = "all rows (no MAG column)"
        else:
            pr_mode_lit = "all rows (CLEA_PR_ONLY=0)"
        agg_note_lit = (
            (
                "Votes and seats summed only over constituencies with MAG>1 "
                "(multi-member / PR tier). Single-member rows excluded."
            )
            if pr_only_active
            else (
                "No MAG column in CSV: sums include all constituency rows "
                "(SMD and PR mixed if present)."
                if not c_mag
                else "MAG present but CLEA_PR_ONLY=0: all rows included."
            )
        ).replace("'", "''")
        thr_note_lit = (
            (
                f"Threshold value from CSV column {thr_col_lit!s}: verify against "
                "your CLEA codebook — not always the legal PR threshold."
            )
            if c_thr
            else "No threshold column detected; set CLEA_THRESHOLD_COL if needed."
        ).replace("'", "''")

        if c_mag:
            seats_tier_cte = """
            ,
            seats_tier AS (
              SELECT ctr, yr, mn, dy,
                CAST(SUM(CASE WHEN mag IS NOT NULL AND mag > 1 THEN COALESCE(seat, 0) ELSE 0 END) AS BIGINT) AS seats_pr_tier,
                CAST(SUM(CASE WHEN mag IS NULL OR mag <= 1 THEN COALESCE(seat, 0) ELSE 0 END) AS BIGINT) AS seats_constituency_tier
              FROM clea_norm
              GROUP BY 1, 2, 3, 4
            )"""
            seats_tier_join = """
            LEFT JOIN seats_tier st
              ON st.ctr = n.ctr AND st.yr = n.yr AND st.mn = n.mn AND st.dy = n.dy"""
            seats_tier_cols = """
              CAST(st.seats_pr_tier AS INTEGER) AS seats_pr_tier,
              CAST(st.seats_constituency_tier AS INTEGER) AS seats_constituency_tier,"""
        else:
            seats_tier_cte = ""
            seats_tier_join = ""
            seats_tier_cols = """
              CAST(NULL AS INTEGER) AS seats_pr_tier,
              CAST(NULL AS INTEGER) AS seats_constituency_tier,"""

        con.execute(
            f"""
            CREATE TABLE clea_elections AS
            WITH const_vv AS (
              SELECT ctr, yr, mn, dy, cst, MAX(vv1) AS vv_cst
              FROM clea_norm WHERE vv1 IS NOT NULL AND vv1 >= 0
              GROUP BY 1, 2, 3, 4, 5
            ),
            nat_valid AS (
              SELECT ctr, yr, mn, dy, SUM(vv_cst) AS votes_valid
              FROM const_vv GROUP BY 1, 2, 3, 4
            ),
            thr_elec AS (
              SELECT ctr, yr, mn, dy,
                CASE
                  WHEN MAX(thr_val) IS NULL THEN NULL
                  WHEN MAX(thr_val) > 1.0 THEN ROUND(MAX(thr_val), 4)
                  ELSE ROUND(100.0 * MAX(thr_val), 4)
                END AS threshold_percent
              FROM clea_norm GROUP BY 1, 2, 3, 4
            ),
            party_agg AS (
              SELECT ctr, yr, mn, dy, pty_n,
                     SUM(pv1) AS votes_party, SUM(COALESCE(seat, 0)) AS seats_party
              FROM clea_norm GROUP BY 1, 2, 3, 4, 5
            ),
            lab AS (
              SELECT ctr, yr, mn, dy, """
            + ctr_n_sql
            + f""" AS country_label
              FROM clea_norm GROUP BY 1, 2, 3, 4
            ),
            seats_tot AS (
              SELECT ctr, yr, mn, dy, SUM(seats_party) AS seats_total
              FROM party_agg GROUP BY 1, 2, 3, 4
            )"""
            + seats_tier_cte
            + """
            SELECT
              printf('%s|%s|%s|%s',
                CAST(n.ctr AS VARCHAR), CAST(n.yr AS VARCHAR),
                LPAD(CAST(n.mn AS VARCHAR), 2, '0'),
                LPAD(CAST(n.dy AS VARCHAR), 2, '0')
              ) AS election_key,
              n.ctr, n.yr, n.mn, n.dy,
              MAKE_DATE(n.yr, n.mn, n.dy) AS election_date,
              l.country_label,
              n.votes_valid,
              s.seats_total,
              """
            + seats_tier_cols
            + f"""
              t.threshold_percent,
              CAST('{thr_col_lit}' AS VARCHAR) AS threshold_column,
              CAST('{pr_mode_lit}' AS VARCHAR) AS pr_tier_mode,
              CAST('{agg_note_lit}' AS VARCHAR) AS aggregation_note,
              CAST('{thr_note_lit}' AS VARCHAR) AS threshold_note
            FROM nat_valid n
            JOIN seats_tot s ON s.ctr = n.ctr AND s.yr = n.yr AND s.mn = n.mn AND s.dy = n.dy
            """
            + seats_tier_join
            + """
            LEFT JOIN thr_elec t ON t.ctr = n.ctr AND t.yr = n.yr AND t.mn = n.mn AND t.dy = n.dy
            LEFT JOIN lab l ON l.ctr = n.ctr AND l.yr = n.yr AND l.mn = n.mn AND l.dy = n.dy
            """
        )

        con.execute(
            """
            CREATE TABLE clea_party_national AS
            WITH const_vv AS (
              SELECT ctr, yr, mn, dy, cst, MAX(vv1) AS vv_cst
              FROM clea_norm WHERE vv1 IS NOT NULL AND vv1 >= 0
              GROUP BY 1, 2, 3, 4, 5
            ),
            nat_valid AS (
              SELECT ctr, yr, mn, dy, SUM(vv_cst) AS votes_valid
              FROM const_vv GROUP BY 1, 2, 3, 4
            ),
            thr_elec AS (
              SELECT ctr, yr, mn, dy,
                CASE
                  WHEN MAX(thr_val) IS NULL THEN NULL
                  WHEN MAX(thr_val) > 1.0 THEN ROUND(MAX(thr_val), 4)
                  ELSE ROUND(100.0 * MAX(thr_val), 4)
                END AS threshold_percent
              FROM clea_norm GROUP BY 1, 2, 3, 4
            ),
            party_agg AS (
              SELECT ctr, yr, mn, dy, pty_n,
                     SUM(pv1) AS votes_party, SUM(COALESCE(seat, 0)) AS seats_party
              FROM clea_norm GROUP BY 1, 2, 3, 4, 5
            ),
            joined AS (
              SELECT
                p.ctr, p.yr, p.mn, p.dy, p.pty_n,
                p.votes_party, p.seats_party, n.votes_valid, t.threshold_percent,
                CASE WHEN n.votes_valid > 0
                  THEN ROUND(CAST(100.0 * p.votes_party / n.votes_valid AS DOUBLE), 6)
                  ELSE NULL
                END AS vote_share_pct
              FROM party_agg p
              JOIN nat_valid n ON n.ctr = p.ctr AND n.yr = p.yr AND n.mn = p.mn AND n.dy = p.dy
              LEFT JOIN thr_elec t ON t.ctr = p.ctr AND t.yr = p.yr AND t.mn = p.mn AND t.dy = p.dy
            )
            SELECT
              printf('%s|%s|%s|%s',
                CAST(j.ctr AS VARCHAR), CAST(j.yr AS VARCHAR),
                LPAD(CAST(j.mn AS VARCHAR), 2, '0'),
                LPAD(CAST(j.dy AS VARCHAR), 2, '0')
              ) AS election_key,
              j.pty_n AS party_name,
              j.vote_share_pct AS vote_share,
              CAST(ROUND(j.votes_party) AS BIGINT) AS votes_estimated,
              CAST(j.seats_party AS INTEGER) AS seats_recorded,
              CAST(NULL AS INTEGER) AS seats_parlgov
            FROM joined j
            WHERE j.pty_n IS NOT NULL AND TRIM(j.pty_n) <> ''
            ORDER BY election_key, vote_share DESC NULLS LAST
            """
        )

        con.execute(
            """
            CREATE TABLE clea_build_meta (
              build_id VARCHAR PRIMARY KEY,
              source_csv VARCHAR,
              source_mtime DOUBLE,
              built_at TIMESTAMP DEFAULT current_timestamp,
              pr_multi_mag_filter BOOLEAN,
              mag_col VARCHAR,
              thr_col VARCHAR,
              doc_note VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO clea_build_meta
              (build_id, source_csv, source_mtime, pr_multi_mag_filter, mag_col, thr_col, doc_note)
            VALUES ('clea_v1', ?, ?, ?, ?, ?, ?)
            """,
            [
                str(csv_path),
                float(mtime),
                pr_only_active,
                c_mag or "",
                c_thr or "",
                (agg_note_lit + " " + thr_note_lit)[:900],
            ],
        )
        logger.info("CLEA: ingested from %s", csv_path)

    # ------------------------------------------------------------------
    # ref_party_election rebuild (inline, no ATTACH)
    # ------------------------------------------------------------------

    def _rebuild_ref(self, con: duckdb.DuckDBPyConnection) -> None:
        parts: list[str] = []

        if _has_view(con, "parliament_elections"):
            parts.append(
                """
                SELECT
                  ('parlgov|' || CAST(pe.election_id AS VARCHAR)) AS election_key,
                  pe.election_date AS election_date,
                  TRIM(COALESCE(pe.country_name, pe.country_name_short, '')) AS election_label,
                  TRIM(COALESCE(
                    NULLIF(TRIM(pe.party_name_english), ''),
                    pe.party_name, pe.party_name_short, ''
                  )) AS party_name,
                  CASE
                    WHEN TRY_CAST(em.votes_valid AS DOUBLE) IS NOT NULL
                         AND pe.vote_share IS NOT NULL
                      THEN CAST(ROUND(TRY_CAST(em.votes_valid AS DOUBLE) * pe.vote_share / 100.0) AS BIGINT)
                    ELSE CAST(NULL AS BIGINT)
                  END AS votes_absolute,
                  pe.vote_share AS vote_share_pct,
                  pe.seats AS seats,
                  CAST('parlgov' AS VARCHAR) AS source,
                  CAST(NULL AS DOUBLE) AS threshold_pct,
                  pe.seats_total AS seats_total,
                  pe.country_name_short AS country_code
                FROM parliament_elections pe
                LEFT JOIN election_meta em ON CAST(em.id AS BIGINT) = pe.election_id
                """
            )

        if _has_table(con, "clea_party_national") and _has_table(con, "clea_elections"):
            parts.append(
                """
                SELECT
                  pn.election_key AS election_key,
                  e.election_date AS election_date,
                  TRIM(COALESCE(e.country_label, '')) AS election_label,
                  TRIM(COALESCE(pn.party_name, '')) AS party_name,
                  pn.votes_estimated AS votes_absolute,
                  pn.vote_share AS vote_share_pct,
                  pn.seats_recorded AS seats,
                  CAST('clea' AS VARCHAR) AS source,
                  e.threshold_percent AS threshold_pct,
                  CAST(e.seats_total AS INTEGER) AS seats_total,
                  CAST(NULL AS VARCHAR) AS country_code
                FROM clea_party_national pn
                INNER JOIN clea_elections e ON e.election_key = pn.election_key
                WHERE pn.party_name IS NOT NULL AND TRIM(pn.party_name) <> ''
                """
            )

        if not parts:
            con.execute(
                """
                CREATE OR REPLACE TABLE ref_party_election (
                  election_key VARCHAR, election_date DATE, election_label VARCHAR,
                  party_name VARCHAR, votes_absolute BIGINT, vote_share_pct DOUBLE,
                  seats INTEGER, source VARCHAR, threshold_pct DOUBLE,
                  seats_total INTEGER, country_code VARCHAR
                )
                """
            )
            logger.info("ref_party_election: empty (no sources available)")
            return

        union_sql = " UNION ALL ".join(parts)
        con.execute(
            f"CREATE OR REPLACE TABLE ref_party_election AS SELECT * FROM ({union_sql}) u"
        )
        n = con.execute("SELECT COUNT(*) FROM ref_party_election").fetchone()[0]
        logger.info("ref_party_election rebuilt: %s rows", int(n))

    # ------------------------------------------------------------------
    # Init / refresh
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is not None:
                return self._con
            if self._error is not None:
                raise RuntimeError(self._error)

            ddir = _data_dir()
            ddir.mkdir(parents=True, exist_ok=True)
            db_path = self._db_path()
            wal_path = db_path.with_suffix(db_path.suffix + ".wal")
            ve_path = ddir / "view_election.csv"
            el_path = ddir / "election.csv"

            try:
                if wal_path.exists():
                    logger.warning(
                        "Stale WAL detected (%s bytes) — removing DB+WAL to rebuild",
                        wal_path.stat().st_size,
                    )
                    wal_path.unlink(missing_ok=True)
                    db_path.unlink(missing_ok=True)

                if not ve_path.is_file() or not el_path.is_file():
                    logger.info("ParlGov: downloading CSVs (first run)")
                    self._download(VIEW_ELECTION_CSV, ve_path)
                    self._download(ELECTION_CSV, el_path)

                con = duckdb.connect(str(db_path))

                if not _has_view(con, "parliament_elections"):
                    self._ingest_parlgov(con, ve_path, el_path)

                csv_path = _clea_csv_path()
                if csv_path is not None and csv_path.is_file():
                    mtime = csv_path.stat().st_mtime
                    need_clea = True
                    if _has_table(con, "clea_build_meta") and _clea_schema_ok(con):
                        row = None
                        try:
                            row = con.execute(
                                "SELECT source_mtime FROM clea_build_meta WHERE build_id = 'clea_v1'"
                            ).fetchone()
                        except Exception:
                            pass
                        if row and row[0] is not None and float(row[0]) >= mtime - 1e-9:
                            need_clea = False
                    if need_clea:
                        self._ingest_clea(con, csv_path, mtime)

                if not _has_table(con, "ref_party_election"):
                    self._rebuild_ref(con)
                else:
                    needed = {"seats_total", "country_code"}
                    existing = {
                        row[0]
                        for row in con.execute(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'main' AND table_name = 'ref_party_election'"
                        ).fetchall()
                    }
                    if not needed.issubset(existing):
                        self._rebuild_ref(con)

                self._con = con
                logger.info("ReferenceStore ready at %s", db_path)
                return con
            except Exception as e:
                self._error = str(e)
                logger.exception("ReferenceStore init failed")
                raise RuntimeError(self._error) from e

    def refresh(self, *, force: bool = False) -> dict[str, object]:
        with self._lock:
            self._close_conn()
            self._error = None
            ddir = _data_dir()
            ddir.mkdir(parents=True, exist_ok=True)
            db_path = self._db_path()
            ve_path = ddir / "view_election.csv"
            el_path = ddir / "election.csv"

            try:
                need_parlgov = force
                if not need_parlgov:
                    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                        need_parlgov = (
                            self._remote_newer_than_local(client, VIEW_ELECTION_CSV, ve_path)
                            or self._remote_newer_than_local(client, ELECTION_CSV, el_path)
                        )
                if need_parlgov:
                    logger.info("ParlGov: downloading CSVs (refresh)")
                    self._download(VIEW_ELECTION_CSV, ve_path)
                    self._download(ELECTION_CSV, el_path)

                csv_path = _clea_csv_path()
                clea_result: dict[str, object]
                need_clea = False
                if csv_path is not None and csv_path.is_file():
                    mtime = csv_path.stat().st_mtime
                    need_clea = force
                    if not need_clea:
                        con_check = duckdb.connect(str(db_path))
                        row = None
                        try:
                            row = con_check.execute(
                                "SELECT source_mtime FROM clea_build_meta WHERE build_id = 'clea_v1'"
                            ).fetchone()
                        except Exception:
                            pass
                        finally:
                            con_check.close()
                        if not row or row[0] is None or float(row[0]) < mtime - 1e-9:
                            need_clea = True
                        elif not _clea_schema_ok(
                            con_tmp := duckdb.connect(str(db_path))
                        ):
                            con_tmp.close()
                            need_clea = True
                        else:
                            con_tmp.close()
                    clea_result = {"enabled": True, "updated": need_clea}
                else:
                    clea_result = {"enabled": False, "skipped": True, "reason": "no_csv"}

                if db_path.exists() and (need_parlgov or need_clea):
                    db_path.unlink()

                con = duckdb.connect(str(db_path))
                self._ingest_parlgov(con, ve_path, el_path)
                if csv_path is not None and csv_path.is_file():
                    self._ingest_clea(con, csv_path, csv_path.stat().st_mtime)
                self._rebuild_ref(con)
                self._con = con

                return {
                    "parlgov": {
                        "updated": need_parlgov,
                        "skipped": not need_parlgov,
                        "message": "CSV загружены, DuckDB пересобран." if need_parlgov
                                   else "Локальные CSV не новее сервера.",
                    },
                    "clea": clea_result,
                }
            except Exception as e:
                logger.exception("ReferenceStore refresh failed")
                self._error = None
                return {"parlgov": {"updated": False, "error": str(e)}, "clea": {}}

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, object]:
        try:
            with self._lock:
                con = self._ensure_loaded()
                n_e = con.execute(
                    "SELECT COUNT(DISTINCT election_id) FROM parliament_elections"
                ).fetchone()[0]
                n_p = con.execute(
                    "SELECT COUNT(*) FROM parliament_elections"
                ).fetchone()[0]
                ref_n = 0
                try:
                    if _has_table(con, "ref_party_election"):
                        ref_n = int(con.execute("SELECT COUNT(*) FROM ref_party_election").fetchone()[0])
                except Exception:
                    pass
                parlgov_status: dict[str, object] = {
                    "loaded": True,
                    "elections_distinct": int(n_e),
                    "party_result_rows": int(n_p),
                    "duckdb_path": str(self._db_path()),
                    "ref_party_election_rows": ref_n,
                    "source": "ParlGov development CSV (parlgov.org)",
                }
                clea_status: dict[str, object]
                csv_path = _clea_csv_path()
                if csv_path is None or not csv_path.is_file():
                    clea_status = {"enabled": False, "reason": "no_csv"}
                elif not _has_table(con, "clea_elections"):
                    clea_status = {"enabled": False, "reason": "not_ingested"}
                else:
                    n_clea = int(con.execute("SELECT COUNT(*) FROM clea_elections").fetchone()[0])
                    meta: dict[str, object] = {}
                    try:
                        mr = con.execute(
                            "SELECT pr_multi_mag_filter, mag_col, thr_col, doc_note "
                            "FROM clea_build_meta WHERE build_id = 'clea_v1'"
                        ).fetchone()
                        if mr:
                            meta = {
                                "pr_multi_mag_filter": bool(mr[0]),
                                "mag_column": mr[1],
                                "threshold_column": mr[2],
                                "doc_note": mr[3],
                            }
                    except Exception:
                        pass
                    clea_status = {
                        "enabled": True,
                        "elections": n_clea,
                        "csv_path": str(csv_path),
                        "duckdb_path": str(self._db_path()),
                        "source": "CLEA (constituency CSV → DuckDB aggregation)",
                        "build": meta,
                    }
                return {"parlgov": parlgov_status, "clea": clea_status}
        except RuntimeError as e:
            return {"parlgov": {"loaded": False, "error": str(e)}, "clea": {}}

    def duckdb_file_path(self) -> Path:
        return self._db_path()

    # ------------------------------------------------------------------
    # ParlGov queries
    # ------------------------------------------------------------------

    def list_countries(self) -> list[dict[str, object]]:
        with self._lock:
            con = self._ensure_loaded()
            rows = con.execute(
                """
                SELECT country_id, country_name_short, country_name
                FROM (SELECT DISTINCT country_id, country_name_short, country_name
                      FROM parliament_elections) t
                ORDER BY country_name_short
                """
            ).fetchall()
        return [
            {"country_id": int(r[0]), "code": r[1], "name": r[2]}
            for r in rows if r[0] is not None
        ]

    def list_elections(
        self,
        country_id: int | None,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        q: str | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        with self._lock:
            con = self._ensure_loaded()
            conds: list[str] = []
            params: list[object] = []
            if country_id is not None:
                conds.append("country_id = ?")
                params.append(country_id)
            if date_from:
                conds.append("election_date >= CAST(? AS DATE)")
                params.append(date_from)
            if date_to:
                conds.append("election_date <= CAST(? AS DATE)")
                params.append(date_to)
            if q and q.strip():
                like = f"%{q.strip().lower()}%"
                conds.append("(LOWER(country_name) LIKE ? OR LOWER(country_name_short) LIKE ?)")
                params.extend([like, like])
            where_sql = " AND ".join(conds) if conds else "1=1"
            total = con.execute(
                f"SELECT COUNT(*) FROM (SELECT DISTINCT election_id FROM parliament_elections WHERE {where_sql}) s",
                params,
            ).fetchone()[0]
            rows = con.execute(
                f"""
                SELECT election_id, election_date::VARCHAR, country_name_short, country_name,
                       MAX(seats_total) AS seats_total
                FROM parliament_elections WHERE {where_sql}
                GROUP BY 1, 2, 3, 4
                ORDER BY election_date DESC
                LIMIT ? OFFSET ?
                """,
                list(params) + [limit, offset],
            ).fetchall()
        return [
            {
                "election_id": int(r[0]),
                "election_date": str(r[1]),
                "country_code": r[2],
                "country_name": r[3],
                "seats_total": int(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ], int(total)

    def list_unified_elections(
        self,
        country_id: int | None,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        q: str | None = None,
        source: str | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        conds: list[str] = ["1=1"]
        params: list[object] = []
        if country_id is not None:
            conds.append("r.source = 'parlgov'")
            conds.append(
                "CAST(SPLIT_PART(r.election_key, '|', 2) AS BIGINT) IN "
                "(SELECT DISTINCT election_id FROM parliament_elections WHERE country_id = ?)"
            )
            params.append(country_id)
        if date_from:
            conds.append("r.election_date >= CAST(? AS DATE)")
            params.append(date_from)
        if date_to:
            conds.append("r.election_date <= CAST(? AS DATE)")
            params.append(date_to)
        if q and q.strip():
            like = f"%{q.strip().lower()}%"
            conds.append("(LOWER(r.election_label) LIKE ? OR LOWER(r.party_name) LIKE ?)")
            params.extend([like, like])
        if source in ("parlgov", "clea"):
            conds.append("r.source = ?")
            params.append(source)
        where_sql = " AND ".join(conds)
        base_sql = f"""
            SELECT
              r.election_key,
              MAX(r.election_date) AS election_date,
              MAX(r.election_label) AS election_label,
              MAX(r.source) AS source,
              MAX(r.threshold_pct) AS threshold_pct,
              COUNT(*)::BIGINT AS n_parties,
              MAX(r.seats_total) AS seats_total_ref,
              MAX(r.country_code) AS country_code
            FROM ref_party_election r
            WHERE {where_sql}
            GROUP BY r.election_key
        """
        with self._lock:
            con = self._ensure_loaded()
            has_clea_e = _has_table(con, "clea_elections")
            total = con.execute(f"SELECT COUNT(*) FROM ({base_sql}) t", params).fetchone()[0]
            if has_clea_e:
                outer = f"""
                SELECT
                  b.election_key,
                  b.election_date::VARCHAR AS election_date,
                  b.election_label, b.source, b.threshold_pct, b.n_parties,
                  ce.votes_valid,
                  COALESCE(ce.seats_total, b.seats_total_ref) AS seats_total,
                  ce.seats_pr_tier, ce.seats_constituency_tier, b.country_code
                FROM ({base_sql}) b
                LEFT JOIN clea_elections ce
                  ON ce.election_key = b.election_key AND b.source = 'clea'
                ORDER BY b.election_date DESC NULLS LAST
                LIMIT ? OFFSET ?
                """
            else:
                outer = f"""
                SELECT
                  b.election_key, b.election_date::VARCHAR AS election_date,
                  b.election_label, b.source, b.threshold_pct, b.n_parties,
                  CAST(NULL AS BIGINT) AS votes_valid,
                  b.seats_total_ref AS seats_total,
                  CAST(NULL AS INTEGER) AS seats_pr_tier,
                  CAST(NULL AS INTEGER) AS seats_constituency_tier,
                  b.country_code
                FROM ({base_sql}) b
                ORDER BY b.election_date DESC NULLS LAST
                LIMIT ? OFFSET ?
                """
            rows = con.execute(outer, list(params) + [limit, offset]).fetchall()

        out: list[dict[str, object]] = []
        for r in rows:
            ek = str(r[0])
            parlgov_id: int | None = None
            if ek.startswith("parlgov|"):
                try:
                    parlgov_id = int(ek.split("|", 1)[1])
                except (IndexError, ValueError):
                    pass
            country_code = str(r[10]) if r[10] is not None else None
            thr = float(r[4]) if r[4] is not None else None
            if thr is None and country_code and country_code in _THRESHOLDS:
                thr = _THRESHOLDS[country_code]
            out.append({
                "election_key": ek,
                "parlgov_election_id": parlgov_id,
                "election_date": str(r[1]) if r[1] else "",
                "election_label": r[2],
                "source": r[3],
                "threshold_percent": thr,
                "n_parties": int(r[5]) if r[5] is not None else 0,
                "votes_valid": int(r[6]) if r[6] is not None else None,
                "seats_total": int(r[7]) if r[7] is not None else None,
                "seats_pr_tier": int(r[8]) if r[8] is not None else None,
                "seats_constituency_tier": int(r[9]) if r[9] is not None else None,
            })
        return out, int(total)

    def election_detail(self, election_id: int) -> dict[str, object] | None:
        with self._lock:
            con = self._ensure_loaded()
            meta = con.execute(
                "SELECT em.id, em.date::VARCHAR, em.seats_total, em.votes_valid "
                "FROM election_meta em WHERE CAST(em.id AS BIGINT) = ?",
                [election_id],
            ).fetchone()
            rows = con.execute(
                """
                SELECT party_name_english, party_name, party_name_short, vote_share, seats
                FROM parliament_elections WHERE election_id = ?
                ORDER BY vote_share DESC NULLS LAST
                """,
                [election_id],
            ).fetchall()
            if not rows:
                return None
            votes_valid = election_date = seats_total = None
            if meta:
                election_date = str(meta[1]) if meta[1] else None
                try:
                    seats_total = int(float(meta[2])) if meta[2] not in (None, "") else None
                except (TypeError, ValueError):
                    pass
                try:
                    votes_valid = int(float(meta[3])) if meta[3] not in (None, "") else None
                except (TypeError, ValueError):
                    pass
            if seats_total is None:
                try:
                    seats_total = int(con.execute(
                        "SELECT MAX(seats_total) FROM parliament_elections WHERE election_id = ?",
                        [election_id],
                    ).fetchone()[0])
                except (TypeError, ValueError):
                    pass
            head = con.execute(
                "SELECT country_name_short, country_name, election_date::VARCHAR "
                "FROM parliament_elections WHERE election_id = ? LIMIT 1",
                [election_id],
            ).fetchone()
        parties: list[dict[str, object]] = []
        for r in rows:
            en, name, short, vs, seats = r
            label = (en or name or short or "?").strip()
            parties.append({
                "name": label,
                "vote_share": float(vs) if vs is not None else None,
                "seats_recorded": int(seats) if seats is not None else None,
                "votes_estimated": int(round(float(vs) / 100.0 * votes_valid))
                if votes_valid and vs is not None else None,
            })
        return {
            "election_id": election_id,
            "election_date": election_date or (str(head[2]) if head else None),
            "country_code": head[0] if head else None,
            "country_name": head[1] if head else None,
            "seats_total": seats_total,
            "votes_valid": votes_valid,
            "seats_pr_tier": None,
            "seats_constituency_tier": None,
            "parties": parties,
        }

    def calculator_prefill(
        self, election_id: int, *, threshold_percent: float = 0.0
    ) -> dict[str, object]:
        detail = self.election_detail(election_id)
        if not detail or not detail.get("parties"):
            raise ValueError("election_not_found")
        seats_total = detail.get("seats_total")
        if not isinstance(seats_total, int) or seats_total < 1:
            raise ValueError("invalid_seats_total")
        raw: list[tuple[str, float, int | None]] = []
        for p in detail["parties"]:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name") or "").strip()
            vs = p.get("vote_share")
            if not name or vs is None:
                continue
            try:
                v = float(vs)
            except (TypeError, ValueError):
                continue
            if v >= 0:
                sr = p.get("seats_recorded")
                raw.append((name, v, int(sr) if sr is not None else None))
        if not raw:
            raise ValueError("no_parties")
        s = sum(v for _, v, _ in raw)
        if s <= 0:
            raise ValueError("no_votes")
        parties_out = [
            {
                "name": n,
                "votePercent": f"{(100.0 * v / s):.8f}".rstrip("0").rstrip("."),
                "seatsRecorded": sr,
            }
            for n, v, sr in raw
        ]
        return {
            "totalMandates": seats_total,
            "thresholdPercent": float(threshold_percent),
            "parties": parties_out,
            "meta": {
                "election_id": election_id,
                "election_date": detail.get("election_date"),
                "country_code": detail.get("country_code"),
                "source": "ParlGov view_election (vote shares renormalized to 100%)",
            },
        }

    # ------------------------------------------------------------------
    # CLEA queries
    # ------------------------------------------------------------------

    def clea_list_elections(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        with self._lock:
            con = self._ensure_loaded()
            if not _has_table(con, "clea_elections"):
                raise RuntimeError("CLEA: нет данных (CSV не задан или не загружен).")
            conds: list[str] = ["1=1"]
            params: list[object] = []
            if date_from:
                conds.append("election_date >= CAST(? AS DATE)")
                params.append(date_from)
            if date_to:
                conds.append("election_date <= CAST(? AS DATE)")
                params.append(date_to)
            if q and q.strip():
                conds.append("LOWER(COALESCE(country_label, '')) LIKE ?")
                params.append(f"%{q.strip().lower()}%")
            where_sql = " AND ".join(conds)
            total = con.execute(
                f"SELECT COUNT(*) FROM clea_elections WHERE {where_sql}", params
            ).fetchone()[0]
            rows = con.execute(
                f"""
                SELECT election_key, election_date::VARCHAR, country_label,
                       votes_valid, seats_total, seats_pr_tier, seats_constituency_tier,
                       threshold_percent
                FROM clea_elections WHERE {where_sql}
                ORDER BY election_date DESC NULLS LAST LIMIT ? OFFSET ?
                """,
                list(params) + [limit, offset],
            ).fetchall()
        return [
            {
                "election_key": str(r[0]),
                "election_date": str(r[1]) if r[1] else "",
                "country_label": r[2],
                "votes_valid": int(r[3]) if r[3] is not None else None,
                "seats_total": int(r[4]) if r[4] is not None else None,
                "seats_pr_tier": int(r[5]) if r[5] is not None else None,
                "seats_constituency_tier": int(r[6]) if r[6] is not None else None,
                "threshold_percent": float(r[7]) if r[7] is not None else None,
            }
            for r in rows
        ], int(total)

    def clea_election_detail(self, election_key: str) -> dict[str, object] | None:
        with self._lock:
            con = self._ensure_loaded()
            if not _has_table(con, "clea_elections"):
                return None
            if not _valid_election_key(election_key):
                return None
            head = con.execute(
                """
                SELECT election_key, election_date::VARCHAR, country_label,
                       votes_valid, seats_total, seats_pr_tier, seats_constituency_tier,
                       threshold_percent, threshold_column, pr_tier_mode,
                       aggregation_note, threshold_note
                FROM clea_elections WHERE election_key = ?
                """,
                [election_key],
            ).fetchone()
            if not head:
                return None
            rows = con.execute(
                """
                SELECT party_name, vote_share, votes_estimated, seats_recorded, seats_parlgov
                FROM clea_party_national WHERE election_key = ?
                ORDER BY vote_share DESC NULLS LAST
                """,
                [election_key],
            ).fetchall()
        return {
            "source": "clea",
            "election_key": head[0],
            "election_id": None,
            "election_date": str(head[1]) if head[1] else None,
            "country_code": None,
            "country_name": head[2],
            "seats_total": int(head[4]) if head[4] is not None else None,
            "votes_valid": int(head[3]) if head[3] is not None else None,
            "seats_pr_tier": int(head[5]) if head[5] is not None else None,
            "seats_constituency_tier": int(head[6]) if head[6] is not None else None,
            "threshold_from_data": float(head[7]) if head[7] is not None else None,
            "threshold_column": head[8],
            "pr_tier_mode": head[9],
            "aggregation_note": head[10],
            "threshold_note": head[11],
            "parties": [
                {
                    "name": str(r[0]),
                    "vote_share": float(r[1]) if r[1] is not None else None,
                    "votes_estimated": int(r[2]) if r[2] is not None else None,
                    "seats_recorded": int(r[3]) if r[3] is not None else None,
                    "seats_parlgov": int(r[4]) if r[4] is not None else None,
                }
                for r in rows
            ],
        }

    def clea_calculator_prefill(
        self, election_key: str, *, threshold_percent: float | None = None
    ) -> dict[str, object]:
        detail = self.clea_election_detail(election_key)
        if not detail or not detail.get("parties"):
            raise ValueError("election_not_found")
        seats_total_raw = detail.get("seats_total")
        seats_pr = detail.get("seats_pr_tier")
        seats_total = (
            seats_pr if isinstance(seats_pr, int) and seats_pr > 0
            else (seats_total_raw if isinstance(seats_total_raw, int) and seats_total_raw >= 1 else 150)
        )
        thr_default = detail.get("threshold_from_data")
        thr = float(threshold_percent) if threshold_percent is not None else (
            float(thr_default) if thr_default is not None else 0.0
        )
        raw: list[tuple[str, float, int | None]] = []
        for p in detail["parties"]:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name") or "").strip()
            vs = p.get("vote_share")
            if not name or vs is None:
                continue
            try:
                v = float(vs)
            except (TypeError, ValueError):
                continue
            if v >= 0:
                sr = p.get("seats_recorded")
                raw.append((name, v, int(sr) if sr is not None else None))
        if not raw:
            raise ValueError("no_parties")
        s = sum(v for _, v, _ in raw)
        if s <= 0:
            raise ValueError("no_votes")
        parties_out = [
            {
                "name": n,
                "votePercent": f"{(100.0 * v / s):.8f}".rstrip("0").rstrip("."),
                "seatsRecorded": sr,
            }
            for n, v, sr in raw
        ]
        return {
            "totalMandates": seats_total,
            "thresholdPercent": thr,
            "parties": parties_out,
            "meta": {
                "seats_total_all_tiers": seats_total_raw if isinstance(seats_total_raw, int) else None,
                "seats_pr_tier": seats_pr if isinstance(seats_pr, int) else None,
                "seats_constituency_tier": detail.get("seats_constituency_tier")
                if isinstance(detail.get("seats_constituency_tier"), int) else None,
                "calculator_mandates_tier": "pr_mag_gt_1"
                if isinstance(seats_pr, int) and seats_pr > 0 else "all_seats",
                "election_key": election_key,
                "election_date": detail.get("election_date"),
                "country_name": detail.get("country_name"),
                "source": "CLEA aggregated (vote shares renormalized to 100%)",
                "threshold_from_data": thr_default,
            },
        }


_store = ReferenceStore()


def get_reference_store() -> ReferenceStore:
    return _store
