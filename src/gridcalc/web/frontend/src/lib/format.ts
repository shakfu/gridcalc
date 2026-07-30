// A non-finite ranging bound comes across the bridge as null; render it as
// "inf". Integers print bare; other numbers to `digits` places.
export function fnum(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined) return 'inf'
  if (Number.isInteger(x)) return String(x)
  // Round to `digits` places but trim trailing zeros (1.5000 -> 1.5).
  return String(Number(x.toFixed(digits)))
}

// Format a table cell value by column kind (label / boolean / number).
export function fmtCell(v: unknown, kind?: 'k' | 'bool'): string {
  if (kind === 'k') return String(v)
  if (kind === 'bool') return v ? 'yes' : 'no'
  if (v === null || v === undefined) return 'inf'
  return typeof v === 'number' ? fnum(v) : String(v)
}
