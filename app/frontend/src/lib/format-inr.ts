/**
 * Format a number using the Indian numbering system (lakh/crore).
 * e.g. 1000000 → "₹10,00,000"
 */
export function formatINR(value: number, decimals = 0): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';

  const [intPart, decPart] = abs.toFixed(decimals).split('.');
  const digits = intPart.split('');

  // Indian grouping: last 3 digits, then every 2
  const result: string[] = [];
  const len = digits.length;
  if (len <= 3) {
    result.push(intPart);
  } else {
    result.push(digits.slice(0, len - 3).reduce((acc, d, i, arr) => {
      const pos = arr.length - i;
      return acc + d + (pos > 1 && pos % 2 === 1 ? ',' : '');
    }, ''));
    result.push(',');
    result.push(digits.slice(len - 3).join(''));
  }

  const formatted = result.join('');
  const withDec = decPart ? `${formatted}.${decPart}` : formatted;
  return `${sign}₹${withDec}`;
}

/**
 * Compact INR format: ₹10.5L, ₹1.2Cr
 */
export function formatINRCompact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1e7) return `${sign}₹${(value / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `${sign}₹${(value / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `${sign}₹${(value / 1e3).toFixed(1)}K`;
  return `${sign}₹${value.toFixed(0)}`;
}

/**
 * Format percentage with sign
 */
export function formatPct(value: number, decimals = 2): string {
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}
