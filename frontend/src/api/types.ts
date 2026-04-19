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
