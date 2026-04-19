/** Состояние react-router для предзаполнения калькулятора с /app/votes */
export type CalculatorPrefillState = {
  totalMandates: number;
  thresholdPercent: number;
  parties: { name: string; votePercent: string }[];
};
