"""Загрузка CLEA (окружный CSV), агрегация до национального уровня в DuckDB и запись в .duckdb."""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

_ALIASES: dict[str, list[str]] = {
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
        "tm",
        "tms",
        "th",
        "nthr",
        "nat_thr",
        "natthr",
        "ethresh",
        "ethr",
        "elthr",
        "pr_thr",
        "prthr",
        "thresh",
        "threshold",
        "legal_thr",
        "legal_threshold",
        "elec_thresh",
    ],
    "mag": ["mag", "mag_n", "dm", "dstm", "district_magnitude", "magnitude"],
    "ctr_n": ["ctr_n", "cntry_n", "country_name", "countryname", "cntry"],
}


def _data_dir() -> Path:
    raw = os.getenv("CLEA_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(os.getenv("TMPDIR", "/tmp")) / "clea"


def _csv_path() -> Path | None:
    p = os.getenv("CLEA_CSV_PATH", "").strip()
    if p:
        return Path(p)
    ddir = _data_dir()
    if not ddir.is_dir():
        return None
    for name in ("clea.csv", "clea_constituency.csv", "CLEA.csv"):
        cand = ddir / name
        if cand.is_file():
            return cand
    csvs = sorted(ddir.glob("*.csv"))
    return csvs[0] if csvs else None


def _duckdb_out_path() -> Path:
    raw = os.getenv("CLEA_DUCKDB_PATH", "").strip()
    if raw:
        return Path(raw)
    csv = _csv_path()
    if csv is not None:
        return csv.parent / "clea_aggregated.duckdb"
    return _data_dir() / "clea_aggregated.duckdb"


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
    """Ключ вида ctr|yyyy|mm|dd (как в printf из агрегации)."""
    return bool(re.fullmatch(r"\d+\|\d{4}\|\d{2}\|\d{2}", s))


def _clea_aggregate_schema_ok(con: duckdb.DuckDBPyConnection) -> bool:
    """Совместимость: после смены схемы пересобрать даже при том же mtime CSV."""
    try:
        info = con.execute("PRAGMA table_info('clea_elections')").fetchall()
        names = {str(r[1]) for r in info}
        return {"threshold_column", "pr_tier_mode", "aggregation_note"}.issubset(
            names
        ) and {"seats_pr_tier", "seats_constituency_tier"}.issubset(names)
    except Exception:
        return False


class CleaStore:
    """Читает один CSV CLEA (окружный уровень), строит агрегаты и сохраняет их в DuckDB-файл."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._con: duckdb.DuckDBPyConnection | None = None
        self._error: str | None = None
        self._csv_mtime: float | None = None

    def _close_conn(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:  # noqa: BLE001
                pass
            self._con = None

    def refresh(self, *, force: bool = False) -> dict[str, object]:
        """Пересобрать агрегат из CSV, если файл на диске новее записанного mtime (или force)."""
        with self._lock:
            self._close_conn()
            self._csv_mtime = None
            self._error = None
            csv_path = _csv_path()
            if csv_path is None or not csv_path.is_file():
                return {
                    "enabled": False,
                    "updated": False,
                    "skipped": True,
                    "reason": "no_csv",
                }
            out_path = _duckdb_out_path()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            mtime = csv_path.stat().st_mtime
            try:
                con = duckdb.connect(str(out_path))
                row = None
                try:
                    row = con.execute(
                        """
                        SELECT source_mtime FROM clea_build_meta
                        WHERE build_id = 'clea_v1'
                        """
                    ).fetchone()
                except Exception:
                    row = None
                need = (
                    force
                    or not row
                    or row[0] is None
                    or float(row[0]) < mtime - 1e-9
                    or not _clea_aggregate_schema_ok(con)
                )
                if not need:
                    self._con = con
                    self._csv_mtime = mtime
                    return {
                        "enabled": True,
                        "updated": False,
                        "skipped": True,
                        "message": "CSV CLEA не менялся с прошлой сборки.",
                    }
                self._rebuild(con, csv_path, mtime)
                self._con = con
                self._csv_mtime = mtime
                return {
                    "enabled": True,
                    "updated": True,
                    "skipped": False,
                    "message": "CLEA: DuckDB пересобран из CSV.",
                }
            except Exception as e:  # noqa: BLE001
                logger.exception("CLEA refresh failed")
                self._error = None
                return {
                    "enabled": True,
                    "updated": False,
                    "error": str(e),
                }

    def _ensure_loaded(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            csv_path = _csv_path()
            if csv_path is None or not csv_path.is_file():
                self._error = "clea_csv_missing"
                raise RuntimeError(
                    "CLEA: задайте CLEA_CSV_PATH или положите CSV в CLEA_DATA_DIR "
                    "(см. README раздел CLEA)."
                )
            mtime = csv_path.stat().st_mtime
            out_path = _duckdb_out_path()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if self._con is not None and self._csv_mtime == mtime:
                return self._con
            if self._error == "clea_csv_missing":
                raise RuntimeError(self._error)
            try:
                con = duckdb.connect(str(out_path))
                need_rebuild = True
                row = None
                try:
                    row = con.execute(
                        """
                        SELECT source_mtime FROM clea_build_meta
                        WHERE build_id = 'clea_v1'
                        """
                    ).fetchone()
                except Exception:
                    row = None
                if (
                    row
                    and row[0] is not None
                    and float(row[0]) >= mtime
                    and _clea_aggregate_schema_ok(con)
                ):
                    need_rebuild = False
                if need_rebuild:
                    self._rebuild(con, csv_path, mtime)
                self._con = con
                self._csv_mtime = mtime
                self._error = None
                logger.info("CLEA DuckDB ready at %s", out_path)
                return con
            except Exception as e:  # noqa: BLE001
                self._error = str(e)
                logger.exception("CLEA init failed")
                raise RuntimeError(self._error) from e

    def _rebuild(self, con: duckdb.DuckDBPyConnection, csv_path: Path, mtime: float) -> None:
        con.execute("DROP TABLE IF EXISTS _clea_raw")
        con.execute(
            """
            CREATE TABLE _clea_raw AS
            SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE, HEADER=TRUE)
            """,
            [str(csv_path)],
        )
        info = con.execute("PRAGMA table_info('_clea_raw')").fetchall()
        cols = {str(r[1]) for r in info}
        c_ctr = _pick(cols, _ALIASES["ctr"])
        c_yr = _pick(cols, _ALIASES["yr"])
        c_pv1 = _pick(cols, _ALIASES["pv1"])
        c_vv1 = _pick(cols, _ALIASES["vv1"])
        if not c_ctr or not c_yr or not c_pv1 or not c_vv1:
            raise RuntimeError(
                "CLEA: в CSV не найдены обязательные колонки "
                "(ctr, yr, pv1, vv1 — или алиасы из README)."
            )
        c_mn = _pick(cols, _ALIASES["mn"])
        c_dy = _pick(cols, _ALIASES["dy"])
        c_cst = _pick(cols, _ALIASES["cst"])
        c_pty_n = _pick(cols, _ALIASES["pty_n"])
        c_pty = _pick(cols, _ALIASES["pty"])
        c_seat = _pick(cols, _ALIASES["seat"])
        c_ctr_n = _pick(cols, _ALIASES["ctr_n"])
        c_mag = _pick(cols, _ALIASES["mag"])
        thr_env = os.getenv("CLEA_THRESHOLD_COL", "").strip()
        if thr_env:
            lmthr = _lower_map(list(cols))
            c_thr = lmthr.get(thr_env.lower()) if thr_env.lower() in lmthr else None
            if c_thr is None:
                logger.warning(
                    "CLEA_THRESHOLD_COL=%s не найден среди колонок CSV — порог не подставляется.",
                    thr_env,
                )
        else:
            c_thr = _pick(cols, _ALIASES["thr"])
        pr_only = (
            os.getenv("CLEA_PR_ONLY", "1").strip().lower() not in ("0", "false", "no")
        )

        if not c_cst:
            raise RuntimeError(
                "CLEA: не найдена колонка округа (cst / constituency / district). "
                "Без неё нельзя корректно посчитать национальные действительные голоса."
            )
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
            raise RuntimeError(
                "CLEA: нужна колонка названия партии (pty_n) или кода (pty)."
            )

        mn_sql = f"COALESCE(TRY_CAST({_qid(c_mn)} AS INTEGER), 1)" if c_mn else "CAST(1 AS INTEGER)"
        dy_sql = f"COALESCE(TRY_CAST({_qid(c_dy)} AS INTEGER), 1)" if c_dy else "CAST(1 AS INTEGER)"
        vv_sql = f"TRY_CAST({_qid(c_vv1)} AS DOUBLE)" if c_vv1 else "CAST(NULL AS DOUBLE)"
        seat_sql = f"TRY_CAST({_qid(c_seat)} AS INTEGER)" if c_seat else "CAST(NULL AS INTEGER)"
        thr_sql = f"TRY_CAST({_qid(c_thr)} AS DOUBLE)" if c_thr else "CAST(NULL AS DOUBLE)"
        mag_sql = f"TRY_CAST({_qid(c_mag)} AS INTEGER)" if c_mag else "CAST(NULL AS INTEGER)"
        pr_only_active = bool(pr_only and c_mag)
        mag_filter_sql = ""
        if pr_only_active:
            mag_filter_sql = " AND (z.mag IS NOT NULL AND z.mag > 1)"
        ctr_n_src_col = (
            f", TRIM(CAST({_qid(c_ctr_n)} AS VARCHAR)) AS ctr_n_src"
            if c_ctr_n
            else ""
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
                CAST(
                  SUM(
                    CASE
                      WHEN mag IS NOT NULL AND mag > 1 THEN COALESCE(seat, 0)
                      ELSE 0
                    END
                  ) AS BIGINT
                ) AS seats_pr_tier,
                CAST(
                  SUM(
                    CASE
                      WHEN mag IS NULL OR mag <= 1 THEN COALESCE(seat, 0)
                      ELSE 0
                    END
                  ) AS BIGINT
                ) AS seats_constituency_tier
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
              FROM clea_norm
              WHERE vv1 IS NOT NULL AND vv1 >= 0
              GROUP BY 1, 2, 3, 4, 5
            ),
            nat_valid AS (
              SELECT ctr, yr, mn, dy, SUM(vv_cst) AS votes_valid
              FROM const_vv
              GROUP BY 1, 2, 3, 4
            ),
            thr_elec AS (
              SELECT ctr, yr, mn, dy,
                CASE
                  WHEN MAX(thr_val) IS NULL THEN NULL
                  WHEN MAX(thr_val) > 1.0 THEN ROUND(MAX(thr_val), 4)
                  ELSE ROUND(100.0 * MAX(thr_val), 4)
                END AS threshold_percent
              FROM clea_norm
              GROUP BY 1, 2, 3, 4
            ),
            party_agg AS (
              SELECT ctr, yr, mn, dy, pty_n,
                     SUM(pv1) AS votes_party,
                     SUM(COALESCE(seat, 0)) AS seats_party
              FROM clea_norm
              GROUP BY 1, 2, 3, 4, 5
            ),
            lab AS (
              SELECT ctr, yr, mn, dy, """
            + ctr_n_sql
            + f""" AS country_label
              FROM clea_norm
              GROUP BY 1, 2, 3, 4
            ),
            seats_tot AS (
              SELECT ctr, yr, mn, dy, SUM(seats_party) AS seats_total
              FROM party_agg
              GROUP BY 1, 2, 3, 4
            )"""
            + seats_tier_cte
            + """
            SELECT
              printf('%s|%s|%s|%s',
                CAST(n.ctr AS VARCHAR),
                CAST(n.yr AS VARCHAR),
                LPAD(CAST(n.mn AS VARCHAR), 2, '0'),
                LPAD(CAST(n.dy AS VARCHAR), 2, '0')
              ) AS election_key,
              n.ctr,
              n.yr,
              n.mn,
              n.dy,
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
              FROM clea_norm
              WHERE vv1 IS NOT NULL AND vv1 >= 0
              GROUP BY 1, 2, 3, 4, 5
            ),
            nat_valid AS (
              SELECT ctr, yr, mn, dy, SUM(vv_cst) AS votes_valid
              FROM const_vv
              GROUP BY 1, 2, 3, 4
            ),
            thr_elec AS (
              SELECT ctr, yr, mn, dy,
                CASE
                  WHEN MAX(thr_val) IS NULL THEN NULL
                  WHEN MAX(thr_val) > 1.0 THEN ROUND(MAX(thr_val), 4)
                  ELSE ROUND(100.0 * MAX(thr_val), 4)
                END AS threshold_percent
              FROM clea_norm
              GROUP BY 1, 2, 3, 4
            ),
            party_agg AS (
              SELECT ctr, yr, mn, dy, pty_n,
                     SUM(pv1) AS votes_party,
                     SUM(COALESCE(seat, 0)) AS seats_party
              FROM clea_norm
              GROUP BY 1, 2, 3, 4, 5
            ),
            joined AS (
              SELECT
                p.ctr, p.yr, p.mn, p.dy, p.pty_n,
                p.votes_party,
                p.seats_party,
                n.votes_valid,
                t.threshold_percent,
                CASE WHEN n.votes_valid > 0
                  THEN ROUND(CAST(100.0 * p.votes_party / n.votes_valid AS DOUBLE), 6)
                  ELSE NULL
                END AS vote_share_pct
              FROM party_agg p
              JOIN nat_valid n ON n.ctr = p.ctr AND n.yr = p.yr AND n.mn = p.mn AND n.dy = p.dy
              LEFT JOIN thr_elec t
                ON t.ctr = p.ctr AND t.yr = p.yr AND t.mn = p.mn AND t.dy = p.dy
            )
            SELECT
              printf('%s|%s|%s|%s',
                CAST(j.ctr AS VARCHAR),
                CAST(j.yr AS VARCHAR),
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
            INSERT INTO clea_build_meta (
              build_id, source_csv, source_mtime,
              pr_multi_mag_filter, mag_col, thr_col, doc_note
            )
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

    def status(self) -> dict[str, object]:
        csv_path = _csv_path()
        if csv_path is None or not csv_path.is_file():
            return {
                "enabled": False,
                "reason": "no_csv",
                "hint": "Задайте CLEA_CSV_PATH или положите CSV в CLEA_DATA_DIR.",
            }
        try:
            con = self._ensure_loaded()
            n = con.execute(
                "SELECT COUNT(*) FROM clea_elections"
            ).fetchone()[0]
            meta: dict[str, object] = {}
            try:
                mr = con.execute(
                    """
                    SELECT pr_multi_mag_filter, mag_col, thr_col, doc_note
                    FROM clea_build_meta
                    WHERE build_id = 'clea_v1'
                    """
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
            return {
                "enabled": True,
                "elections": int(n),
                "csv_path": str(csv_path),
                "duckdb_path": str(_duckdb_out_path()),
                "source": "CLEA (constituency CSV → DuckDB aggregation)",
                "build": meta,
            }
        except RuntimeError as e:
            return {"enabled": False, "error": str(e)}

    def duckdb_file_path(self) -> Path:
        return _duckdb_out_path()

    def list_elections(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        con = self._ensure_loaded()
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
            f"SELECT COUNT(*) FROM clea_elections WHERE {where_sql}",
            params,
        ).fetchone()[0]
        params2 = list(params)
        params2.extend([limit, offset])
        rows = con.execute(
            f"""
            SELECT election_key, election_date::VARCHAR, country_label,
                   votes_valid, seats_total, seats_pr_tier, seats_constituency_tier,
                   threshold_percent
            FROM clea_elections
            WHERE {where_sql}
            ORDER BY election_date DESC NULLS LAST
            LIMIT ? OFFSET ?
            """,
            params2,
        ).fetchall()
        out = [
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
        ]
        return out, int(total)

    def election_detail(self, election_key: str) -> dict[str, object] | None:
        con = self._ensure_loaded()
        if not _valid_election_key(election_key):
            return None
        head = con.execute(
            """
            SELECT election_key, election_date::VARCHAR, country_label,
                   votes_valid, seats_total, seats_pr_tier, seats_constituency_tier,
                   threshold_percent,
                   threshold_column, pr_tier_mode, aggregation_note, threshold_note
            FROM clea_elections
            WHERE election_key = ?
            """,
            [election_key],
        ).fetchone()
        if not head:
            return None
        rows = con.execute(
            """
            SELECT party_name, vote_share, votes_estimated, seats_recorded, seats_parlgov
            FROM clea_party_national
            WHERE election_key = ?
            ORDER BY vote_share DESC NULLS LAST
            """,
            [election_key],
        ).fetchall()
        # party_name, vote_share, votes_estimated, seats_recorded, seats_parlgov
        parties_fixed = [
            {
                "name": str(r[0]),
                "vote_share": float(r[1]) if r[1] is not None else None,
                "votes_estimated": int(r[2]) if r[2] is not None else None,
                "seats_recorded": int(r[3]) if r[3] is not None else None,
                "seats_parlgov": int(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ]
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
            "parties": parties_fixed,
        }

    def calculator_prefill(
        self,
        election_key: str,
        *,
        threshold_percent: float | None = None,
    ) -> dict[str, object]:
        detail = self.election_detail(election_key)
        if not detail or not detail.get("parties"):
            raise ValueError("election_not_found")
        seats_total_raw = detail.get("seats_total")
        seats_pr = detail.get("seats_pr_tier")
        if isinstance(seats_pr, int) and seats_pr > 0:
            seats_total = seats_pr
        elif isinstance(seats_total_raw, int) and seats_total_raw >= 1:
            seats_total = seats_total_raw
        else:
            seats_total = 150
        thr_default = detail.get("threshold_from_data")
        if threshold_percent is not None:
            thr = float(threshold_percent)
        elif thr_default is not None:
            thr = float(thr_default)
        else:
            thr = 0.0
        raw: list[tuple[str, float]] = []
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
            if v < 0:
                continue
            raw.append((name, v))
        if not raw:
            raise ValueError("no_parties")
        s = sum(v for _, v in raw)
        if s <= 0:
            raise ValueError("no_votes")
        parties_out = [
            {"name": n, "votePercent": f"{(100.0 * v / s):.8f}".rstrip("0").rstrip(".")}
            for n, v in raw
        ]
        return {
            "totalMandates": seats_total,
            "thresholdPercent": float(thr),
            "parties": parties_out,
            "meta": {
                "seats_total_all_tiers": seats_total_raw
                if isinstance(seats_total_raw, int)
                else None,
                "seats_pr_tier": seats_pr if isinstance(seats_pr, int) else None,
                "seats_constituency_tier": detail.get("seats_constituency_tier")
                if isinstance(detail.get("seats_constituency_tier"), int)
                else None,
                "calculator_mandates_tier": "pr_mag_gt_1"
                if isinstance(seats_pr, int) and seats_pr > 0
                else "all_seats",
                "election_key": election_key,
                "election_date": detail.get("election_date"),
                "country_name": detail.get("country_name"),
                "source": "CLEA aggregated (vote shares renormalized to 100%)",
                "threshold_from_data": thr_default,
            },
        }


_clea_store = CleaStore()


def get_clea_store() -> CleaStore:
    return _clea_store
