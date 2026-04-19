export type MandateRow = {
  party: string;
  vote_percent: number;
  hare: number;
  droop: number;
  sainte_lague: number;
  dhondt: number;
  imperiali: number;
};

export type CalculateResponse = {
  rows: MandateRow[];
  vote_percent_sum: number;
};

export type CalculateRequest = {
  total_mandates: number;
  threshold_percent: number;
  parties: { name: string; vote_percent: number }[];
};

export type ReferenceCountry = {
  country_id: number;
  code: string;
  name: string;
};

export type ReferenceElectionRow = {
  election_id: number;
  election_date: string;
  country_code: string;
  country_name: string;
  seats_total: number | null;
};

export type CleaElectionRow = {
  election_key: string;
  election_date: string;
  country_label: string | null;
  votes_valid: number | null;
  seats_total: number | null;
  /** Места по строкам CLEA с MAG>1 (пропорциональный уровень), если в CSV есть MAG */
  seats_pr_tier: number | null;
  /** Места по MAG≤1 или MAG NULL (одномандатные / окружной уровень) */
  seats_constituency_tier: number | null;
  threshold_percent: number | null;
};

/** Список выборов из ref_party_election (ParlGov + CLEA, одна DuckDB). */
export type UnifiedElectionRow = {
  election_key: string;
  parlgov_election_id: number | null;
  election_date: string;
  election_label: string | null;
  source: string;
  threshold_percent: number | null;
  n_parties: number;
  votes_valid: number | null;
  seats_total: number | null;
  seats_pr_tier: number | null;
  seats_constituency_tier: number | null;
};

export type ReferenceElectionsResponse = {
  items: ReferenceElectionRow[];
  total: number;
  limit: number;
  offset: number;
};

export type UnifiedElectionsResponse = {
  items: UnifiedElectionRow[];
  total: number;
  limit: number;
  offset: number;
};

export type ReferencePartyRow = {
  name: string;
  vote_share: number | null;
  seats_recorded: number | null;
  votes_estimated: number | null;
  seats_parlgov?: number | null;
};

export type ReferenceElectionDetail = {
  source?: "parlgov" | "clea";
  election_id: number | null;
  election_key?: string | null;
  election_date: string | null;
  country_code: string | null;
  country_name: string | null;
  seats_total: number | null;
  votes_valid: number | null;
  /** CLEA: сумма мест в многомандатных округах (MAG>1). ParlGov: не задаётся */
  seats_pr_tier?: number | null;
  /** CLEA: сумма мест в одномандатных / при MAG≤1. ParlGov: не задаётся */
  seats_constituency_tier?: number | null;
  threshold_from_data?: number | null;
  parties: ReferencePartyRow[];
};

export type ReferencePrefillResponse = {
  totalMandates: number;
  thresholdPercent: number;
  parties: { name: string; votePercent: string }[];
  meta?: Record<string, unknown>;
};
