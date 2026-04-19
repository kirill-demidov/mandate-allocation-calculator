"""Таблица ref_party_election: ParlGov-view + CLEA через ATTACH (без второго writer на parlgov.duckdb)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import duckdb

from app.reference_unified import rebuild_ref_party_election


class TestReferenceUnified(unittest.TestCase):
    def setUp(self) -> None:
        self._clea_dir = os.environ.pop("CLEA_DATA_DIR", None)
        self._clea_path = os.environ.pop("CLEA_DUCKDB_PATH", None)

    def tearDown(self) -> None:
        if self._clea_dir is not None:
            os.environ["CLEA_DATA_DIR"] = self._clea_dir
        else:
            os.environ.pop("CLEA_DATA_DIR", None)
        if self._clea_path is not None:
            os.environ["CLEA_DUCKDB_PATH"] = self._clea_path
        else:
            os.environ.pop("CLEA_DUCKDB_PATH", None)

    def _write_min_clea_db(self, path: Path) -> None:
        con = duckdb.connect(str(path))
        con.execute(
            """
            CREATE TABLE clea_elections (
              election_key VARCHAR,
              election_date DATE,
              country_label VARCHAR,
              threshold_percent DOUBLE,
              seats_total INTEGER
            )
            """
        )
        con.execute(
            """
            CREATE TABLE clea_party_national (
              election_key VARCHAR,
              party_name VARCHAR,
              votes_estimated BIGINT,
              vote_share DOUBLE,
              seats_recorded INTEGER
            )
            """
        )
        con.execute(
            """
            INSERT INTO clea_elections VALUES
              ('1|2020|01|01', DATE '2020-01-01', 'Testland', 4.0, 20)
            """
        )
        con.execute(
            """
            INSERT INTO clea_party_national VALUES
              ('1|2020|01|01', 'PartyA', 1000, 50.0, 10),
              ('1|2020|01|01', 'PartyB', 1000, 50.0, 10)
            """
        )
        con.close()

    def _parlgov_min_schema(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute(
            """
            CREATE TABLE election_meta (id VARCHAR, votes_valid VARCHAR);
            INSERT INTO election_meta VALUES ('42', '10000');
            """
        )
        con.execute(
            """
            CREATE VIEW parliament_elections AS
            SELECT
              CAST(42 AS BIGINT) AS election_id,
              DATE '2019-06-01' AS election_date,
              CAST(1 AS BIGINT) AS country_id,
              'X' AS country_name_short,
              'Xland' AS country_name,
              CAST(100 AS INTEGER) AS seats_total,
              CAST(1 AS BIGINT) AS party_id,
              'P1' AS party_name_short,
              'Party One' AS party_name,
              CAST(NULL AS VARCHAR) AS party_name_english,
              CAST(50.0 AS DOUBLE) AS vote_share,
              CAST(50 AS INTEGER) AS seats
            UNION ALL
            SELECT
              42, DATE '2019-06-01', 1, 'X', 'Xland', 100, 2, 'P2', 'Party Two',
              NULL, 50.0, 50
            """
        )

    def test_rebuild_parlgov_and_clea_via_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            clea_db = tdir / "clea_aggregated.duckdb"
            self._write_min_clea_db(clea_db)
            os.environ["CLEA_DATA_DIR"] = str(tdir)

            main = duckdb.connect(":memory:")
            self._parlgov_min_schema(main)
            rebuild_ref_party_election(main)

            by_src = dict(
                main.execute(
                    "SELECT source, COUNT(*) FROM ref_party_election GROUP BY source"
                ).fetchall()
            )
            self.assertEqual(by_src.get("parlgov"), 2)
            self.assertEqual(by_src.get("clea"), 2)
            # после rebuild DETACH — алиас clea_ref не должен оставаться
            dbs = [r[1] for r in main.execute("PRAGMA database_list").fetchall()]
            self.assertNotIn("clea_ref", dbs)

    def test_rebuild_parlgov_only_when_no_clea_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["CLEA_DATA_DIR"] = str(Path(tmp))
            main = duckdb.connect(":memory:")
            self._parlgov_min_schema(main)
            rebuild_ref_party_election(main)
            n = main.execute(
                "SELECT COUNT(*) FROM ref_party_election WHERE source = 'parlgov'"
            ).fetchone()[0]
            self.assertEqual(int(n), 2)
            n_clea = main.execute(
                "SELECT COUNT(*) FROM ref_party_election WHERE source = 'clea'"
            ).fetchone()[0]
            self.assertEqual(int(n_clea), 0)

    def test_rebuild_clea_only_without_parl_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            self._write_min_clea_db(tdir / "clea_aggregated.duckdb")
            os.environ["CLEA_DATA_DIR"] = str(tdir)
            main = duckdb.connect(":memory:")
            rebuild_ref_party_election(main)
            self.assertEqual(
                int(
                    main.execute(
                        "SELECT COUNT(*) FROM ref_party_election WHERE source = 'clea'"
                    ).fetchone()[0]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
