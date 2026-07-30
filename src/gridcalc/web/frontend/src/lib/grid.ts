// Grid geometry, shared by the grid component and its tests. Pixel sizes match
// the engine's fixed cell metrics.
export const CW = 90 // column width
export const CH = 22 // row height
export const GW = 52 // row-number gutter width
export const PAD = 4 // rows/cols of overscan beyond the viewport

export interface Cursor {
  r: number
  c: number
}

// 0 -> A, 25 -> Z, 26 -> AA (bijective base-26), matching engine `col_name`.
export function colName(c: number): string {
  let s = ''
  c += 1
  while (c > 0) {
    c -= 1
    s = String.fromCharCode(65 + (c % 26)) + s
    c = Math.floor(c / 26)
  }
  return s
}

export function cellRef(r: number, c: number): string {
  return colName(c) + (r + 1)
}

export interface Rect {
  r0: number
  c0: number
  r1: number
  c1: number
}

// The grid's current selection, reported up to the app so the Data menu and
// feature dialogs can act on it. `ref` is the A1 range, `active` the cursor.
export interface Selection extends Rect {
  ref: string
  active: string
}

export function selRect(a: Cursor, b: Cursor): Rect {
  return {
    r0: Math.min(a.r, b.r),
    c0: Math.min(a.c, b.c),
    r1: Math.max(a.r, b.r),
    c1: Math.max(a.c, b.c),
  }
}

// A1 for a single cell, A1:B3 for a rectangle.
export function rangeRef(a: Cursor, b: Cursor): string {
  const s = selRect(a, b)
  const start = cellRef(s.r0, s.c0)
  if (s.r0 === s.r1 && s.c0 === s.c1) return start
  return `${start}:${cellRef(s.r1, s.c1)}`
}

export function clamp(v: number, hi: number): number {
  return Math.max(0, Math.min(hi - 1, v))
}

// A solver result painted onto the sheet. The tables in the results panel say
// the same thing, but a shadow price means much more sitting on the constraint
// row it belongs to than in a column of numbers -- reading the model off the
// grid is the thing a terminal cannot do.
export type CellRole = 'objective' | 'decision' | 'binding' | 'slack'

export interface CellAnnotation {
  role: CellRole
  // Hover text: the shadow price, reduced cost, or optimal value.
  title?: string
}

// Parse a single A1 reference back to a cursor (the name box's jump target).
// `$` is accepted and ignored -- absoluteness is meaningless for a jump.
export function parseRef(s: string): Cursor | null {
  const m = /^\$?([A-Za-z]+)\$?(\d+)$/.exec(s.trim())
  if (!m) return null
  let c = 0
  for (const ch of m[1].toUpperCase()) c = c * 26 + (ch.charCodeAt(0) - 64)
  const r = parseInt(m[2], 10)
  if (c < 1 || r < 1) return null
  return { r: r - 1, c: c - 1 }
}
