"""Расчёт мандатов (логика перенесена из Streamlit app.py без изменения алгоритмов)."""

from __future__ import annotations

import numpy as np


def calculate_quota_hare(total_votes: float, total_mandates: int) -> float:
    return total_votes / total_mandates


def calculate_quota_droop(total_votes: float, total_mandates: int) -> float:
    return total_votes / (total_mandates + 1) + 1


def method_saint_lague(
    votes: np.ndarray, total_mandates: int, k: float = 2, d: float = 1
) -> np.ndarray:
    """
    Метод Сент-Лагю и вариации.
    k=2, d=1 — Сент-Лагю; k=1, d=1 — Д'Ондт; k=1, d=2 — Империали.
    """
    mandates = np.zeros(len(votes))
    while sum(mandates) < total_mandates:
        quotients = votes / (k * mandates + d)
        party_idx = int(np.argmax(quotients))
        mandates[party_idx] += 1
    return mandates


def allocate_largest_remainders(
    votes: np.ndarray, quota: float, total_mandates: int
) -> np.ndarray:
    if quota <= 0:
        raise ValueError("quota must be positive")
    mandates = np.floor(votes / quota)
    remainders = votes / quota - mandates
    mandates = mandates.astype(int)
    allocated = int(np.sum(mandates))
    left = int(total_mandates - allocated)
    if left > 0:
        idx = np.argsort(-remainders)
        n = len(idx)
        for i in range(left):
            mandates[idx[i % n]] += 1
    return mandates


def calculate_mandates(
    vote_percents: np.ndarray, total_mandates: int, threshold_percent: float = 0.0
) -> dict[str, np.ndarray]:
    """
    vote_percents — доли голосов в процентах (как во входе Streamlit).
    threshold_percent — электоральный барьер в процентах; партии ниже порога обнуляются.
    """
    valid_votes = vote_percents.copy().astype(float)
    valid_votes[vote_percents < threshold_percent] = 0
    total_valid_votes = float(np.sum(valid_votes))
    if total_valid_votes <= 0:
        raise ValueError("После применения порога не осталось голосов для распределения.")
    quota_hare = calculate_quota_hare(total_valid_votes, total_mandates)
    quota_droop = calculate_quota_droop(total_valid_votes, total_mandates)
    mandates_hare = allocate_largest_remainders(valid_votes, quota_hare, total_mandates)
    mandates_droop = allocate_largest_remainders(
        valid_votes, quota_droop, total_mandates
    )
    mandates_sl = method_saint_lague(valid_votes, total_mandates, k=2, d=1)
    mandates_dhondt = method_saint_lague(valid_votes, total_mandates, k=1, d=1)
    mandates_imperiali = method_saint_lague(valid_votes, total_mandates, k=1, d=2)
    return {
        "hare": mandates_hare,
        "droop": mandates_droop,
        "sainte_lague": mandates_sl,
        "dhondt": mandates_dhondt,
        "imperiali": mandates_imperiali,
    }
