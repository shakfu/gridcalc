import type {
  ChartData,
  Dims,
  GoalResult,
  OpenResult,
  SaveResult,
  Sheets,
  SolveResult,
  SweepResult,
  Viewport,
  ViewportCell,
} from './types'

const colLetter = (c: number): string => {
  let s = ''
  c += 1
  while (c > 0) {
    c -= 1
    s = String.fromCharCode(65 + (c % 26)) + s
    c = Math.floor(c / 26)
  }
  return s
}

const parseRef = (s: string): { r: number; c: number } | null => {
  const m = /^([A-Za-z]+)(\d+)$/.exec(s.trim())
  if (!m) return null
  let c = 0
  for (const ch of m[1].toUpperCase()) c = c * 26 + (ch.charCodeAt(0) - 64)
  return { r: parseInt(m[2], 10) - 1, c: c - 1 }
}

const parseRange = (spec: string) => {
  const [a, b] = spec.split(':')
  const A = parseRef(a)
  const B = parseRef(b ?? a)
  if (!A || !B) return null
  return {
    r0: Math.min(A.r, B.r),
    c0: Math.min(A.c, B.c),
    r1: Math.max(A.r, B.r),
    c1: Math.max(A.c, B.c),
  }
}

// A canned optimal LP result (the Wyndor example) for the dev/test bridge --
// real solving lives in the Python engine, not the mock.
const MOCK_SOLVE: SolveResult = {
  ok: true,
  status: 'OPTIMAL',
  optimal: true,
  objective: 36,
  values: { A2: 2, A3: 6 },
  applied: true,
  quadratic: false,
  sensitivity: {
    variables: [
      { cell: 'A2', value: 2, reduced_cost: 0, obj_coef: 3, obj_from: 0, obj_till: 7.5 },
      { cell: 'A3', value: 6, reduced_cost: 0, obj_coef: 5, obj_from: 2, obj_till: null },
    ],
    constraints: [
      { cell: 'C2', shadow_price: 0, rhs: 4, activity: 2, slack: 2, binding: false, rhs_from: 2, rhs_till: null },
      { cell: 'C3', shadow_price: 1.5, rhs: 12, activity: 12, slack: 0, binding: true, rhs_from: 6, rhs_till: 18 },
      { cell: 'C4', shadow_price: 1, rhs: 18, activity: 18, slack: 0, binding: true, rhs_from: 12, rhs_till: 24 },
    ],
  },
}

// A stateful stand-in for the pywebview js_api so the UI runs in a plain
// browser -- `npm run dev` (Vite HMR) and the vitest suite. It keeps a tiny
// in-memory workbook (sheets + a sparse cell store) so actions have observable
// effects. Installed only in DEV builds; the production bundle uses the real
// pywebview bridge, and headless tests of that bundle inject their own mock.
export function installMockBridge(): void {
  if (!import.meta.env.DEV) return
  if (window.pywebview?.api) return

  const dims: Dims = { ncol: 256, nrow: 1024, filename: '' }
  const sheets: Sheets = { active: 0, names: ['Sheet1', 'Data'] }

  const cells = new Map<string, string>() // "r,c" -> source text
  const key = (r: number, c: number) => `${r},${c}`
  const seed: Array<[number, number, string]> = [
    [0, 0, 'gridcalc demo'],
    [2, 0, 'Item'],
    [2, 1, 'Qty'],
    [2, 2, 'Price'],
    [3, 0, 'Widget'],
    [3, 1, '10'],
    [3, 2, '2.5'],
    [4, 0, 'Gadget'],
    [4, 1, '4'],
    [4, 2, '9'],
    [5, 0, 'Gizmo'],
    [5, 1, '7'],
    [5, 2, '3.25'],
  ]
  for (const [r, c, t] of seed) cells.set(key(r, c), t)

  const isNumeric = (s: string) => s !== '' && (!Number.isNaN(Number(s)) || s.startsWith('='))

  interface Style {
    bold: boolean
    italic: boolean
    underline: boolean
    fmt: string
    fmtstr: string
  }
  const styles = new Map<string, Style>()

  let clip: {
    r0: number
    c0: number
    cells: Array<{ dr: number; dc: number; text: string }>
    cut: boolean
  } | null = null

  window.pywebview = {
    api: {
      dims: async (): Promise<Dims> => ({ ...dims }),
      sheets: async (): Promise<Sheets> => ({ ...sheets }),
      set_active: async (idx: number): Promise<Sheets> => {
        if (idx >= 0 && idx < sheets.names.length) sheets.active = idx
        return { ...sheets }
      },
      undo: async () => ({ ok: true }),
      redo: async () => ({ ok: true }),
      save: async (path?: string): Promise<SaveResult> => {
        const target = path || dims.filename
        if (!target) return { ok: false, needs_path: true }
        dims.filename = target
        return { ok: true, path: target }
      },
      save_dialog: async (): Promise<SaveResult> => {
        dims.filename = '/tmp/mock-workbook.json'
        return { ok: true, path: dims.filename }
      },
      open_dialog: async (): Promise<OpenResult> => {
        dims.filename = '/tmp/opened.json'
        sheets.names = ['Sheet1', 'Budget', 'Data']
        sheets.active = 0
        return { ok: true, filename: dims.filename }
      },
      open_file: async (path: string): Promise<OpenResult> => {
        dims.filename = path
        return { ok: true, filename: path }
      },
      viewport: async (r0: number, c0: number, rows: number, cols: number): Promise<Viewport> => {
        const out: ViewportCell[] = []
        for (let r = r0; r < r0 + rows; r++) {
          for (let c = c0; c < c0 + cols; c++) {
            const text = cells.get(key(r, c))
            if (!text) continue
            const cell: ViewportCell = { r, c, text, align: isNumeric(text) ? 'r' : 'l' }
            const st = styles.get(key(r, c))
            if (st?.bold) cell.bold = true
            if (st?.italic) cell.italic = true
            if (st?.underline) cell.underline = true
            out.push(cell)
          }
        }
        return { r0, c0, rows, cols, cells: out }
      },
      set_format: async (r0: number, c0: number, r1: number, c1: number, spec: string) => {
        const s = spec || ''
        const style = s.length > 0 && [...s].every((ch) => 'bui'.includes(ch))
        const single = s.length === 1 && 'LRIGD$%*'.includes(s.toUpperCase())
        for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
          for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) {
            if (!cells.has(key(r, c))) continue
            const cur: Style = styles.get(key(r, c)) ?? {
              bold: false,
              italic: false,
              underline: false,
              fmt: '',
              fmtstr: '',
            }
            if (style) {
              for (const ch of s) {
                if (ch === 'b') cur.bold = !cur.bold
                else if (ch === 'u') cur.underline = !cur.underline
                else if (ch === 'i') cur.italic = !cur.italic
              }
            } else if (single) {
              cur.fmt = s.toUpperCase()
              cur.fmtstr = ''
            } else if (s) {
              cur.fmtstr = s.slice(0, 31)
              cur.fmt = ''
            }
            styles.set(key(r, c), cur)
          }
        }
        return { ok: true }
      },
      set_global_format: async () => ({ ok: true }),
      cell_source: async (r: number, c: number): Promise<string> => cells.get(key(r, c)) ?? '',
      set_cell: async (r: number, c: number, text: string) => {
        if (text) cells.set(key(r, c), text)
        else cells.delete(key(r, c))
        return { ok: true }
      },
      clear_range: async (r0: number, c0: number, r1: number, c1: number) => {
        for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
          for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) cells.delete(key(r, c))
        }
        return { ok: true }
      },
      copy: async (r0: number, c0: number, r1: number, c1: number, cut: boolean) => {
        const ra = Math.min(r0, r1)
        const ca = Math.min(c0, c1)
        const buf: Array<{ dr: number; dc: number; text: string }> = []
        const lines: string[] = []
        for (let r = ra; r <= Math.max(r0, r1); r++) {
          const row: string[] = []
          for (let c = ca; c <= Math.max(c0, c1); c++) {
            const t = cells.get(key(r, c))
            if (t) buf.push({ dr: r - ra, dc: c - ca, text: t })
            row.push(t ?? '')
          }
          lines.push(row.join('\t'))
        }
        clip = { r0: ra, c0: ca, cells: buf, cut }
        return { ok: true, tsv: lines.join('\n') }
      },
      paste: async (r: number, c: number) => {
        if (!clip) return { ok: false }
        for (const cell of clip.cells) cells.set(key(r + cell.dr, c + cell.dc), cell.text)
        if (clip.cut) {
          const dest = new Set(clip.cells.map((x) => key(r + x.dr, c + x.dc)))
          for (const cell of clip.cells) {
            const sk = key(clip.r0 + cell.dr, clip.c0 + cell.dc)
            if (!dest.has(sk)) cells.delete(sk)
          }
          clip = null
        }
        return { ok: true }
      },
      paste_text: async (r: number, c: number, text: string) => {
        const rows = text.replace(/\r\n?/g, '\n').split('\n')
        if (rows.length && rows[rows.length - 1] === '') rows.pop()
        rows.forEach((line, dr) =>
          line.split('\t').forEach((val, dc) => {
            if (val) cells.set(key(r + dr, c + dc), val)
            else cells.delete(key(r + dr, c + dc))
          }),
        )
        return { ok: true }
      },
      fill: async (r0: number, c0: number, r1: number, c1: number, direction: 'down' | 'right') => {
        if (direction === 'down') {
          for (let c = c0; c <= c1; c++) {
            const src = cells.get(key(r0, c))
            for (let r = r0 + 1; r <= r1; r++) {
              if (src) cells.set(key(r, c), src)
              else cells.delete(key(r, c))
            }
          }
        } else {
          for (let r = r0; r <= r1; r++) {
            const src = cells.get(key(r, c0))
            for (let c = c0 + 1; c <= c1; c++) {
              if (src) cells.set(key(r, c), src)
              else cells.delete(key(r, c))
            }
          }
        }
        return { ok: true }
      },
      solve_selection: async (): Promise<SolveResult> => ({ ...MOCK_SOLVE }),
      solve_model: async (): Promise<SolveResult> => ({ ...MOCK_SOLVE }),
      goal_seek: async (_f: string, target: number): Promise<GoalResult> => ({
        ok: true,
        converged: true,
        iterations: 12,
        var_value: target / 2,
        formula_value: target,
        residual: 0,
        applied: true,
      }),
      opt_sweep: async (): Promise<SweepResult> => ({
        ok: true,
        points: [
          { rhs: 0, status: 'OPTIMAL', objective: 24, shadow_price: 1.5, delta: null, breakpoint: false },
          { rhs: 4, status: 'OPTIMAL', objective: 30, shadow_price: 1.5, delta: 6, breakpoint: false },
          { rhs: 8, status: 'OPTIMAL', objective: 36, shadow_price: 1, delta: 6, breakpoint: true },
        ],
      }),
      chart_data: async (spec: string): Promise<ChartData> => {
        const rect = parseRange(spec)
        if (!rect) return { error: `bad range: ${spec}` }
        const rows: number[] = []
        for (let r = rect.r0; r <= rect.r1; r++) rows.push(r)
        const cols: number[] = []
        for (let c = rect.c0; c <= rect.c1; c++) cols.push(c)
        let labelCol: number | null = null
        if (cols.length > 1 && rows.some((r) => !isNumeric(cells.get(key(r, cols[0])) ?? ''))) {
          labelCol = cols[0]
        }
        const labels =
          labelCol !== null
            ? rows.map((r) => cells.get(key(r, labelCol as number)) ?? '')
            : rows.map((r) => String(r + 1))
        const seriesCols = labelCol !== null ? cols.filter((c) => c !== labelCol) : cols
        const series = seriesCols.map((c) => ({
          name: colLetter(c),
          values: rows.map((r) => {
            const t = cells.get(key(r, c))
            const n = t ? Number(t) : NaN
            return Number.isFinite(n) ? n : null
          }),
        }))
        return { title: spec.toUpperCase(), labels, series }
      },
    },
  }
}
