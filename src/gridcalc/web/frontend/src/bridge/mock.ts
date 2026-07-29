import type {
  ChartData,
  ColWidths,
  Dims,
  GoalResult,
  OpenResult,
  SaveResult,
  Sheets,
  InferResult,
  ModelSpec,
  ModelsResult,
  NamesResult,
  SaveModelResult,
  SavedModel,
  SearchMatch,
  SearchResult,
  SheetsResult,
  SolveResult,
  Stats,
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

  const dims: Dims = { ncol: 256, nrow: 1024, filename: '', dirty: false }
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

  // Mirrors `Api._touch`: any mutation dirties the workbook and says so.
  const touch = () => {
    dims.dirty = true
    return { ok: true, dirty: true }
  }

  interface Style {
    bold: boolean
    italic: boolean
    underline: boolean
    fmt: string
    fmtstr: string
  }
  const styles = new Map<string, Style>()
  const models = new Map<string, SavedModel>()
  const colWidths = new Map<number, number>()
  const names = new Map<string, string>() // name -> A1 range

  // Structural edits, mock-side: move every cell (and its style) across the
  // insertion/deletion point. `delta > 0` inserts blank lines at `at`, `delta
  // < 0` deletes `|delta|` of them starting there. The real engine also
  // rewrites formula references; the mock stores source text verbatim and
  // never evaluates, so there is nothing here to rewrite.
  const shift = (axis: 'r' | 'c', at: number, delta: number) => {
    const moved = new Map<string, string>()
    const movedStyles = new Map<string, Style>()
    for (const [k, text] of cells) {
      const [r, c] = k.split(',').map(Number)
      const along = axis === 'r' ? r : c
      if (delta < 0 && along >= at && along < at - delta) continue // deleted
      const shifted = along >= at ? along + delta : along
      const nk = axis === 'r' ? key(shifted, c) : key(r, shifted)
      moved.set(nk, text)
      const st = styles.get(k)
      if (st) movedStyles.set(nk, st)
    }
    cells.clear()
    styles.clear()
    for (const [k, v] of moved) cells.set(k, v)
    for (const [k, v] of movedStyles) styles.set(k, v)
  }

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
      search: async (pattern: string): Promise<SearchResult> => {
        const pat = (pattern ?? '').toLowerCase()
        if (!pat) return { matches: [], total: 0, truncated: false }
        const hits: SearchMatch[] = []
        for (const [k, text] of cells) {
          if (!text.toLowerCase().includes(pat)) continue
          const [r, c] = k.split(',').map(Number)
          hits.push({ r, c, ref: `${colLetter(c)}${r + 1}` })
        }
        hits.sort((a, b) => a.r - b.r || a.c - b.c)
        return { matches: hits, total: hits.length, truncated: false }
      },
      recalc: async () => ({ ok: true, dirty: dims.dirty }),
      list_names: async (): Promise<NamesResult> => ({
        names: [...names.entries()]
          .map(([name, range]) => ({ name, range, sheet: '' }))
          .sort((a, b) => a.name.localeCompare(b.name)),
      }),
      set_name: async (name: string, rng: string) => {
        const key = (name ?? '').trim()
        if (!key || !/^[A-Za-z][A-Za-z0-9_]*$/.test(key)) {
          return { ok: false, error: `not a usable name: '${name}'` }
        }
        if (/^[A-Za-z]{1,2}\d+$/.test(key)) {
          return { ok: false, error: `${key} is a cell reference, not a name` }
        }
        names.set(key, rng)
        touch()
        return { ok: true, name: key }
      },
      delete_name: async (name: string) => {
        if (!names.has(name)) return { ok: false, error: `no such name: ${name}` }
        names.delete(name)
        return touch()
      },
      col_widths: async (): Promise<ColWidths> => ({
        widths: Object.fromEntries([...colWidths].map(([c, w]) => [String(c), w])),
      }),
      set_col_width: async (col: number, px: number) => {
        colWidths.set(col, px)
        return touch()
      },
      add_sheet: async (name: string): Promise<SheetsResult> => {
        const n = (name ?? '').trim()
        if (!n) return { ...sheets, ok: false, error: 'a sheet needs a name' }
        if (sheets.names.includes(n)) {
          return { ...sheets, ok: false, error: `sheet '${n}' already exists` }
        }
        sheets.names.push(n)
        sheets.active = sheets.names.length - 1
        touch()
        return { ...sheets, ok: true }
      },
      delete_sheet: async (name: string): Promise<SheetsResult> => {
        const i = sheets.names.indexOf(name)
        if (i < 0) return { ...sheets, ok: false, error: `no such sheet: ${name}` }
        if (sheets.names.length <= 1) {
          return { ...sheets, ok: false, error: 'cannot remove the last sheet' }
        }
        sheets.names.splice(i, 1)
        if (sheets.active >= sheets.names.length) sheets.active = sheets.names.length - 1
        else if (sheets.active > i) sheets.active -= 1
        touch()
        return { ...sheets, ok: true }
      },
      rename_sheet: async (old: string, name: string): Promise<SheetsResult> => {
        const n = (name ?? '').trim()
        const i = sheets.names.indexOf(old)
        if (!n) return { ...sheets, ok: false, error: 'a sheet needs a name' }
        if (i < 0) return { ...sheets, ok: false, error: `no such sheet: ${old}` }
        if (n !== old && sheets.names.includes(n)) {
          return { ...sheets, ok: false, error: `sheet '${n}' already exists` }
        }
        sheets.names[i] = n
        touch()
        return { ...sheets, ok: true }
      },
      move_sheet: async (name: string, index: number): Promise<SheetsResult> => {
        const i = sheets.names.indexOf(name)
        if (i < 0) return { ...sheets, ok: false, error: `no such sheet: ${name}` }
        if (index < 0 || index >= sheets.names.length) {
          return { ...sheets, ok: false, error: `index out of range: ${index}` }
        }
        const activeName = sheets.names[sheets.active]
        sheets.names.splice(i, 1)
        sheets.names.splice(index, 0, name)
        sheets.active = sheets.names.indexOf(activeName)
        touch()
        return { ...sheets, ok: true }
      },
      insert_rows: async (at: number, count: number) => {
        shift('r', at, Math.max(1, count))
        return touch()
      },
      insert_cols: async (at: number, count: number) => {
        shift('c', at, Math.max(1, count))
        return touch()
      },
      delete_rows: async (r0: number, r1: number) => {
        const [a, b] = [Math.min(r0, r1), Math.max(r0, r1)]
        shift('r', a, -(b - a + 1))
        return touch()
      },
      delete_cols: async (c0: number, c1: number) => {
        const [a, b] = [Math.min(c0, c1), Math.max(c0, c1)]
        shift('c', a, -(b - a + 1))
        return touch()
      },
      undo: async () => touch(),
      redo: async () => touch(),
      save: async (path?: string): Promise<SaveResult> => {
        const target = path || dims.filename
        if (!target) return { ok: false, needs_path: true }
        dims.filename = target
        dims.dirty = false
        return { ok: true, path: target }
      },
      save_dialog: async (): Promise<SaveResult> => {
        dims.filename = '/tmp/mock-workbook.json'
        dims.dirty = false
        return { ok: true, path: dims.filename }
      },
      open_dialog: async (): Promise<OpenResult> => {
        dims.filename = '/tmp/opened.json'
        dims.dirty = false
        sheets.names = ['Sheet1', 'Budget', 'Data']
        sheets.active = 0
        return { ok: true, filename: dims.filename }
      },
      open_file: async (path: string): Promise<OpenResult> => {
        dims.filename = path
        dims.dirty = false
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
      // The mock stores source text and never evaluates, so a formula cell is
      // counted but contributes no value -- the real Api aggregates `cl.val`.
      stats: async (r0: number, c0: number, r1: number, c1: number): Promise<Stats> => {
        let count = 0
        const nums: number[] = []
        for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
          for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) {
            const text = cells.get(key(r, c))
            if (!text) continue
            count++
            const n = Number(text)
            if (text.trim() !== '' && Number.isFinite(n)) nums.push(n)
          }
        }
        const sum = nums.length ? nums.reduce((a, b) => a + b, 0) : null
        return {
          count,
          numeric: nums.length,
          sum,
          avg: sum === null ? null : sum / nums.length,
          min: nums.length ? Math.min(...nums) : null,
          max: nums.length ? Math.max(...nums) : null,
        }
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
        return touch()
      },
      set_global_format: async () => touch(),
      cell_source: async (r: number, c: number): Promise<string> => cells.get(key(r, c)) ?? '',
      set_cell: async (r: number, c: number, text: string) => {
        if (text) cells.set(key(r, c), text)
        else cells.delete(key(r, c))
        return touch()
      },
      clear_range: async (r0: number, c0: number, r1: number, c1: number) => {
        for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
          for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) cells.delete(key(r, c))
        }
        return touch()
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
        return touch()
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
        return touch()
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
        return touch()
      },
      solve_selection: async (): Promise<SolveResult> => {
        models.set('default', {
          name: 'default',
          sense: 'max',
          objective: 'B2',
          vars: 'A2:A3',
          constraints: 'C2:C4',
        })
        return { ...MOCK_SOLVE }
      },
      solve_model: async (): Promise<SolveResult> => ({ ...MOCK_SOLVE }),
      list_models: async (): Promise<ModelsResult> => ({
        models: [...models.values()].sort((a, b) => a.name.localeCompare(b.name)),
      }),
      save_model: async (name: string, spec: ModelSpec): Promise<SaveModelResult> => {
        const key = String(name ?? '').trim()
        if (!key) return { ok: false, error: 'a model needs a name' }
        if (!spec.objective || !spec.vars || !spec.constraints) {
          return { ok: false, error: 'saved model missing required field' }
        }
        models.set(key, { name: key, ...spec } as SavedModel)
        touch()
        return { ok: true, name: key }
      },
      delete_model: async (name: string) => {
        if (!models.has(name)) return { ok: false, error: `no such model: ${name}` }
        models.delete(name)
        return touch()
      },
      run_model: async (name: string): Promise<SolveResult> => {
        if (!models.has(name)) return { ok: false, error: `no such model: ${name}` }
        return { ...MOCK_SOLVE }
      },
      infer_model_spec: async (
        _r0: number,
        _c0: number,
        _r1: number,
        _c1: number,
        sense: string,
      ): Promise<InferResult> => ({
        ok: true,
        sense,
        objective: 'B2',
        vars: 'A2:A3',
        constraints: 'C2:C4',
      }),
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
