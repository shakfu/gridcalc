import type { PywebviewApi } from './types'

// pywebview injects `window.pywebview.api` and fires `pywebviewready` once the
// bridge is live -- but the timing relative to React mounting is not
// guaranteed, and the api object can appear a tick before its method stubs are
// attached. So "the api object is truthy" is NOT a safe readiness signal (that
// was a Phase 0 bug: a real WebView reached `dims()` before it existed).
// Instead we treat "a known method is callable" as ready, listen for the event,
// AND poll -- covering the event having already fired before we listened, or
// methods attaching just after it. A timeout turns a hang into a diagnostic
// naming whatever the bridge did expose.
function bridgeReady(): boolean {
  return typeof window.pywebview?.api?.dims === 'function'
}

function apiMethodNames(): string[] {
  const a = window.pywebview?.api
  if (!a) return []
  const names = new Set<string>()
  for (const k in a) names.add(k)
  Object.getOwnPropertyNames(a).forEach((n) => names.add(n))
  const proto = Object.getPrototypeOf(a) as object | null
  if (proto) Object.getOwnPropertyNames(proto).forEach((n) => names.add(n))
  names.delete('constructor')
  return [...names]
}

export function whenReady(timeoutMs = 8000): Promise<void> {
  if (bridgeReady()) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const start = Date.now()
    let timer: ReturnType<typeof setInterval>
    const cleanup = () => {
      clearInterval(timer)
      window.removeEventListener('pywebviewready', check)
    }
    const check = () => {
      if (bridgeReady()) {
        cleanup()
        resolve()
      } else if (Date.now() - start > timeoutMs) {
        cleanup()
        reject(
          new Error(
            `pywebview bridge not ready after ${timeoutMs}ms; ` +
              `window.pywebview=${!!window.pywebview}, ` +
              `api methods=${JSON.stringify(apiMethodNames())}`,
          ),
        )
      }
    }
    timer = setInterval(check, 25)
    window.addEventListener('pywebviewready', check)
  })
}

function api(): PywebviewApi {
  const a = window.pywebview?.api
  if (!a) throw new Error('pywebview bridge is not available')
  return a
}

// The typed client the React app calls. Each method is a thin, awaitable
// forward to the Python `Api`; call sites never touch `window.pywebview`.
export const bridge: PywebviewApi = {
  dims: () => api().dims(),
  sheets: () => api().sheets(),
  set_active: (idx) => api().set_active(idx),
  search: (pattern) => api().search(pattern),
  list_commands: () => api().list_commands(),
  run_command: (name, args, selection) => api().run_command(name, args, selection),
  col_widths: () => api().col_widths(),
  set_col_width: (col, px) => api().set_col_width(col, px),
  add_sheet: (name) => api().add_sheet(name),
  delete_sheet: (name) => api().delete_sheet(name),
  rename_sheet: (old, name) => api().rename_sheet(old, name),
  move_sheet: (name, index) => api().move_sheet(name, index),
  undo: () => api().undo(),
  redo: () => api().redo(),
  save: (path) => api().save(path),
  save_dialog: () => api().save_dialog(),
  open_dialog: () => api().open_dialog(),
  open_file: (path) => api().open_file(path),
  viewport: (r0, c0, rows, cols) => api().viewport(r0, c0, rows, cols),
  stats: (r0, c0, r1, c1) => api().stats(r0, c0, r1, c1),
  cell_source: (r, c) => api().cell_source(r, c),
  set_cell: (r, c, text) => api().set_cell(r, c, text),
  clear_range: (r0, c0, r1, c1) => api().clear_range(r0, c0, r1, c1),
  set_format: (r0, c0, r1, c1, spec) => api().set_format(r0, c0, r1, c1, spec),
  set_global_format: (fmt) => api().set_global_format(fmt),
  copy: (r0, c0, r1, c1, cut) => api().copy(r0, c0, r1, c1, cut),
  paste: (r, c) => api().paste(r, c),
  paste_text: (r, c, text) => api().paste_text(r, c, text),
  fill: (r0, c0, r1, c1, direction) => api().fill(r0, c0, r1, c1, direction),
  solve_selection: (r0, c0, r1, c1, sense) => api().solve_selection(r0, c0, r1, c1, sense),
  solve_model: (spec) => api().solve_model(spec),
  goal_seek: (formula_ref, target, var_ref, lo, hi) =>
    api().goal_seek(formula_ref, target, var_ref, lo, hi),
  opt_sweep: (spec) => api().opt_sweep(spec),
  list_models: () => api().list_models(),
  save_model: (name, spec) => api().save_model(name, spec),
  delete_model: (name) => api().delete_model(name),
  run_model: (name, spec) => api().run_model(name, spec),
  infer_model_spec: (r0, c0, r1, c1, sense) => api().infer_model_spec(r0, c0, r1, c1, sense),
  chart_data: (spec) => api().chart_data(spec),
}
