// Typed mirror of the Python `gridcalc.web.Api` bridge. The contract grows one
// phase at a time -- Phase 1 covers workbook-level actions (dimensions, sheets,
// file open/save, undo/redo). Grid, editing, and optimization methods are added
// in later phases alongside the UI that uses them. Every method returns
// JSON-serializable data marshalled across the pywebview js_api boundary.

export interface Dims {
  ncol: number
  nrow: number
  filename: string
  // True when the workbook has changes not yet written to disk.
  dirty: boolean
}

export interface Sheets {
  active: number
  names: string[]
}

// The sheet-management methods return the new tab list along with the usual
// ok/error, so one call both mutates and refreshes the tab strip.
export interface SheetsResult extends Sheets {
  ok?: boolean
  error?: string
}

export interface OkResult {
  ok: boolean
  // Every mutating method reports the workbook's dirty state back, so the
  // client learns it from the call that caused it rather than re-polling.
  dirty?: boolean
}

// Selection summary for the status bar. `count` includes labels; the
// aggregates cover only the numeric cells and are null when there are none.
export interface Stats {
  count: number
  numeric: number
  sum: number | null
  avg: number | null
  min: number | null
  max: number | null
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

// One search hit: zero-based coordinates plus the A1 form the client jumps to.
export interface SearchMatch {
  r: number
  c: number
  ref: string
}

// `total` is the true number of hits even when `matches` was capped, so the
// counter never understates what is on the sheet.
export interface SearchResult {
  matches: SearchMatch[]
  total: number
  truncated: boolean
}

// A named range as the user would write it: `Data = A2:A3`. `sheet` is empty
// for a sheet-agnostic name (one that resolves against the active sheet).
export interface NamedRange {
  name: string
  range: string
  sheet: string
}

export interface NamesResult {
  names: NamedRange[]
}

// Per-column pixel widths for the active sheet, keyed by column index as a
// string (JSON object keys are strings). Columns with no entry use the view's
// own default width.
export interface ColWidths {
  widths: Record<string, number>
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

// A model definition persisted in the workbook (`grid.models`), shared with the
// TUI's `:opt run <name>`. The fields are the *spec strings* the user typed --
// cell refs resolve at solve time, so a model outlives edits to the sheet.
export interface SavedModel {
  name: string
  sense: string
  objective: string
  vars: string
  constraints: string
  bounds?: string
  integers?: string
  binaries?: string
}

export interface ModelsResult {
  models: SavedModel[]
}

export interface SaveModelResult {
  ok: boolean
  name?: string
  error?: string
}

// What `solve_selection` would build from a block, without running it.
export interface InferResult {
  ok: boolean
  error?: string
  sense?: string
  objective?: string
  vars?: string
  constraints?: string
}

export interface PywebviewApi {
  dims(): Promise<Dims>
  sheets(): Promise<Sheets>
  set_active(idx: number): Promise<Sheets>
  search(pattern: string): Promise<SearchResult>
  recalc(): Promise<OkResult>
  list_names(): Promise<NamesResult>
  set_name(name: string, rng: string): Promise<OkResult & { name?: string; error?: string }>
  delete_name(name: string): Promise<OkResult & { error?: string }>
  col_widths(): Promise<ColWidths>
  set_col_width(col: number, px: number): Promise<OkResult & { error?: string }>
  add_sheet(name: string): Promise<SheetsResult>
  delete_sheet(name: string): Promise<SheetsResult>
  rename_sheet(old: string, name: string): Promise<SheetsResult>
  move_sheet(name: string, index: number): Promise<SheetsResult>
  insert_rows(at: number, count: number): Promise<OkResult & { error?: string }>
  insert_cols(at: number, count: number): Promise<OkResult & { error?: string }>
  delete_rows(r0: number, r1: number): Promise<OkResult & { error?: string }>
  delete_cols(c0: number, c1: number): Promise<OkResult & { error?: string }>
  undo(): Promise<OkResult>
  redo(): Promise<OkResult>
  save(path?: string): Promise<SaveResult>
  save_dialog(): Promise<SaveResult>
  open_dialog(): Promise<OpenResult>
  open_file(path: string): Promise<OpenResult>
  viewport(r0: number, c0: number, rows: number, cols: number): Promise<Viewport>
  stats(r0: number, c0: number, r1: number, c1: number): Promise<Stats>
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
  list_models(): Promise<ModelsResult>
  save_model(name: string, spec: ModelSpec): Promise<SaveModelResult>
  delete_model(name: string): Promise<OkResult & { error?: string }>
  run_model(name: string, spec?: ModelSpec): Promise<SolveResult>
  infer_model_spec(
    r0: number,
    c0: number,
    r1: number,
    c1: number,
    sense: string,
  ): Promise<InferResult>
  chart_data(spec: string): Promise<ChartData>
}

declare global {
  interface Window {
    pywebview?: { api: PywebviewApi }
  }
}
