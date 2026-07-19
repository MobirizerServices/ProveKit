// Rough public list prices (USD per 1M tokens) for a *cost estimate only*. Prices drift
// constantly — treat these as approximate, and unknown models show no estimate rather than a
// wrong number. Update as needed.
const PRICES: Record<string, [number, number]> = {
  // model substring: [input, output] per 1M tokens
  "gpt-4o-mini": [0.15, 0.6],
  "gpt-4o": [2.5, 10],
  "gpt-4.1-nano": [0.1, 0.4],
  "gpt-4.1-mini": [0.4, 1.6],
  "gpt-4.1": [2, 8],
  "o4-mini": [1.1, 4.4],
  "o3": [2, 8],
  "claude-haiku": [0.8, 4],
  "claude-sonnet": [3, 15],
  "claude-opus": [15, 75],
  "gemini-2.5-flash": [0.3, 2.5],
  "gemini-2.5-pro": [1.25, 10],
};

function priceFor(model?: string): [number, number] | null {
  if (!model) return null;
  const m = model.toLowerCase();
  for (const k of Object.keys(PRICES)) if (m.includes(k)) return PRICES[k];
  return null;
}

export function estimateCost(model?: string, inTok?: number | null, outTok?: number | null): number | null {
  const p = priceFor(model);
  if (!p || inTok == null) return null;
  return (inTok * p[0] + (outTok ?? 0) * p[1]) / 1e6;
}

export function fmtCost(c: number | null): string | null {
  if (c == null) return null;
  if (c === 0) return null;                 // nothing to show
  if (c < 0.01) return "<$0.01";            // sub-cent reads clean, never "~$0.0000"
  if (c < 1) return `$${c.toFixed(2)}`;
  return `$${c.toFixed(c < 100 ? 2 : 0)}`;
}

// Full-precision cost for tooltips/hover (where sub-cent detail is useful).
export function fmtCostPrecise(c: number | null): string | null {
  if (c == null || c === 0) return null;
  if (c < 0.01) return `$${c.toFixed(6)}`;
  return `$${c.toFixed(4)}`;
}
