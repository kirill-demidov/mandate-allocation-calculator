import type {
  CalculateRequest,
  CalculateResponse,
  CleaElectionRow,
  ReferenceCountry,
  ReferenceElectionDetail,
  ReferenceElectionsResponse,
  ReferencePrefillResponse,
  UnifiedElectionsResponse,
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

export type ReferenceRefreshResponse = {
  parlgov: Record<string, unknown>;
  clea: Record<string, unknown>;
  status: Record<string, unknown>;
};

export async function postReferenceRefresh(
  force = false,
): Promise<ReferenceRefreshResponse> {
  const q = force ? "?force=true" : "";
  const res = await fetch(`${base}/api/reference/refresh${q}`, { method: "POST" });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferenceRefreshResponse;
}

export async function fetchReferenceCountries(): Promise<ReferenceCountry[]> {
  const res = await fetch(`${base}/api/reference/countries`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferenceCountry[];
}

export type ReferenceElectionsQuery = {
  countryId?: number;
  limit: number;
  offset: number;
  dateFrom?: string;
  dateTo?: string;
  q?: string;
};

export async function fetchReferenceElections(
  params: ReferenceElectionsQuery,
): Promise<ReferenceElectionsResponse> {
  const q = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.countryId != null) q.set("country_id", String(params.countryId));
  if (params.dateFrom) q.set("date_from", params.dateFrom);
  if (params.dateTo) q.set("date_to", params.dateTo);
  if (params.q?.trim()) q.set("q", params.q.trim());
  const res = await fetch(`${base}/api/reference/elections?${q}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferenceElectionsResponse;
}

export type UnifiedElectionsQuery = {
  countryId?: number;
  limit: number;
  offset: number;
  dateFrom?: string;
  dateTo?: string;
  q?: string;
  source?: "parlgov" | "clea";
};

export async function fetchUnifiedElections(
  params: UnifiedElectionsQuery,
): Promise<UnifiedElectionsResponse> {
  const q = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.countryId != null) q.set("country_id", String(params.countryId));
  if (params.dateFrom) q.set("date_from", params.dateFrom);
  if (params.dateTo) q.set("date_to", params.dateTo);
  if (params.q?.trim()) q.set("q", params.q.trim());
  if (params.source) q.set("source", params.source);
  const res = await fetch(`${base}/api/reference/unified-elections?${q}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as UnifiedElectionsResponse;
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

export type CleaElectionsResponse = {
  items: CleaElectionRow[];
  total: number;
  limit: number;
  offset: number;
};

export async function fetchCleaStatus(): Promise<Record<string, unknown>> {
  const res = await fetch(`${base}/api/reference/clea/status`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Record<string, unknown>;
}

export async function fetchCleaElections(
  params: {
    limit: number;
    offset: number;
    dateFrom?: string;
    dateTo?: string;
    q?: string;
  },
): Promise<CleaElectionsResponse> {
  const q = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
  });
  if (params.dateFrom) q.set("date_from", params.dateFrom);
  if (params.dateTo) q.set("date_to", params.dateTo);
  if (params.q?.trim()) q.set("q", params.q.trim());
  const res = await fetch(`${base}/api/reference/clea/elections?${q}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CleaElectionsResponse;
}

export async function fetchCleaDetail(
  electionKey: string,
): Promise<ReferenceElectionDetail> {
  const q = new URLSearchParams({ election_key: electionKey });
  const res = await fetch(`${base}/api/reference/clea/detail?${q}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferenceElectionDetail;
}

export async function fetchCleaPrefill(
  electionKey: string,
  thresholdPercent: number | null,
): Promise<ReferencePrefillResponse> {
  const q = new URLSearchParams({ election_key: electionKey });
  if (thresholdPercent != null) {
    q.set("threshold_percent", String(thresholdPercent));
  }
  const res = await fetch(`${base}/api/reference/clea/prefill?${q}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as ReferencePrefillResponse;
}

export function cleaDuckdbDownloadHref(): string {
  return `${base}/api/reference/clea/duckdb`;
}

export function referenceDuckdbDownloadHref(): string {
  return `${base}/api/reference/duckdb`;
}
