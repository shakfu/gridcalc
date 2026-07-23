// Typed mirror of the Python `gridcalc.web.Api` bridge. The contract grows one
// phase at a time -- Phase 1 covers workbook-level actions (dimensions, sheets,
// file open/save, undo/redo). Grid, editing, and optimization methods are added
// in later phases alongside the UI that uses them. Every method returns
// JSON-serializable data marshalled across the pywebview js_api boundary.

export interface Dims {
  ncol: number
  nrow: number
  filename: string
}

export interface Sheets {
  active: number
  names: string[]
}

export interface OkResult {
  ok: boolean
}

export interface SaveResult {
  ok: boolean
  path?: string
  needs_path?: boolean
  cancelled?: boolean
  error?: string
}

export interface OpenResult {
  ok: boolean
  filename?: string
  cancelled?: boolean
  error?: string
}

export interface ViewportCell {
  r: number
  c: number
  text: string
  align: 'l' | 'r'
  bold?: boolean
  italic?: boolean
  underline?: boolean
}

export interface Viewport {
  r0: number
  c0: number
  rows: number
  cols: number
  cells: ViewportCell[]
}

export interface CopyResult {
  ok: boolean
  tsv?: string
}

// --- optimization ---

export interface VarSensitivity {
  cell: string
  value: number
  reduced_cost: number
  obj_coef: number
  obj_from: number | null
  obj_till: number | null
}

export interface ConSensitivity {
  cell: string
  shadow_price: number
  rhs: number
  activity: number
  slack: number
  binding: boolean
  rhs_from: number | null
  rhs_till: number | null
}

export interface Sensitivity {
  variables: VarSensitivity[]
  constraints: ConSensitivity[]
}

export interface SolveResult {
  ok: boolean
  error?: string
  status?: string
  optimal?: boolean
  objective?: number | null
  values?: Record<string, number>
  applied?: boolean
  quadratic?: boolean
  sensitivity?: Sensitivity
  conflict?: string[]
  unbounded?: string[]
}

export interface GoalResult {
  ok: boolean
  error?: string
  converged?: boolean
  iterations?: number
  var_value?: number
  formula_value?: number
  residual?: number
  applied?: boolean
}

export interface SweepPoint {
  rhs: number
  status: string
  objective: number | null
  shadow_price: number | null
  delta: number | null
  breakpoint: boolean
}

export interface SweepResult {
  ok: boolean
  error?: string
  points?: SweepPoint[]
}

export interface ChartSeries {
  name: string
  values: (number | null)[]
}

export interface ChartData {
  title?: string
  labels?: string[]
  series?: ChartSeries[]
  error?: string
}

export type ModelSpec = Record<string, unknown>

export interface PywebviewApi {
  dims(): Promise<Dims>
  sheets(): Promise<Sheets>
  set_active(idx: number): Promise<Sheets>
  undo(): Promise<OkResult>
  redo(): Promise<OkResult>
  save(path?: string): Promise<SaveResult>
  save_dialog(): Promise<SaveResult>
  open_dialog(): Promise<OpenResult>
  open_file(path: string): Promise<OpenResult>
  viewport(r0: number, c0: number, rows: number, cols: number): Promise<Viewport>
  cell_source(r: number, c: number): Promise<string>
  set_cell(r: number, c: number, text: string): Promise<OkResult>
  clear_range(r0: number, c0: number, r1: number, c1: number): Promise<OkResult>
  set_format(r0: number, c0: number, r1: number, c1: number, spec: string): Promise<OkResult>
  set_global_format(fmt: string): Promise<OkResult>
  copy(r0: number, c0: number, r1: number, c1: number, cut: boolean): Promise<CopyResult>
  paste(r: number, c: number): Promise<OkResult>
  paste_text(r: number, c: number, text: string): Promise<OkResult>
  fill(r0: number, c0: number, r1: number, c1: number, direction: 'down' | 'right'): Promise<OkResult>
  solve_selection(r0: number, c0: number, r1: number, c1: number, sense: string): Promise<SolveResult>
  solve_model(spec: ModelSpec): Promise<SolveResult>
  goal_seek(
    formula_ref: string,
    target: number,
    var_ref: string,
    lo?: number | null,
    hi?: number | null,
  ): Promise<GoalResult>
  opt_sweep(spec: ModelSpec): Promise<SweepResult>
  chart_data(spec: string): Promise<ChartData>
}

declare global {
  interface Window {
    pywebview?: { api: PywebviewApi }
  }
}
