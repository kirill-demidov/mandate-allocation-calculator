"""Единый ReferenceStore: ParlGov + CLEA в одном reference.duckdb (без ATTACH)."""

from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from app.reference_store import ReferenceStore, _has_table


def _write_min_parlgov_csvs(ddir: Path) -> None:
    ve_path = ddir / "view_election.csv"
    el_path = ddir / "election.csv"
    with ve_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["election_id", "election_date", "country_id", "country_name_short",
                    "country_name", "seats_total", "party_id", "party_name_short",
                    "party_name", "party_name_english", "vote_share", "seats", "election_type"])
        w.writerow([42, "2019-06-01", 1, "X", "Xland", 100, 1, "P1", "Party One", "", 50.0, 50, "parliament"])
        w.writerow([42, "2019-06-01", 1, "X", "Xland", 100, 2, "P2", "Party Two", "", 50.0, 50, "parliament"])
    with el_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "date", "seats_total", "votes_valid"])
        w.writerow([42, "2019-06-01", 100, 10000])


def _write_min_clea_csv(path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ctr", "yr", "mn", "dy", "cst", "pty_n", "pv1", "vv1", "seat"])
        w.writerow([1, 2020, 1, 1, "D1", "PartyA", 5000, 10000, 10])
        w.writerow([1, 2020, 1, 1, "D1", "PartyB", 5000, 10000, 10])


class TestReferenceStore(unittest.TestCase):

    def _make_store(self, parlgov_dir: str, clea_csv: str | None = None) -> ReferenceStore:
        store = ReferenceStore()
        env = {"PARLGOV_DATA_DIR": parlgov_dir}
        if clea_csv:
            env["CLEA_CSV_PATH"] = clea_csv
        else:
            env.pop("CLEA_CSV_PATH", None)
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("CLEA_DATA_DIR", None)
            if not clea_csv:
                os.environ.pop("CLEA_CSV_PATH", None)
            store._ensure_loaded()
        return store

    def test_parlgov_only_no_clea(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ddir = Path(tmp)
            _write_min_parlgov_csvs(ddir)
            with patch.dict(os.environ, {"PARLGOV_DATA_DIR": tmp}, clear=False):
                os.environ.pop("CLEA_CSV_PATH", None)
                os.environ.pop("CLEA_DATA_DIR", None)
                store = ReferenceStore()
                con = store._ensure_loaded()

            by_src = dict(
                con.execute(
                    "SELECT source, COUNT(*) FROM ref_party_election GROUP BY source"
                ).fetchall()
            )
            self.assertEqual(by_src.get("parlgov"), 2)
            self.assertIsNone(by_src.get("clea"))

            # нет отдельного файла clea_aggregated.duckdb
            self.assertFalse((ddir / "clea_aggregated.duckdb").exists())
            # единый файл reference.duckdb
            self.assertTrue((ddir / "reference.duckdb").exists())

    def test_parlgov_and_clea_in_single_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ddir = Path(tmp)
            _write_min_parlgov_csvs(ddir)
            clea_csv = ddir / "clea.csv"
            _write_min_clea_csv(clea_csv)

            with patch.dict(
                os.environ,
                {"PARLGOV_DATA_DIR": tmp, "CLEA_CSV_PATH": str(clea_csv)},
                clear=False,
            ):
                store = ReferenceStore()
                con = store._ensure_loaded()

            by_src = dict(
                con.execute(
                    "SELECT source, COUNT(*) FROM ref_party_election GROUP BY source"
                ).fetchall()
            )
            self.assertEqual(by_src.get("parlgov"), 2)
            self.assertEqual(by_src.get("clea"), 2)

            # всё в одном файле, нет отдельного clea_aggregated.duckdb
            self.assertTrue((ddir / "reference.duckdb").exists())
            self.assertFalse((ddir / "clea_aggregated.duckdb").exists())

            # clea_elections и clea_party_national живут в том же соединении
            self.assertTrue(_has_table(con, "clea_elections"))
            self.assertTrue(_has_table(con, "clea_party_national"))

    def test_clea_only_no_parlgov_view(self) -> None:
        """Если ParlGov CSV не загружен — ref_party_election содержит только CLEA."""
        with tempfile.TemporaryDirectory() as tmp:
            ddir = Path(tmp)
            _write_min_parlgov_csvs(ddir)
            clea_csv = ddir / "clea.csv"
            _write_min_clea_csv(clea_csv)

            with patch.dict(
                os.environ,
                {"PARLGOV_DATA_DIR": tmp, "CLEA_CSV_PATH": str(clea_csv)},
                clear=False,
            ):
                store = ReferenceStore()
                con = store._ensure_loaded()
                # симулируем отсутствие parliament_elections view
                con.execute("DROP VIEW IF EXISTS parliament_elections")
                store._rebuild_ref(con)

            n_clea = con.execute(
                "SELECT COUNT(*) FROM ref_party_election WHERE source = 'clea'"
            ).fetchone()[0]
            self.assertEqual(int(n_clea), 2)
            n_pg = con.execute(
                "SELECT COUNT(*) FROM ref_party_election WHERE source = 'parlgov'"
            ).fetchone()[0]
            self.assertEqual(int(n_pg), 0)

    def test_no_attach_detach(self) -> None:
        """В reference.duckdb не должно быть прикреплённых алиасов clea_ref."""
        with tempfile.TemporaryDirectory() as tmp:
            ddir = Path(tmp)
            _write_min_parlgov_csvs(ddir)
            clea_csv = ddir / "clea.csv"
            _write_min_clea_csv(clea_csv)

            with patch.dict(
                os.environ,
                {"PARLGOV_DATA_DIR": tmp, "CLEA_CSV_PATH": str(clea_csv)},
                clear=False,
            ):
                store = ReferenceStore()
                con = store._ensure_loaded()

            dbs = [r[1] for r in con.execute("PRAGMA database_list").fetchall()]
            self.assertNotIn("clea_ref", dbs)


if __name__ == "__main__":
    unittest.main()
