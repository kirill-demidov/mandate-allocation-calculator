import type {
  CalculateRequest,
  CalculateResponse,
  ReferenceCountry,
  ReferenceElectionDetail,
  ReferenceElectionsResponse,
  ReferencePrefillResponse,
} from "./types";

const base = import.meta.env.VITE_API_BASE ?? "";

async function parseError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((d) => JSON.stringify(d)).join("; ");
    }
  } catch {
    /* ignore */
  }
  return res.statusText || `HTTP ${res.status}`;
}

export async function calculate(
  body: CalculateRequest,
): Promise<CalculateResponse> {
  const res = await fetch(`${base}/api/calculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CalculateResponse;
}

export async function downloadExcel(
  body: CalculateRequest,
  lang: "ru" | "en",
): Promise<void> {
  const q = new URLSearchParams({ lang });
  const res = await fetch(`${base}/api/export.xlsx?${q.toString()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="([^"]+)"/);
  const filename = m?.[1] ?? (lang === "ru" ? "результаты.xlsx" : "results.xlsx");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export async function fetchReferenceStatus(): Promise<Record<string, unknown>> {
  const res = await fetch(`${base}/api/reference/status`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Record<string, unknown>;
}

export async function fetchReferenceCountries(): Promise<ReferenceCountry[]> {
  const res = await fetch(`${base}/api/reference/countries`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferenceCountry[];
}

export async function fetchReferenceElections(
  countryId: number,
  limit: number,
  offset: number,
): Promise<ReferenceElectionsResponse> {
  const q = new URLSearchParams({
    country_id: String(countryId),
    limit: String(limit),
    offset: String(offset),
  });
  const res = await fetch(`${base}/api/reference/elections?${q}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferenceElectionsResponse;
}

export async function fetchReferenceElectionDetail(
  electionId: number,
): Promise<ReferenceElectionDetail> {
  const res = await fetch(`${base}/api/reference/election/${electionId}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferenceElectionDetail;
}

export async function fetchReferencePrefill(
  electionId: number,
  thresholdPercent: number,
): Promise<ReferencePrefillResponse> {
  const q = new URLSearchParams({
    threshold_percent: String(thresholdPercent),
  });
  const res = await fetch(
    `${base}/api/reference/election/${electionId}/prefill?${q.toString()}`,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferencePrefillResponse;
}
