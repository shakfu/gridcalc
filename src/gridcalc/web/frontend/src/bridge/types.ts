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
  copy(r0: number, c0: number, r1: number, c1: number, cut: boolean): Promise<CopyResult>
  paste(r: number, c: number): Promise<OkResult>
  paste_text(r: number, c: number, text: string): Promise<OkResult>
  fill(r0: number, c0: number, r1: number, c1: number, direction: 'down' | 'right'): Promise<OkResult>
}

declare global {
  interface Window {
    pywebview?: { api: PywebviewApi }
  }
}
