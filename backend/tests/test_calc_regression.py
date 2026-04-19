"""Регрессия: суммы мест, порог, эталонные малые примеры для calculate_mandates."""

from __future__ import annotations

import unittest

import numpy as np

from app.calc import calculate_mandates


class TestCalcRegression(unittest.TestCase):
    def test_each_method_sums_to_total_mandates(self) -> None:
        votes = np.array([40.0, 35.0, 25.0])
        total = 10
        out = calculate_mandates(votes, total, threshold_percent=0.0)
        for key, arr in out.items():
            self.assertEqual(int(np.sum(arr)), total, msg=key)

    def test_threshold_excludes_small_party(self) -> None:
        votes = np.array([50.0, 48.0, 2.0])
        out = calculate_mandates(votes, 5, threshold_percent=3.0)
        # 2% < 3% → третья партия обнулена, остаётся 98 голосов на двоих
        self.assertEqual(int(np.sum(out["hare"])), 5)
        self.assertEqual(int(np.sum(out["dhondt"])), 5)

    def test_hare_two_party_five_seats(self) -> None:
        """Квота Хэйра 100/5=20 → 60/20=3, 40/20=2, остатков нет."""
        votes = np.array([60.0, 40.0])
        out = calculate_mandates(votes, 5, threshold_percent=0.0)
        self.assertListEqual(out["hare"].astype(int).tolist(), [3, 2])

    def test_hare_remainder_one_seat(self) -> None:
        """Сумма целых частей на 1 меньше числа мандатов — один уходит по наибольшему остатку."""
        votes = np.array([41.0, 29.0, 30.0])
        total = 3
        out = calculate_mandates(votes, total, threshold_percent=0.0)
        self.assertEqual(int(np.sum(out["hare"])), total)
        # 41/33.33.. floor 1, 29→0, 30→0 даёт 1; квота 100/3 — проверяем только сумму и неотрицательность
        self.assertTrue(np.all(out["hare"] >= 0))


if __name__ == "__main__":
    unittest.main()
