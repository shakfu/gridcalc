import type { Dims, OpenResult, SaveResult, Sheets, Viewport, ViewportCell } from './types'

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
            if (text) out.push({ r, c, text, align: isNumeric(text) ? 'r' : 'l' })
          }
        }
        return { r0, c0, rows, cols, cells: out }
      },
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
    },
  }
}
