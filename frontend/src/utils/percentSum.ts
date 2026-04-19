/**
 * Допуск над 100% только из‑за float (сумма после ренормализации / цепочки Number).
 * Не путать с «лишними десятыми доли процента»: 100.01 по-прежнему считается превышением.
 */
export const PERCENT_SUM_FLOAT_EPSILON = 1e-6;

export function parseVotePercentField(s: string): number | null {
  const v = Number(String(s).replace(",", "."));
  if (!Number.isFinite(v)) return null;
  return v;
}

/** Сумма долей только по строкам с непустым названием — как тело запроса к API. */
export function sumVotePercentsNamedOnly(
  parties: readonly { name: string; votePercent: string }[],
): number {
  return parties.reduce((acc, p) => {
    if (!p.name.trim()) return acc;
    const v = parseVotePercentField(p.votePercent);
    return acc + (v ?? 0);
  }, 0);
}

export function isPercentSumOver100(sum: number): boolean {
  return sum > 100 + PERCENT_SUM_FLOAT_EPSILON;
}
