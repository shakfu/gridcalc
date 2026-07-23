import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from 'react'
import { bridge } from '../bridge/api'
import type { Viewport } from '../bridge/types'
import {
  CH,
  CW,
  GW,
  PAD,
  cellRef,
  clamp,
  colName,
  rangeRef,
  selRect,
  type Cursor,
  type Selection,
} from '../lib/grid'

interface GridProps {
  ncol: number
  nrow: number
  // Bumps when an out-of-grid action (undo/redo, formatting) changes cells, so
  // the grid refetches its viewport without losing scroll/cursor.
  revision: number
  onSelectionChange?: (sel: Selection) => void
}

const MIN_COL_W = 28

// The virtualized spreadsheet grid. Only cells inside the scrolled viewport
// enter the DOM (fetched from the engine on scroll). Column widths are
// variable (drag a header's right edge to resize); row height is uniform.
export function Grid({ ncol, nrow, revision, onSelectionChange }: GridProps) {
  const scrollEl = useRef<HTMLDivElement>(null)
  const editorEl = useRef<HTMLInputElement>(null)
  const scrollPos = useRef({ top: 0, left: 0 })

  const [scroll, setScroll] = useState({ top: 0, left: 0 })
  const [view, setView] = useState<Viewport | null>(null)
  const [cur, setCur] = useState<Cursor>({ r: 0, c: 0 })
  const [anchor, setAnchor] = useState<Cursor>({ r: 0, c: 0 })
  const [editing, setEditing] = useState<Cursor | null>(null)
  const [editValue, setEditValue] = useState('')
  const [source, setSource] = useState('')
  const [colWidths, setColWidths] = useState<Map<number, number>>(new Map())

  // Refs mirroring state so window-level and async handlers read current values.
  const curRef = useRef(cur)
  curRef.current = cur
  const anchorRef = useRef(anchor)
  anchorRef.current = anchor
  const editValueRef = useRef(editValue)
  editValueRef.current = editValue
  const colWidthsRef = useRef(colWidths)
  colWidthsRef.current = colWidths

  // Prefix sum of column left-edges: xs[c] is column c's left x (xs[0] = GW),
  // xs[ncol] the right edge of the sheet. Recomputed only when widths change.
  const xs = useMemo(() => {
    const arr = new Array<number>(ncol + 1)
    arr[0] = GW
    for (let c = 0; c < ncol; c++) arr[c + 1] = arr[c] + (colWidths.get(c) ?? CW)
    return arr
  }, [colWidths, ncol])
  const xsRef = useRef(xs)
  xsRef.current = xs

  const colX = (c: number) => xs[c]
  const colW = (c: number) => xs[c + 1] - xs[c]

  // Column index at a canvas x-pixel (binary search over xs). Reads the ref so
  // callbacks need not depend on the widths.
  const colAtX = useCallback((px: number) => {
    const a = xsRef.current
    if (px < a[0]) return 0
    let lo = 0
    let hi = a.length - 2
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (a[mid] <= px) lo = mid
      else hi = mid - 1
    }
    return lo
  }, [])

  // --- viewport fetch, coalesced ---
  const busy = useRef(false)
  const dirty = useRef(false)
  const doFetch = useCallback(async () => {
    const el = scrollEl.current
    if (!el) return
    const { top, left } = scrollPos.current
    const c0 = Math.max(0, colAtX(left) - PAD)
    const r0 = Math.max(0, Math.floor((top - CH) / CH) - PAD)
    const rows = Math.ceil(el.clientHeight / CH) + 2 * PAD + 1
    const c1 = Math.min(ncol, colAtX(left + el.clientWidth) + PAD + 1)
    const r1 = Math.min(nrow, r0 + rows)
    setView(await bridge.viewport(r0, c0, r1 - r0, c1 - c0))
  }, [ncol, nrow, colAtX])

  const refresh = useCallback(async () => {
    dirty.current = true
    if (busy.current) return
    busy.current = true
    try {
      while (dirty.current) {
        dirty.current = false
        await doFetch()
      }
    } finally {
      busy.current = false
    }
  }, [doFetch])

  const loadSource = useCallback(async (r: number, c: number) => {
    setSource(await bridge.cell_source(r, c))
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh, revision])

  useEffect(() => {
    scrollEl.current?.focus()
  }, [])

  useEffect(() => {
    if (editing) return
    let alive = true
    void bridge.cell_source(cur.r, cur.c).then((s) => alive && setSource(s))
    return () => {
      alive = false
    }
  }, [cur, editing])

  useEffect(() => {
    if (!onSelectionChange) return
    const s = selRect(cur, anchor)
    onSelectionChange({ ...s, ref: rangeRef(cur, anchor), active: cellRef(cur.r, cur.c) })
  }, [cur, anchor, onSelectionChange])

  const onScroll = () => {
    const el = scrollEl.current
    if (!el) return
    scrollPos.current = { top: el.scrollTop, left: el.scrollLeft }
    setScroll(scrollPos.current)
    void refresh()
  }

  const ensureVisible = useCallback((r: number, c: number) => {
    const el = scrollEl.current
    if (!el) return
    const a = xsRef.current
    const l = a[c]
    const w = a[c + 1] - a[c]
    const t = CH + r * CH
    if (l < el.scrollLeft + GW) el.scrollLeft = l - GW
    else if (l + w > el.scrollLeft + el.clientWidth) el.scrollLeft = l + w - el.clientWidth
    if (t < el.scrollTop + CH) el.scrollTop = t - CH
    else if (t + CH > el.scrollTop + el.clientHeight) el.scrollTop = t + CH - el.clientHeight
  }, [])

  const moveCursor = useCallback(
    (r: number, c: number, extend: boolean) => {
      const nr = clamp(r, nrow)
      const nc = clamp(c, ncol)
      setCur({ r: nr, c: nc })
      if (!extend) setAnchor({ r: nr, c: nc })
      ensureVisible(nr, nc)
    },
    [ncol, nrow, ensureVisible],
  )

  // --- editing + formula point mode ---
  const pointStart = useRef<number | null>(null)
  const pointLen = useRef(0)
  const pointAnchor = useRef<Cursor | null>(null)
  const pointing = useRef(false)
  const pendingCaret = useRef<number | null>(null)

  const resetPoint = () => {
    pointStart.current = null
    pointLen.current = 0
    pointAnchor.current = null
    pointing.current = false
  }

  const beginEdit = useCallback(async (r: number, c: number, initial?: string) => {
    setCur({ r, c })
    setAnchor({ r, c })
    resetPoint()
    const src = initial !== undefined ? initial : await bridge.cell_source(r, c)
    setEditValue(src)
    setEditing({ r, c })
  }, [])

  const commit = useCallback(
    async (move: 'down' | 'right' | 'none') => {
      const cell = editing
      if (!cell) return
      setEditing(null)
      resetPoint()
      await bridge.set_cell(cell.r, cell.c, editValueRef.current)
      await refresh()
      scrollEl.current?.focus()
      if (move === 'down') moveCursor(cell.r + 1, cell.c, false)
      else if (move === 'right') moveCursor(cell.r, cell.c + 1, false)
    },
    [editing, refresh, moveCursor],
  )

  const cancelEdit = useCallback(() => {
    setEditing(null)
    resetPoint()
    scrollEl.current?.focus()
  }, [])

  useEffect(() => {
    if (pendingCaret.current !== null && editorEl.current) {
      const caret = pendingCaret.current
      editorEl.current.setSelectionRange(caret, caret)
      editorEl.current.focus()
      pendingCaret.current = null
    }
  }, [editValue])

  const inFormula = () => editing !== null && editValueRef.current.startsWith('=')

  const insertPointRef = (text: string) => {
    const el = editorEl.current
    if (!el) return
    if (pointStart.current === null) {
      pointStart.current = el.selectionStart ?? el.value.length
      pointLen.current = 0
    }
    const start = pointStart.current
    const v = editValueRef.current
    setEditValue(v.slice(0, start) + text + v.slice(start + pointLen.current))
    pointLen.current = text.length
    pendingCaret.current = start + pointLen.current
  }

  const pointAt = (hit: Cursor, extend: boolean) => {
    if (extend && pointAnchor.current) {
      insertPointRef(rangeRef(pointAnchor.current, hit))
    } else {
      pointAnchor.current = { ...hit }
      insertPointRef(rangeRef(hit, hit))
    }
    setCur({ ...hit })
    setAnchor({ ...pointAnchor.current })
  }

  // --- clipboard + fill ---
  const lastCopyTsv = useRef<string | null>(null)

  const copySelection = useCallback(async (cut: boolean) => {
    const s = selRect(curRef.current, anchorRef.current)
    const res = await bridge.copy(s.r0, s.c0, s.r1, s.c1, cut)
    lastCopyTsv.current = res.tsv ?? null
    try {
      await navigator.clipboard.writeText(res.tsv ?? '')
    } catch {
      /* no OS clipboard */
    }
  }, [])

  const pasteAt = useCallback(async () => {
    let ext = ''
    try {
      ext = await navigator.clipboard.readText()
    } catch {
      /* blocked */
    }
    const { r, c } = curRef.current
    if (ext && ext !== lastCopyTsv.current) await bridge.paste_text(r, c, ext)
    else await bridge.paste(r, c)
    await refresh()
    await loadSource(r, c)
  }, [refresh, loadSource])

  const fillSelection = useCallback(
    async (direction: 'down' | 'right') => {
      const s = selRect(curRef.current, anchorRef.current)
      await bridge.fill(s.r0, s.c0, s.r1, s.c1, direction)
      await refresh()
    },
    [refresh],
  )

  // --- mouse ---
  const cellAt = useCallback(
    (clientX: number, clientY: number): Cursor | null => {
      const el = scrollEl.current
      if (!el) return null
      const rect = el.getBoundingClientRect()
      const px = clientX - rect.left + el.scrollLeft
      if (px < GW) return null // the gutter, not a cell
      const c = colAtX(px)
      const r = Math.floor((clientY - rect.top + el.scrollTop - CH) / CH)
      if (c < 0 || r < 0 || c >= ncol || r >= nrow) return null
      return { r, c }
    },
    [colAtX, ncol, nrow],
  )

  const dragging = useRef(false)
  const fillFrom = useRef({ r0: 0, c0: 0, r1: 0, c1: 0 })
  const filling = useRef(false)
  const resizing = useRef<{ col: number; startX: number; startW: number } | null>(null)

  const startResize = useCallback((e: MouseEvent, col: number) => {
    e.preventDefault()
    e.stopPropagation()
    resizing.current = { col, startX: e.clientX, startW: colWidthsRef.current.get(col) ?? CW }
  }, [])

  // Column resize (and drags that end outside the grid) resolve at the window.
  useEffect(() => {
    const onMove = (e: globalThis.MouseEvent) => {
      const rz = resizing.current
      if (!rz) return
      const w = Math.max(MIN_COL_W, rz.startW + (e.clientX - rz.startX))
      setColWidths((prev) => new Map(prev).set(rz.col, w))
    }
    const onUp = () => {
      if (filling.current) {
        filling.current = false
        const s = selRect(curRef.current, anchorRef.current)
        const ff = fillFrom.current
        const dir = s.r1 > ff.r1 ? 'down' : s.c1 > ff.c1 ? 'right' : null
        if (dir) void bridge.fill(s.r0, s.c0, s.r1, s.c1, dir).then(refresh)
      }
      if (resizing.current) {
        resizing.current = null
        void refresh() // the visible column range may have changed
      }
      dragging.current = false
      pointing.current = false
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [refresh])

  const onMouseDown = (e: MouseEvent) => {
    const hit = cellAt(e.clientX, e.clientY)
    if (!hit) return
    if (inFormula()) {
      e.preventDefault()
      pointAt(hit, e.shiftKey)
      pointing.current = true
      return
    }
    if (editing) void commit('none')
    moveCursor(hit.r, hit.c, e.shiftKey)
    dragging.current = true
  }

  const onMouseMove = (e: MouseEvent) => {
    if (e.buttons !== 1 || resizing.current) return
    const hit = cellAt(e.clientX, e.clientY)
    if (!hit) return
    if (filling.current) {
      const ff = fillFrom.current
      const dR = hit.r - ff.r1
      const dC = hit.c - ff.c1
      setAnchor({ r: ff.r0, c: ff.c0 })
      if (Math.abs(dR) >= Math.abs(dC)) setCur({ r: Math.max(ff.r0, hit.r), c: ff.c1 })
      else setCur({ r: ff.r1, c: Math.max(ff.c0, hit.c) })
      return
    }
    if (pointing.current) {
      pointAt(hit, true)
      return
    }
    if (dragging.current) moveCursor(hit.r, hit.c, true)
  }

  const onDoubleClick = (e: MouseEvent) => {
    const hit = cellAt(e.clientX, e.clientY)
    if (hit) void beginEdit(hit.r, hit.c)
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (editing) return
    if (e.metaKey || e.ctrlKey) {
      const k = e.key.toLowerCase()
      if (k === 'c' || k === 'x') {
        e.preventDefault()
        void copySelection(k === 'x')
      } else if (k === 'v') {
        e.preventDefault()
        void pasteAt()
      } else if (k === 'd') {
        e.preventDefault()
        void fillSelection('down')
      } else if (k === 'r') {
        e.preventDefault()
        void fillSelection('right')
      }
      return
    }
    if (e.altKey) return
    const ext = e.shiftKey
    switch (e.key) {
      case 'ArrowUp':
        moveCursor(cur.r - 1, cur.c, ext)
        break
      case 'ArrowDown':
        moveCursor(cur.r + 1, cur.c, ext)
        break
      case 'ArrowLeft':
        moveCursor(cur.r, cur.c - 1, ext)
        break
      case 'ArrowRight':
        moveCursor(cur.r, cur.c + 1, ext)
        break
      case 'Tab':
        moveCursor(cur.r, cur.c + (ext ? -1 : 1), false)
        break
      case 'Home':
        moveCursor(cur.r, 0, ext)
        break
      case 'Enter':
      case 'F2':
        void beginEdit(cur.r, cur.c)
        break
      case 'Delete':
      case 'Backspace': {
        const s = selRect(cur, anchor)
        void bridge.clear_range(s.r0, s.c0, s.r1, s.c1).then(async () => {
          await refresh()
          await loadSource(cur.r, cur.c)
        })
        break
      }
      default:
        if (e.key.length === 1) {
          void beginEdit(cur.r, cur.c, e.key)
        } else {
          return
        }
    }
    e.preventDefault()
  }

  const sel = selRect(cur, anchor)
  const single = sel.r0 === sel.r1 && sel.c0 === sel.c1

  const cellLayer = useMemo(() => {
    if (!view) return null
    return view.cells.map((cell) => (
      <div
        key={`${cell.r},${cell.c}`}
        className={
          'cell' +
          (cell.align === 'r' ? ' num' : '') +
          (cell.bold ? ' b' : '') +
          (cell.italic ? ' i' : '') +
          (cell.underline ? ' u' : '')
        }
        style={{ left: xs[cell.c], top: CH + cell.r * CH, width: xs[cell.c + 1] - xs[cell.c] }}
      >
        {cell.text}
      </div>
    ))
  }, [view, xs])

  const headerLayer = useMemo(() => {
    if (!view) return null
    const items = []
    for (let c = view.c0; c < view.c0 + view.cols; c++) {
      items.push(
        <div key={c} className="hdr" style={{ left: xs[c], width: xs[c + 1] - xs[c] }}>
          {colName(c)}
        </div>,
      )
      items.push(
        <div
          key={`rz${c}`}
          className="col-resize"
          style={{ left: xs[c + 1] - 3 }}
          onMouseDown={(e) => startResize(e, c)}
        />,
      )
    }
    return items
  }, [view, xs, startResize])

  // Vertical gridlines at the real column boundaries so they track resizing
  // (the horizontal lines come from the canvas background, since rows are
  // uniform).
  const vlineLayer = useMemo(() => {
    if (!view) return null
    const h = nrow * CH
    const items = []
    for (let c = view.c0; c <= view.c0 + view.cols; c++) {
      items.push(<div key={c} className="vline" style={{ left: xs[c], height: h }} />)
    }
    return items
  }, [view, xs, nrow])

  const gutterLayer = useMemo(() => {
    if (!view) return null
    const items = []
    for (let r = view.r0; r < view.r0 + view.rows; r++) {
      items.push(
        <div key={r} className="gut" style={{ top: CH + r * CH }}>
          {r + 1}
        </div>,
      )
    }
    return items
  }, [view])

  return (
    <div className="grid">
      <div className="formula-bar">
        <span className="name-box">{cellRef(cur.r, cur.c)}</span>
        <span className="formula-src">{source}</span>
      </div>
      <div
        className="grid-scroll"
        ref={scrollEl}
        tabIndex={0}
        onScroll={onScroll}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
      >
        <div className="grid-canvas" style={{ width: xs[ncol], height: CH + nrow * CH }}>
          <div className="vline-layer">{vlineLayer}</div>
          <div className="cell-layer">{cellLayer}</div>

          {!single && (
            <div
              className="sel-rect"
              style={{
                left: colX(sel.c0),
                top: CH + sel.r0 * CH,
                width: xs[sel.c1 + 1] - xs[sel.c0],
                height: (sel.r1 - sel.r0 + 1) * CH,
              }}
            />
          )}
          <div
            className="cursor"
            style={{ left: colX(cur.c), top: CH + cur.r * CH, width: colW(cur.c), height: CH }}
          />
          {!editing && (
            <div
              className="fill-handle"
              style={{ left: xs[sel.c1 + 1] - 4, top: CH + (sel.r1 + 1) * CH - 4 }}
              onMouseDown={(e) => {
                e.preventDefault()
                e.stopPropagation()
                fillFrom.current = selRect(cur, anchor)
                filling.current = true
              }}
            />
          )}

          <div className="hdr-layer" style={{ top: scroll.top }}>
            {headerLayer}
          </div>
          <div className="gut-layer" style={{ left: scroll.left }}>
            {gutterLayer}
          </div>
          <div className="corner" style={{ top: scroll.top, left: scroll.left }} />

          {editing && (
            <input
              ref={editorEl}
              className="cell-editor"
              style={{ left: colX(editing.c), top: CH + editing.r * CH, width: colW(editing.c) }}
              value={editValue}
              onChange={(e) => {
                setEditValue(e.target.value)
                resetPoint()
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void commit('down')
                } else if (e.key === 'Tab') {
                  e.preventDefault()
                  void commit('right')
                } else if (e.key === 'Escape') {
                  e.preventDefault()
                  cancelEdit()
                }
                e.stopPropagation()
              }}
              autoFocus
            />
          )}
        </div>
      </div>
    </div>
  )
}
