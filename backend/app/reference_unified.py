"""Единая таблица справочника в том же DuckDB, что и ParlGov (ref_party_election)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


def _has_parliament_elections(con: duckdb.DuckDBPyConnection) -> bool:
    r = con.execute(
        """
        SELECT COUNT(*) FROM information_schema.views
        WHERE table_schema = 'main' AND table_name = 'parliament_elections'
        """
    ).fetchone()
    return r is not None and int(r[0]) > 0


def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    r = con.execute(
        """
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [name],
    ).fetchone()
    return r is not None and int(r[0]) > 0


def rebuild_ref_party_election(con: duckdb.DuckDBPyConnection) -> None:
    """
    Создаёт / перезаписывает ref_party_election: строка = выборы × партия.
    Источники: parlgov (если есть view parliament_elections), clea (если есть clea_party_national).
    """
    parts: list[str] = []
    if _has_parliament_elections(con):
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
                WHEN TRY_CAST(em.votes_valid AS BIGINT) IS NOT NULL
                     AND pe.vote_share IS NOT NULL
                  THEN CAST(
                    ROUND(
                      CAST(TRY_CAST(em.votes_valid AS DOUBLE) AS DOUBLE)
                      * pe.vote_share / 100.0
                    ) AS BIGINT
                  )
                ELSE CAST(NULL AS BIGINT)
              END AS votes_absolute,
              pe.vote_share AS vote_share_pct,
              pe.seats AS seats,
              CAST('parlgov' AS VARCHAR) AS source,
              CAST(NULL AS DOUBLE) AS threshold_pct
            FROM parliament_elections pe
            LEFT JOIN election_meta em
              ON CAST(em.id AS BIGINT) = pe.election_id
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
              e.threshold_percent AS threshold_pct
            FROM clea_party_national pn
            INNER JOIN clea_elections e ON e.election_key = pn.election_key
            WHERE pn.party_name IS NOT NULL AND TRIM(pn.party_name) <> ''
            """
        )
    if not parts:
        con.execute(
            """
            CREATE OR REPLACE TABLE ref_party_election (
              election_key VARCHAR,
              election_date DATE,
              election_label VARCHAR,
              party_name VARCHAR,
              votes_absolute BIGINT,
              vote_share_pct DOUBLE,
              seats INTEGER,
              source VARCHAR,
              threshold_pct DOUBLE
            )
            SELECT
              CAST(NULL AS VARCHAR), CAST(NULL AS DATE), CAST(NULL AS VARCHAR),
              CAST(NULL AS VARCHAR), CAST(NULL AS BIGINT), CAST(NULL AS DOUBLE),
              CAST(NULL AS INTEGER), CAST(NULL AS VARCHAR), CAST(NULL AS DOUBLE)
            WHERE FALSE
            """
        )
        logger.info("ref_party_election: empty (no ParlGov view and no CLEA tables)")
        return

    union_sql = " UNION ALL ".join(parts)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE ref_party_election AS
        SELECT * FROM (
          {union_sql}
        ) u
        """
    )
    n = con.execute("SELECT COUNT(*) FROM ref_party_election").fetchone()[0]
    logger.info("ref_party_election rebuilt: %s rows", int(n))
