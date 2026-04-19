"""Единая таблица ref_party_election в parlgov.duckdb.

CLEA добавляется через DuckDB ATTACH (read-only) из clea_aggregated.duckdb,
поэтому каждый источник держит эксклюзивный write-lock только к своему файлу.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


def _clea_db_path() -> Path | None:
    """Путь к clea_aggregated.duckdb (только для ATTACH в parlgov-соединении)."""
    raw = os.getenv("CLEA_DUCKDB_PATH", "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_file() else None
    clea_dir = os.getenv("CLEA_DATA_DIR", "").strip()
    if clea_dir:
        p = Path(clea_dir) / "clea_aggregated.duckdb"
        return p if p.is_file() else None
    return None


def _has_view(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    r = con.execute(
        """
        SELECT COUNT(*) FROM information_schema.views
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [name],
    ).fetchone()
    return r is not None and int(r[0]) > 0


def rebuild_ref_party_election(con: duckdb.DuckDBPyConnection) -> None:
    """
    Создаёт / перезаписывает ref_party_election в уже открытом соединении parlgov.duckdb.

    ParlGov-данные берутся из view parliament_elections / table election_meta (в con).
    CLEA-данные (если clea_aggregated.duckdb найден) подключаются через ATTACH READ_ONLY;
    после вставки — DETACH. Каждый файл остаётся под эксклюзивным write-lock своего владельца.
    """
    parts: list[str] = []

    if _has_view(con, "parliament_elections"):
        parts.append(
            """
            SELECT
              ('parlgov|' || CAST(pe.election_id AS VARCHAR)) AS election_key,
              pe.election_date AS election_date,
              TRIM(COALESCE(pe.country_name, pe.country_name_short, '')) AS election_label,
              TRIM(
                COALESCE(
                  NULLIF(TRIM(pe.party_name_english), ''),
                  pe.party_name,
                  pe.party_name_short,
                  ''
                )
              ) AS party_name,
              CASE
                WHEN TRY_CAST(em.votes_valid AS DOUBLE) IS NOT NULL
                     AND pe.vote_share IS NOT NULL
                  THEN CAST(
                    ROUND(TRY_CAST(em.votes_valid AS DOUBLE) * pe.vote_share / 100.0)
                    AS BIGINT
                  )
                ELSE CAST(NULL AS BIGINT)
              END AS votes_absolute,
              pe.vote_share AS vote_share_pct,
              pe.seats AS seats,
              CAST('parlgov' AS VARCHAR) AS source,
              CAST(NULL AS DOUBLE) AS threshold_pct,
              pe.seats_total AS seats_total
            FROM parliament_elections pe
            LEFT JOIN election_meta em
              ON CAST(em.id AS BIGINT) = pe.election_id
            """
        )

    clea_path = _clea_db_path()
    clea_attached = False
    if clea_path is not None:
        try:
            con.execute(f"ATTACH '{clea_path}' AS clea_ref (READ_ONLY)")
            clea_attached = True
        except Exception as exc:
            logger.warning("ref_party_election: не удалось ATTACH CLEA (%s): %s", clea_path, exc)

    if clea_attached:
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
              CAST(e.seats_total AS INTEGER) AS seats_total
            FROM clea_ref.clea_party_national pn
            INNER JOIN clea_ref.clea_elections e ON e.election_key = pn.election_key
            WHERE pn.party_name IS NOT NULL AND TRIM(pn.party_name) <> ''
            """
        )

    empty_ddl = """
        CREATE OR REPLACE TABLE ref_party_election (
          election_key VARCHAR,
          election_date DATE,
          election_label VARCHAR,
          party_name VARCHAR,
          votes_absolute BIGINT,
          vote_share_pct DOUBLE,
          seats INTEGER,
          source VARCHAR,
          threshold_pct DOUBLE,
          seats_total INTEGER
        )
    """

    try:
        if not parts:
            con.execute(empty_ddl + " SELECT * FROM (SELECT CAST(NULL AS VARCHAR), CAST(NULL AS DATE), CAST(NULL AS VARCHAR), CAST(NULL AS VARCHAR), CAST(NULL AS BIGINT), CAST(NULL AS DOUBLE), CAST(NULL AS INTEGER), CAST(NULL AS VARCHAR), CAST(NULL AS DOUBLE)) t WHERE FALSE")
            logger.info("ref_party_election: empty (no ParlGov view and no CLEA)")
        else:
            union_sql = " UNION ALL ".join(parts)
            con.execute(
                f"""
                CREATE OR REPLACE TABLE ref_party_election AS
                SELECT * FROM ({union_sql}) u
                """
            )
            n = con.execute("SELECT COUNT(*) FROM ref_party_election").fetchone()[0]
            logger.info("ref_party_election rebuilt: %s rows", int(n))
    finally:
        if clea_attached:
            try:
                con.execute("DETACH clea_ref")
            except Exception:
                pass
