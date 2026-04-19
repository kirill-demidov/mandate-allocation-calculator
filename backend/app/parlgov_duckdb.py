"""Загрузка CSV ParlGov и запросы через DuckDB (ленивая инициализация)."""

from __future__ import annotations

import logging
import os
import threading
from email.utils import parsedate_to_datetime
from pathlib import Path

import duckdb
import httpx

from app.reference_unified import rebuild_ref_party_election

logger = logging.getLogger(__name__)

VIEW_ELECTION_CSV = (
    "https://parlgov.org/data/parlgov-development_csv-utf-8/view_election.csv"
)
ELECTION_CSV = "https://parlgov.org/data/parlgov-development_csv-utf-8/election.csv"

PARL_TYPE_PARLIAMENT = "parliament"


def _data_dir() -> Path:
    raw = os.getenv("PARLGOV_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path(os.getenv("TMPDIR", "/tmp")) / "parlgov"


class ParlGovStore:
    """Один раз скачивает CSV и строит таблицы в файле DuckDB для быстрых повторных стартов."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._con: duckdb.DuckDBPyConnection | None = None
        self._error: str | None = None

    def _close_conn(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except Exception:  # noqa: BLE001
                pass
            self._con = None

    def reset_connection(self) -> None:
        """Закрыть кэш DuckDB (после записи из другого процесса/хранилища в тот же файл)."""
        with self._lock:
            self._close_conn()

    def _materialize_parliament(
        self, con: duckdb.DuckDBPyConnection, ve_path: Path, el_path: Path
    ) -> None:
        con.execute(
            """
            CREATE OR REPLACE TABLE view_election AS
            SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
            """,
            [str(ve_path)],
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE election_meta AS
            SELECT * FROM read_csv_auto(?, ALL_VARCHAR=TRUE)
            """,
            [str(el_path)],
        )
        con.execute(
            f"""
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
            WHERE lower(trim(election_type)) = '{PARL_TYPE_PARLIAMENT}'
              AND election_id IS NOT NULL AND trim(election_id) <> ''
              AND TRY_CAST(vote_share AS DOUBLE) IS NOT NULL
            """
        )
        rebuild_ref_party_election(con)

    @staticmethod
    def _ensure_ref_party_election(con: duckdb.DuckDBPyConnection) -> None:
        r = con.execute(
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = 'ref_party_election'
            """
        ).fetchone()
        if r is None or int(r[0]) == 0:
            rebuild_ref_party_election(con)

    def _remote_newer_than_local(
        self, client: httpx.Client, url: str, local: Path
    ) -> bool:
        """True — стоит скачать заново (локального файла нет или Last-Modified на сервере новее)."""
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
            dt = parsedate_to_datetime(lm)
            remote_ts = dt.timestamp()
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

    def _ensure_loaded(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._con is not None:
                return self._con
            if self._error is not None:
                raise RuntimeError(self._error)
            ddir = _data_dir()
            ddir.mkdir(parents=True, exist_ok=True)
            ve_path = ddir / "view_election.csv"
            el_path = ddir / "election.csv"
            db_path = ddir / "parlgov.duckdb"
            wal_path = ddir / "parlgov.duckdb.wal"
            try:
                if wal_path.exists():
                    logger.warning(
                        "Stale DuckDB WAL detected (%s bytes) — removing DB and WAL to rebuild from CSV",
                        wal_path.stat().st_size,
                    )
                    wal_path.unlink(missing_ok=True)
                    db_path.unlink(missing_ok=True)
                if not ve_path.is_file() or not el_path.is_file():
                    logger.info("ParlGov: downloading CSV (first run may take a few minutes)")
                    self._download(VIEW_ELECTION_CSV, ve_path)
                    self._download(ELECTION_CSV, el_path)
                con = duckdb.connect(str(db_path))
                has = con.execute(
                    "SELECT COUNT(*) FROM duckdb_views() WHERE view_name = 'parliament_elections'"
                ).fetchone()[0]
                if int(has) == 0:
                    self._materialize_parliament(con, ve_path, el_path)
                else:
                    self._ensure_ref_party_election(con)
                self._con = con
                logger.info("ParlGov DuckDB ready at %s", db_path)
                return con
            except Exception as e:  # noqa: BLE001
                self._error = str(e)
                logger.exception("ParlGov init failed")
                raise RuntimeError(self._error) from e

    def refresh(self, *, force: bool = False) -> dict[str, object]:
        """HEAD к parlgov.org; при более новом CSV скачивает и пересобирает DuckDB."""
        with self._lock:
            self._close_conn()
            self._error = None
            ddir = _data_dir()
            ddir.mkdir(parents=True, exist_ok=True)
            ve_path = ddir / "view_election.csv"
            el_path = ddir / "election.csv"
            db_path = ddir / "parlgov.duckdb"
            try:
                need_download = force
                if not need_download:
                    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
                        need_download = self._remote_newer_than_local(
                            client, VIEW_ELECTION_CSV, ve_path
                        ) or self._remote_newer_than_local(client, ELECTION_CSV, el_path)
                if not need_download and ve_path.is_file() and el_path.is_file():
                    con = duckdb.connect(str(db_path))
                    has = con.execute(
                        "SELECT COUNT(*) FROM duckdb_views() WHERE view_name = 'parliament_elections'"
                    ).fetchone()[0]
                    if int(has) == 0:
                        self._materialize_parliament(con, ve_path, el_path)
                    else:
                        self._ensure_ref_party_election(con)
                    self._con = con
                    return {
                        "updated": False,
                        "skipped": True,
                        "message": "Локальные CSV не новее сервера (Last-Modified).",
                    }
                logger.info("ParlGov: downloading CSV (refresh)")
                self._download(VIEW_ELECTION_CSV, ve_path)
                self._download(ELECTION_CSV, el_path)
                con = duckdb.connect(str(db_path))
                self._materialize_parliament(con, ve_path, el_path)
                self._con = con
                return {
                    "updated": True,
                    "skipped": False,
                    "message": "CSV загружены, DuckDB пересобран.",
                }
            except Exception as e:  # noqa: BLE001
                logger.exception("ParlGov refresh failed")
                self._error = None
                return {"updated": False, "skipped": False, "error": str(e)}

    def status(self) -> dict[str, object]:
        try:
            con = self._ensure_loaded()
            n_e = con.execute(
                "SELECT COUNT(DISTINCT election_id) FROM parliament_elections"
            ).fetchone()[0]
            n_p = con.execute(
                "SELECT COUNT(*) FROM parliament_elections"
            ).fetchone()[0]
            db_path = str(_data_dir() / "parlgov.duckdb")
            ref_n = 0
            try:
                r0 = con.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = 'main' AND table_name = 'ref_party_election'
                    """
                ).fetchone()
                if r0 and int(r0[0]) > 0:
                    ref_n = int(
                        con.execute(
                            "SELECT COUNT(*) FROM ref_party_election"
                        ).fetchone()[0]
                    )
            except Exception:  # noqa: BLE001
                pass
            return {
                "loaded": True,
                "elections_distinct": int(n_e),
                "party_result_rows": int(n_p),
                "duckdb_path": db_path,
                "ref_party_election_rows": ref_n,
                "source": "ParlGov development CSV (parlgov.org)",
            }
        except RuntimeError as e:
            return {"loaded": False, "error": str(e)}

    def list_countries(self) -> list[dict[str, object]]:
        con = self._ensure_loaded()
        rows = con.execute(
            """
            SELECT country_id, country_name_short, country_name
            FROM (
              SELECT DISTINCT country_id, country_name_short, country_name
              FROM parliament_elections
            ) t
            ORDER BY country_name_short
            """
        ).fetchall()
        return [
            {"country_id": int(r[0]), "code": r[1], "name": r[2]}
            for r in rows
            if r[0] is not None
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
            conds.append(
                "(LOWER(country_name) LIKE ? OR LOWER(country_name_short) LIKE ?)"
            )
            params.extend([like, like])
        where_sql = " AND ".join(conds) if conds else "1=1"
        total = con.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT DISTINCT election_id FROM parliament_elections
              WHERE {where_sql}
            ) s
            """,
            params,
        ).fetchone()[0]
        params2 = list(params)
        params2.extend([limit, offset])
        rows = con.execute(
            f"""
            SELECT election_id, election_date::VARCHAR AS election_date,
                   country_name_short, country_name,
                   MAX(seats_total) AS seats_total
            FROM parliament_elections
            WHERE {where_sql}
            GROUP BY 1, 2, 3, 4
            ORDER BY election_date DESC
            LIMIT ? OFFSET ?
            """,
            params2,
        ).fetchall()
        out = [
            {
                "election_id": int(r[0]),
                "election_date": str(r[1]),
                "country_code": r[2],
                "country_name": r[3],
                "seats_total": int(r[4]) if r[4] is not None else None,
            }
            for r in rows
        ]
        return out, int(total)

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
        """Список выборов из ref_party_election (ParlGov + CLEA в одной таблице)."""
        con = self._ensure_loaded()
        self._ensure_ref_party_election(con)
        has_clea_e = int(
            con.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'main' AND table_name = 'clea_elections'
                """
            ).fetchone()[0]
        ) > 0
        conds: list[str] = ["1=1"]
        params: list[object] = []
        if country_id is not None:
            conds.append("r.source = 'parlgov'")
            conds.append(
                "CAST(SPLIT_PART(r.election_key, '|', 2) AS BIGINT) IN ("
                "SELECT DISTINCT election_id FROM parliament_elections WHERE country_id = ?)"
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
            conds.append(
                "(LOWER(r.election_label) LIKE ? OR LOWER(r.party_name) LIKE ?)"
            )
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
              COUNT(*)::BIGINT AS n_parties
            FROM ref_party_election r
            WHERE {where_sql}
            GROUP BY r.election_key
        """
        total = con.execute(
            f"SELECT COUNT(*) FROM ({base_sql}) t",
            params,
        ).fetchone()[0]
        if has_clea_e:
            outer = f"""
            SELECT
              b.election_key,
              b.election_date::VARCHAR AS election_date,
              b.election_label,
              b.source,
              b.threshold_pct,
              b.n_parties,
              ce.votes_valid,
              ce.seats_total,
              ce.seats_pr_tier,
              ce.seats_constituency_tier
            FROM ({base_sql}) b
            LEFT JOIN clea_elections ce
              ON ce.election_key = b.election_key AND b.source = 'clea'
            ORDER BY b.election_date DESC NULLS LAST
            LIMIT ? OFFSET ?
            """
        else:
            outer = f"""
            SELECT
              b.election_key,
              b.election_date::VARCHAR AS election_date,
              b.election_label,
              b.source,
              b.threshold_pct,
              b.n_parties,
              CAST(NULL AS BIGINT) AS votes_valid,
              CAST(NULL AS INTEGER) AS seats_total,
              CAST(NULL AS INTEGER) AS seats_pr_tier,
              CAST(NULL AS INTEGER) AS seats_constituency_tier
            FROM ({base_sql}) b
            ORDER BY b.election_date DESC NULLS LAST
            LIMIT ? OFFSET ?
            """
        params2 = list(params)
        params2.extend([limit, offset])
        rows = con.execute(outer, params2).fetchall()
        out: list[dict[str, object]] = []
        for r in rows:
            ek = str(r[0])
            parlgov_id: int | None = None
            if ek.startswith("parlgov|"):
                try:
                    parlgov_id = int(ek.split("|", 1)[1])
                except (IndexError, ValueError):
                    parlgov_id = None
            out.append(
                {
                    "election_key": ek,
                    "parlgov_election_id": parlgov_id,
                    "election_date": str(r[1]) if r[1] else "",
                    "election_label": r[2],
                    "source": r[3],
                    "threshold_percent": float(r[4]) if r[4] is not None else None,
                    "n_parties": int(r[5]) if r[5] is not None else 0,
                    "votes_valid": int(r[6]) if r[6] is not None else None,
                    "seats_total": int(r[7]) if r[7] is not None else None,
                    "seats_pr_tier": int(r[8]) if r[8] is not None else None,
                    "seats_constituency_tier": int(r[9]) if r[9] is not None else None,
                }
            )
        return out, int(total)

    def duckdb_file_path(self) -> Path:
        return _data_dir() / "parlgov.duckdb"

    def election_detail(self, election_id: int) -> dict[str, object] | None:
        con = self._ensure_loaded()
        meta = con.execute(
            """
            SELECT em.id, em.date::VARCHAR, em.seats_total, em.votes_valid
            FROM election_meta em
            WHERE CAST(em.id AS BIGINT) = ?
            """,
            [election_id],
        ).fetchone()
        rows = con.execute(
            """
            SELECT party_name_english, party_name, party_name_short,
                   vote_share, seats
            FROM parliament_elections
            WHERE election_id = ?
            ORDER BY vote_share DESC NULLS LAST
            """,
            [election_id],
        ).fetchall()
        if not rows:
            return None
        votes_valid: int | None = None
        seats_total: int | None = None
        election_date: str | None = None
        if meta:
            election_date = str(meta[1]) if meta[1] else None
            try:
                seats_total = int(float(meta[2])) if meta[2] not in (None, "") else None
            except (TypeError, ValueError):
                seats_total = None
            try:
                votes_valid = int(float(meta[3])) if meta[3] not in (None, "") else None
            except (TypeError, ValueError):
                votes_valid = None
        if seats_total is None:
            try:
                seats_total = int(
                    con.execute(
                        "SELECT MAX(seats_total) FROM parliament_elections WHERE election_id = ?",
                        [election_id],
                    ).fetchone()[0]
                )
            except (TypeError, ValueError):
                seats_total = None
        parties: list[dict[str, object]] = []
        for r in rows:
            en, name, short, vs, seats = r
            label = (en or name or short or "?").strip()
            parties.append(
                {
                    "name": label,
                    "vote_share": float(vs) if vs is not None else None,
                    "seats_recorded": int(seats) if seats is not None else None,
                    "votes_estimated": int(round(float(vs) / 100.0 * votes_valid))
                    if votes_valid and vs is not None
                    else None,
                }
            )
        head = con.execute(
            """
            SELECT country_name_short, country_name, election_date::VARCHAR
            FROM parliament_elections
            WHERE election_id = ?
            LIMIT 1
            """,
            [election_id],
        ).fetchone()
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
        self,
        election_id: int,
        *,
        threshold_percent: float = 0.0,
    ) -> dict[str, object]:
        detail = self.election_detail(election_id)
        if not detail or not detail.get("parties"):
            raise ValueError("election_not_found")
        seats_total = detail.get("seats_total")
        if not isinstance(seats_total, int) or seats_total < 1:
            raise ValueError("invalid_seats_total")
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
            "thresholdPercent": float(threshold_percent),
            "parties": parties_out,
            "meta": {
                "election_id": election_id,
                "election_date": detail.get("election_date"),
                "country_code": detail.get("country_code"),
                "source": "ParlGov view_election (vote shares renormalized to 100%)",
            },
        }


_store = ParlGovStore()


def get_store() -> ParlGovStore:
    return _store
