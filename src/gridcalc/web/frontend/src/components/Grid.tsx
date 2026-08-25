import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type Ref,
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
  parseRef,
  rangeRef,
  selRect,
  type CellAnnotation,
  type Cursor,
  type Selection,
  type SheetView,
} from '../lib/grid'
import { failureOf } from '../bridge/result'

// The grid's imperative command set, handed up to the app so the menubar,
// toolbar, and keyboard all drive one implementation. Cursor and selection
// stay owned by the grid (they change on every mouse move, and lifting them
// would re-render the whole shell); commands are how everything else acts on
// them.
export interface GridHandle {
  copy(): void
  cut(): void
  paste(): void
  clear(): void
  fillDown(): void
  fillRight(): void
  edit(): void
  goto(ref: string): boolean
  focus(): void
}

interface GridProps {
  ncol: number
  nrow: number
  // Bumps when an out-of-grid action (undo/redo, formatting) changes cells, so
  // the grid refetches its viewport without losing scroll/cursor.
  revision: number
  onSelectionChange?: (sel: Selection) => void
  // Solver output painted onto the sheet, keyed by A1 reference.
  annotations?: Record<string, CellAnnotation>
  // A bridge call failed; the app owns the user-visible channel for saying so.
  onError?: (msg: string) => void
  // A mutation succeeded, so the workbook now has unsaved changes.
  onMutate?: () => void
  // Where this sheet was last left. Read once, at mount; `null` starts at A1.
  initialView?: SheetView | null
  // Handed the view state as the grid goes away, for the app to stash against
  // the sheet this instance was showing.
  onViewChange?: (view: SheetView) => void
  ref?: Ref<GridHandle>
}

const MIN_COL_W = 28

// A restored cursor is clamped to the sheet rather than trusted: it was
// recorded against a sheet of the same dimensions, but nothing guarantees the
// one being entered has them.
function restoreCursor(p: Cursor | undefined, nrow: number, ncol: number): Cursor {
  return p ? { r: clamp(p.r, nrow), c: clamp(p.c, ncol) } : { r: 0, c: 0 }
}

// The virtualized spreadsheet grid. Only cells inside the scrolled viewport
// enter the DOM (fetched from the engine on scroll). Column widths are
// variable (drag a header's right edge to resize); row height is uniform.
export function Grid({
  ncol,
  nrow,
  revision,
  onSelectionChange,
  annotations,
  onError,
  onMutate,
  initialView,
  onViewChange,
  ref,
}: GridProps) {
  const scrollEl = useRef<HTMLDivElement>(null)
  const editorEl = useRef<HTMLInputElement>(null)
  const barEl = useRef<HTMLInputElement>(null)

  // Mount is exactly when the incoming sheet's state is known -- the app
  // remounts this component per sheet -- so the prop is read once and later
  // changes are deliberately ignored. Same reasoning as the column widths
  // fetched below.
  const start = useRef(initialView ?? null)
  const scrollPos = useRef({ top: start.current?.top ?? 0, left: start.current?.left ?? 0 })

  const [scroll, setScroll] = useState(scrollPos.current)
  const [view, setView] = useState<Viewport | null>(null)
  const [cur, setCur] = useState<Cursor>(() => restoreCursor(start.current?.cur, nrow, ncol))
  const [anchor, setAnchor] = useState<Cursor>(() =>
    restoreCursor(start.current?.anchor, nrow, ncol),
  )
  const [editing, setEditing] = useState<Cursor | null>(null)
  // An edit started from the formula bar keeps its caret there; the in-cell
  // editor would otherwise autofocus and steal it mid-keystroke.
  const [editInBar, setEditInBar] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [source, setSource] = useState('')
  const [nameDraft, setNameDraft] = useState<string | null>(null)
  const [colWidths, setColWidths] = useState<Map<number, number>>(new Map())

  // Refs mirroring state so window-level and async handlers read current values.
  const curRef = useRef(cur)
  curRef.current = cur
  const anchorRef = useRef(anchor)
  anchorRef.current = anchor

  // Cursor/anchor moves write through to the refs immediately rather than
  // waiting for the re-render. Otherwise two commands issued in one tick
  // (`goto('A4')` then `copy()`) would have the second act on the old cursor.
  const putCur = useCallback((p: Cursor) => {
    curRef.current = p
    setCur(p)
  }, [])
  const putAnchor = useCallback((p: Cursor) => {
    anchorRef.current = p
    setAnchor(p)
  }, [])
  const editValueRef = useRef(editValue)
  editValueRef.current = editValue
  const colWidthsRef = useRef(colWidths)
  colWidthsRef.current = colWidths
  const editInBarRef = useRef(editInBar)
  editInBarRef.current = editInBar
  const onErrorRef = useRef(onError)
  onErrorRef.current = onError
  const onMutateRef = useRef(onMutate)
  onMutateRef.current = onMutate
  const onViewChangeRef = useRef(onViewChange)
  onViewChangeRef.current = onViewChange

  // A bridge call is a marshalled Python call and can reject. Unguarded, the
  // rejection is swallowed and the user is left looking at a silently stale
  // grid -- so every call routes failures to the app's status channel.
  const guard = useCallback(async <T,>(what: string, fn: () => Promise<T>): Promise<T | null> => {
    try {
      return await fn()
    } catch (e) {
      onErrorRef.current?.(`${what}: ${e instanceof Error ? e.message : String(e)}`)
      return null
    }
  }, [])

  // Run a mutating bridge call, then tell the app the workbook changed.
  // A call that resolves can still be a refusal (`{ok: false}`) -- an empty
  // clipboard, input the engine will not accept -- and announcing a mutation
  // for one left the sheet marked dirty with nothing changed. A refusal is
  // reported like a rejection and returns null, so callers testing `!== null`
  // stay correct.
  const mutate = useCallback(
    async <T,>(what: string, fn: () => Promise<T>): Promise<T | null> => {
      const res = await guard(what, fn)
      if (res === null) return null
      const why = failureOf(res)
      if (why !== null) {
        onErrorRef.current?.(`${what}: ${why}`)
        return null
      }
      onMutateRef.current?.()
      return res
    },
    [guard],
  )

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
    const vp = await guard('viewport', () => bridge.viewport(r0, c0, r1 - r0, c1 - c0))
    if (vp) setView(vp)
  }, [ncol, nrow, colAtX, guard])

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

  const loadSource = useCallback(
    async (r: number, c: number) => {
      const s = await guard('cell', () => bridge.cell_source(r, c))
      if (s !== null) setSource(s)
    },
    [guard],
  )

  useEffect(() => {
    void refresh()
  }, [refresh, revision])

  // Put the scroll offset back before paint, and before the focus below: the
  // browser scrolls a focused container into view, which on a fresh element
  // would undo the restore. The first viewport fetch already reads the right
  // region, since `scrollPos` was seeded from the same state.
  useLayoutEffect(() => {
    const el = scrollEl.current
    const v = start.current
    if (!el || !v) return
    el.scrollTop = v.top
    el.scrollLeft = v.left
  }, [])

  useEffect(() => {
    scrollEl.current?.focus()
  }, [])

  // Report where the sheet was left as this instance goes away. Switching
  // sheets remounts the grid, so without this the cursor, the selection and
  // the scroll offset would reset to A1 on every tab switch. The callback is
  // read from a ref, which still holds the closure from this instance's last
  // render -- and so names the sheet it was actually showing, not the one
  // being switched to.
  useEffect(
    () => () => {
      onViewChangeRef.current?.({
        cur: curRef.current,
        anchor: anchorRef.current,
        top: scrollPos.current.top,
        left: scrollPos.current.left,
      })
    },
    [],
  )

  // Column widths are per-sheet workbook state, so they are fetched here
  // rather than passed down: the app remounts this component per sheet, which
  // makes mount exactly the moment the right set is known.
  useEffect(() => {
    let alive = true
    void guard('column widths', () => bridge.col_widths()).then((r) => {
      if (!alive || !r) return
      const m = new Map<number, number>()
      for (const [c, w] of Object.entries(r.widths)) m.set(Number(c), w)
      if (m.size) setColWidths(m)
    })
    return () => {
      alive = false
    }
  }, [guard])

  useEffect(() => {
    if (editing) return
    void loadSource(cur.r, cur.c)
  }, [cur, editing, loadSource])

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
      putCur({ r: nr, c: nc })
      if (!extend) putAnchor({ r: nr, c: nc })
      ensureVisible(nr, nc)
    },
    [ncol, nrow, ensureVisible, putCur, putAnchor],
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

  const beginEdit = useCallback(
    async (r: number, c: number, initial?: string, inBar = false) => {
      putCur({ r, c })
      putAnchor({ r, c })
      resetPoint()
      let src = initial
      if (src === undefined) src = (await guard('cell', () => bridge.cell_source(r, c))) ?? ''
      setEditValue(src)
      setEditInBar(inBar)
      setEditing({ r, c })
    },
    [guard, putCur, putAnchor],
  )

  const commit = useCallback(
    async (move: 'down' | 'right' | 'none') => {
      const cell = editing
      if (!cell) return
      setEditing(null)
      setEditInBar(false)
      resetPoint()
      await mutate('write cell', () => bridge.set_cell(cell.r, cell.c, editValueRef.current))
      await refresh()
      scrollEl.current?.focus()
      if (move === 'down') moveCursor(cell.r + 1, cell.c, false)
      else if (move === 'right') moveCursor(cell.r, cell.c + 1, false)
      else void loadSource(cell.r, cell.c)
    },
    [editing, refresh, moveCursor, mutate, loadSource],
  )

  const cancelEdit = useCallback(() => {
    setEditing(null)
    setEditInBar(false)
    resetPoint()
    scrollEl.current?.focus()
  }, [])

  // Whichever input the current edit session lives in -- the in-cell editor or
  // the formula bar. Point mode writes into it either way.
  const activeEditor = () => (editInBarRef.current ? barEl.current : editorEl.current)

  useEffect(() => {
    const el = activeEditor()
    if (pendingCaret.current !== null && el) {
      const caret = pendingCaret.current
      el.setSelectionRange(caret, caret)
      el.focus()
      pendingCaret.current = null
    }
  }, [editValue])

  const inFormula = () => editing !== null && editValueRef.current.startsWith('=')

  const insertPointRef = (text: string) => {
    const el = activeEditor()
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
    putCur({ ...hit })
    putAnchor({ ...pointAnchor.current })
  }

  // --- clipboard + fill ---
  const lastCopyTsv = useRef<string | null>(null)

  const copySelection = useCallback(
    async (cut: boolean) => {
      const s = selRect(curRef.current, anchorRef.current)
      // A cut mutates (it clears the source on paste), a copy does not.
      const run = cut ? mutate : guard
      const res = await run(cut ? 'cut' : 'copy', () =>
        bridge.copy(s.r0, s.c0, s.r1, s.c1, cut),
      )
      if (!res) return
      lastCopyTsv.current = res.tsv ?? null
      try {
        await navigator.clipboard.writeText(res.tsv ?? '')
      } catch {
        /* no OS clipboard */
      }
      if (cut) await refresh()
    },
    [guard, mutate, refresh],
  )

  const pasteAt = useCallback(async () => {
    let ext = ''
    try {
      ext = await navigator.clipboard.readText()
    } catch {
      /* blocked */
    }
    const { r, c } = curRef.current
    // Clipboard text that is not our own last copy came from another app, so
    // it pastes verbatim; otherwise the internal buffer preserves formulas.
    if (ext && ext !== lastCopyTsv.current) {
      await mutate('paste', () => bridge.paste_text(r, c, ext))
    } else {
      await mutate('paste', () => bridge.paste(r, c))
    }
    await refresh()
    await loadSource(r, c)
  }, [refresh, loadSource, mutate])

  const fillSelection = useCallback(
    async (direction: 'down' | 'right') => {
      const s = selRect(curRef.current, anchorRef.current)
      await mutate('fill', () => bridge.fill(s.r0, s.c0, s.r1, s.c1, direction))
      await refresh()
    },
    [refresh, mutate],
  )

  const clearSelection = useCallback(async () => {
    const { r, c } = curRef.current
    const s = selRect(curRef.current, anchorRef.current)
    await mutate('clear', () => bridge.clear_range(s.r0, s.c0, s.r1, s.c1))
    await refresh()
    await loadSource(r, c)
  }, [refresh, loadSource, mutate])

  const gotoRef = useCallback(
    (text: string): boolean => {
      const hit = parseRef(text)
      if (!hit || hit.r >= nrow || hit.c >= ncol) return false
      moveCursor(hit.r, hit.c, false)
      scrollEl.current?.focus()
      return true
    },
    [moveCursor, ncol, nrow],
  )

  useImperativeHandle(
    ref,
    (): GridHandle => ({
      copy: () => void copySelection(false),
      cut: () => void copySelection(true),
      paste: () => void pasteAt(),
      clear: () => void clearSelection(),
      fillDown: () => void fillSelection('down'),
      fillRight: () => void fillSelection('right'),
      edit: () => void beginEdit(curRef.current.r, curRef.current.c),
      goto: gotoRef,
      focus: () => scrollEl.current?.focus(),
    }),
    [copySelection, pasteAt, clearSelection, fillSelection, beginEdit, gotoRef],
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
        if (dir) void fillSelection(dir)
      }
      if (resizing.current) {
        const { col } = resizing.current
        resizing.current = null
        // Persist on release, not on every mousemove: a drag is dozens of
        // frames and each bridge call is a round trip into Python.
        const w = colWidthsRef.current.get(col)
        // A width is per-sheet state the workbook carries, so the release is a
        // mutation: without this the dirty mark stays clear and the user can
        // close over an unsaved resize.
        if (w !== undefined) void mutate('column width', () => bridge.set_col_width(col, w))
        void refresh() // the visible column range may have changed
      }
      dragging.current = false
      pointing.current = false
      lineDrag.current = null
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [refresh, fillSelection, mutate])

  // Selecting a whole row or column by its header. This is the gesture the
  // Insert/Delete Row+Column menu items are built around -- they act on the
  // selection and label themselves with its span, so without it the only way
  // to delete three rows is to drag across three rows of cells.
  //
  // The selection runs to the last row/column rather than being a distinct
  // "whole line" mode: everything downstream (stats, clear, format, the
  // structural edits) already takes a rectangle, so a full-extent rectangle
  // needs no new concept anywhere else.
  const selectLine = useCallback(
    (axis: 'row' | 'col', index: number, extend: boolean) => {
      if (editing) void commit('none')
      // The cursor lands on the near end (A4 for row 4) and the anchor holds
      // the far end, matching a spreadsheet: the selection covers the line, but
      // the *active* cell is the one you would start typing into. Shift-click
      // leaves the anchor alone so the run extends from where it started.
      if (axis === 'row') {
        if (!extend) putAnchor({ r: index, c: ncol - 1 })
        putCur({ r: index, c: 0 })
      } else {
        if (!extend) putAnchor({ r: nrow - 1, c: index })
        putCur({ r: 0, c: index })
      }
      scrollEl.current?.focus()
    },
    [editing, commit, putAnchor, putCur, ncol, nrow],
  )

  // A drag across headers extends the run, mirroring a cell drag.
  const lineDrag = useRef<'row' | 'col' | null>(null)

  const startLineSelect = (axis: 'row' | 'col', index: number) => (e: MouseEvent) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation() // not a cell click, and on a column header not a resize
    selectLine(axis, index, e.shiftKey)
    lineDrag.current = axis
  }

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
      putAnchor({ r: ff.r0, c: ff.c0 })
      if (Math.abs(dR) >= Math.abs(dC)) putCur({ r: Math.max(ff.r0, hit.r), c: ff.c1 })
      else putCur({ r: ff.r1, c: Math.max(ff.c0, hit.c) })
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
      case 'Backspace':
        void clearSelection()
        break
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
        <div
          key={c}
          className="hdr"
          style={{ left: xs[c], width: xs[c + 1] - xs[c] }}
          onMouseDown={startLineSelect('col', c)}
          onMouseEnter={() => {
            if (lineDrag.current === 'col') selectLine('col', c, true)
          }}
        >
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
  }, [view, xs, startResize, startLineSelect, selectLine])

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

  // Positioned like cells, but driven by the solve result rather than the
  // viewport fetch. Off-screen annotations are skipped rather than clamped --
  // scrolling to them brings them back.
  const annotationLayer = useMemo(() => {
    if (!annotations) return null
    const items = []
    for (const [a1, ann] of Object.entries(annotations)) {
      const at = parseRef(a1)
      if (!at || at.r >= nrow || at.c >= ncol) continue
      items.push(
        <div
          key={a1}
          className={'annot ' + ann.role}
          title={ann.title}
          style={{ left: xs[at.c], top: CH + at.r * CH, width: xs[at.c + 1] - xs[at.c] }}
        />,
      )
    }
    return items
  }, [annotations, xs, ncol, nrow])

  const gutterLayer = useMemo(() => {
    if (!view) return null
    const items = []
    for (let r = view.r0; r < view.r0 + view.rows; r++) {
      items.push(
        <div
          key={r}
          className="gut"
          style={{ top: CH + r * CH }}
          onMouseDown={startLineSelect('row', r)}
          onMouseEnter={() => {
            if (lineDrag.current === 'row') selectLine('row', r, true)
          }}
        >
          {r + 1}
        </div>,
      )
    }
    return items
  }, [view, startLineSelect, selectLine])

  return (
    <div className="grid">
      <div className="formula-bar">
        {/* Type a reference to jump; blurring without committing snaps back to
            the cursor's own address. */}
        <input
          className="name-box"
          aria-label="Cell reference"
          value={nameDraft ?? cellRef(cur.r, cur.c)}
          onChange={(e) => setNameDraft(e.target.value)}
          onFocus={(e) => e.target.select()}
          onBlur={() => setNameDraft(null)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              if (gotoRef(nameDraft ?? '')) setNameDraft(null)
            } else if (e.key === 'Escape') {
              setNameDraft(null)
              scrollEl.current?.focus()
            }
            e.stopPropagation()
          }}
        />
        {/* Editing here drives the same edit session as the in-cell editor, so
            a formula can be written in whichever the user reaches for. */}
        <input
          ref={barEl}
          className="formula-src"
          aria-label="Formula"
          value={editing ? editValue : source}
          onChange={(e) => {
            if (editing) {
              setEditValue(e.target.value)
              resetPoint()
            } else {
              void beginEdit(cur.r, cur.c, e.target.value, true)
            }
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              void commit('down')
            } else if (e.key === 'Escape') {
              e.preventDefault()
              cancelEdit()
              void loadSource(cur.r, cur.c)
            }
            e.stopPropagation()
          }}
        />
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
          <div className="annot-layer">{annotationLayer}</div>
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

          {editing && !editInBar && (
            <input
              ref={editorEl}
              aria-label={`Edit ${cellRef(editing.r, editing.c)}`}
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
