import { useCallback, useEffect, useMemo, useState } from 'react'
import { bridge, whenReady } from '../bridge/api'
import type { Dims, Sheets, SheetsResult } from '../bridge/types'
import type { Rect } from '../lib/grid'
import { failureOf } from '../bridge/result'

export interface WorkbookActions {
  open(): Promise<void>
  save(): Promise<void>
  saveAs(): Promise<void>
  undo(): Promise<void>
  redo(): Promise<void>
  setSheet(idx: number): Promise<void>
  addSheet(name: string): Promise<void>
  deleteSheet(name: string): Promise<void>
  renameSheet(old: string, name: string): Promise<void>
  moveSheet(name: string, index: number): Promise<void>
  // Run a command from the shared registry (`gridcalc.commands`). One action
  // covers every such command, so adding one to the registry needs no new
  // action here -- which is the point of the registry.
  runCommand(name: string, args?: string[], rect?: Rect | null): Promise<void>
  format(rect: Rect, spec: string): Promise<void>
  setDefaultFormat(fmt: string): Promise<void>
}

export type StatusKind = 'info' | 'error'

export interface Workbook {
  dims: Dims | null
  sheets: Sheets | null
  status: string
  statusKind: StatusKind
  ready: boolean
  // True when the workbook has edits not yet written to disk.
  dirty: boolean
  // Bumped whenever an out-of-grid action mutates cells (undo/redo), so the
  // grid knows to refetch its viewport without a full remount.
  revision: number
  // Bumped on every mutation from any source, including the grid's own edits
  // (which refetch themselves and so must not bump `revision`). Derived views
  // like the status-bar aggregates watch this.
  mutations: number
  // Bumped only when a load replaces the whole workbook. Distinct from
  // `revision`, which many ordinary edits bump: anything keyed on workbook
  // *identity* has to remount on a load and not on an undo.
  loads: number
  actions: WorkbookActions
  // The app-wide user-visible channel. Anything that fails -- a bridge
  // rejection, a failed save -- reports here rather than dying silently.
  notify(msg: string): void
  fail(msg: string): void
  markDirty(): void
  // Something outside the grid wrote to the sheet -- an applied solve or goal
  // seek. Unlike `markDirty` (the grid refetches itself after its own edits),
  // this also bumps `revision` so the grid picks up cells it did not write.
  touched(): void
}

// An error stays up long enough to read; a routine confirmation does not.
const INFO_MS = 1800
const ERROR_MS = 6000

// Owns the workbook-level bridge state (dimensions, sheets, a transient status
// line) and the actions the menubar/toolbar invoke. Actions that change the
// workbook (open, save, undo/redo) refresh the derived state, so the chrome
// always reflects what the engine holds.
export function useWorkbook(): Workbook {
  const [dims, setDims] = useState<Dims | null>(null)
  const [sheets, setSheets] = useState<Sheets | null>(null)
  const [status, setStatus] = useState('')
  const [statusKind, setStatusKind] = useState<StatusKind>('info')
  const [dirty, setDirty] = useState(false)
  const [revision, setRevision] = useState(0)
  const [mutations, setMutations] = useState(0)
  const [loads, setLoads] = useState(0)

  const refresh = useCallback(async () => {
    const [d, s] = await Promise.all([bridge.dims(), bridge.sheets()])
    setDims(d)
    setSheets(s)
    setDirty(d.dirty) // the engine is the authority whenever we ask it
  }, [])

  const show = useCallback((msg: string, kind: StatusKind) => {
    setStatus(msg)
    setStatusKind(kind)
    if (msg) {
      const ms = kind === 'error' ? ERROR_MS : INFO_MS
      window.setTimeout(() => setStatus((cur) => (cur === msg ? '' : cur)), ms)
    }
  }, [])

  const flash = useCallback((msg: string) => show(msg, 'info'), [show])
  const fail = useCallback((msg: string) => show(msg, 'error'), [show])
  const markDirty = useCallback(() => {
    setDirty(true)
    setMutations((n) => n + 1)
  }, [])

  const touched = useCallback(() => {
    setDirty(true)
    setMutations((n) => n + 1)
    setRevision((n) => n + 1)
  }, [])

  useEffect(() => {
    let alive = true
    whenReady()
      .then(refresh)
      .catch((e: unknown) => alive && show(String(e), 'error'))
    return () => {
      alive = false
    }
  }, [refresh, show])

  // Same contract as the grid's guard: a rejected bridge call becomes a
  // user-visible error instead of an unhandled rejection.
  const guard = useCallback(
    async <T,>(what: string, fn: () => Promise<T>): Promise<T | null> => {
      try {
        return await fn()
      } catch (e) {
        fail(`${what}: ${e instanceof Error ? e.message : String(e)}`)
        return null
      }
    },
    [fail],
  )

  // The sheet-management calls all return the new tab list alongside ok/error,
  // so one round trip both mutates and refreshes the tab strip. Switching tabs
  // changes which cells every coordinate refers to, so the grid must refetch.
  const sheetOp = useCallback(
    async (what: string, fn: () => Promise<SheetsResult>) => {
      const r = await guard(what, fn)
      if (!r) return
      setSheets({ active: r.active, names: r.names })
      if (r.ok === false) {
        fail(r.error ?? 'sheet operation failed')
        return
      }
      setDirty(true)
      setMutations((n) => n + 1)
      setRevision((n) => n + 1)
    },
    [guard, fail],
  )

  // Every shared command goes through here. A command that reports `changed`
  // may have moved cells anywhere (insert/delete rewrite references across the
  // sheet, a sort reorders rows), so the viewport is refetched wholesale rather
  // than patched; a query only reports its message.
  const runShared = useCallback(
    async (name: string, args: string[], rect: Rect | null) => {
      const r = await guard(name, () =>
        bridge.run_command(
          name,
          args,
          rect ? { r0: rect.r0, c0: rect.c0, r1: rect.r1, c1: rect.c1 } : null,
        ),
      )
      if (!r) return
      if (!r.ok) {
        fail(r.message || `${name} failed`)
        return
      }
      if (r.changed) {
        setDirty(true)
        setMutations((n) => n + 1)
        setRevision((n) => n + 1)
      }
      if (r.message) flash(r.message)
    },
    [guard, fail, flash],
  )

  const actions = useMemo<WorkbookActions>(
    () => ({
      open: async () => {
        const r = await guard('open', () => bridge.open_dialog())
        if (!r || r.cancelled) return
        if (r.ok) {
          await refresh()
          setRevision((n) => n + 1)
          setLoads((n) => n + 1)
          flash('opened')
        } else {
          fail(r.error ?? 'could not open that workbook')
        }
      },
      save: async () => {
        let r = await guard('save', () => bridge.save())
        if (r && !r.ok && r.needs_path) r = await guard('save', () => bridge.save_dialog())
        if (!r || r.cancelled) return
        if (r.ok) {
          await refresh()
          flash('saved')
        } else {
          fail(r.error ?? 'could not save')
        }
      },
      saveAs: async () => {
        const r = await guard('save', () => bridge.save_dialog())
        if (!r || r.cancelled) return
        if (r.ok) {
          await refresh()
          flash('saved')
        } else {
          fail(r.error ?? 'could not save')
        }
      },
      undo: async () => {
        await guard('undo', () => bridge.undo())
        await refresh()
        setRevision((n) => n + 1)
      },
      redo: async () => {
        await guard('redo', () => bridge.redo())
        await refresh()
        setRevision((n) => n + 1)
      },
      setSheet: async (idx: number) => {
        const s = await guard('sheet', () => bridge.set_active(idx))
        if (s) setSheets(s)
      },
      addSheet: (name: string) => sheetOp('sheet', () => bridge.add_sheet(name)),
      deleteSheet: (name: string) => sheetOp('sheet', () => bridge.delete_sheet(name)),
      renameSheet: (old: string, name: string) =>
        sheetOp('sheet', () => bridge.rename_sheet(old, name)),
      moveSheet: (name: string, index: number) =>
        sheetOp('sheet', () => bridge.move_sheet(name, index)),
      runCommand: (name: string, args: string[] = [], rect: Rect | null = null) =>
        runShared(name, args, rect),
      // Both of these ignored the result and marked the workbook dirty even
      // when the bridge refused, so the status bar and the close guard reported
      // unsaved changes over an unchanged sheet.
      format: async (rect: Rect, spec: string) => {
        const res = await guard('format', () =>
          bridge.set_format(rect.r0, rect.c0, rect.r1, rect.c1, spec),
        )
        if (res === null) return
        const why = failureOf(res)
        if (why !== null) {
          fail(`format: ${why}`)
          return
        }
        setDirty(true)
        setMutations((n) => n + 1)
        setRevision((n) => n + 1) // re-fetch the viewport with the new formatting
      },
      setDefaultFormat: async (fmt: string) => {
        const res = await guard('format', () => bridge.set_global_format(fmt))
        if (res === null) return
        const why = failureOf(res)
        if (why !== null) {
          fail(`format: ${why}`)
          return
        }
        setDirty(true)
        setMutations((n) => n + 1)
        setRevision((n) => n + 1)
      },
    }),
    [refresh, flash, fail, guard, sheetOp, runShared],
  )

  return {
    dims,
    sheets,
    status,
    statusKind,
    ready: Boolean(dims && sheets),
    dirty,
    revision,
    mutations,
    loads,
    actions,
    notify: flash,
    fail,
    markDirty,
    touched,
  }
}
