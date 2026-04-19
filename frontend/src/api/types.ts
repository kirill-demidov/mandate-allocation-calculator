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

export type ReferenceElectionsResponse = {
  items: ReferenceElectionRow[];
  total: number;
  limit: number;
  offset: number;
};

export type ReferencePartyRow = {
  name: string;
  vote_share: number | null;
  seats_recorded: number | null;
  votes_estimated: number | null;
};

export type ReferenceElectionDetail = {
  election_id: number;
  election_date: string | null;
  country_code: string | null;
  country_name: string | null;
  seats_total: number | null;
  votes_valid: number | null;
  parties: ReferencePartyRow[];
};

export type ReferencePrefillResponse = {
  totalMandates: number;
  thresholdPercent: number;
  parties: { name: string; votePercent: string }[];
  meta?: Record<string, unknown>;
};
