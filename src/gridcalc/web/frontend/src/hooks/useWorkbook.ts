import { useCallback, useEffect, useMemo, useState } from 'react'
import { bridge, whenReady } from '../bridge/api'
import type { Dims, Sheets } from '../bridge/types'

export interface WorkbookActions {
  open(): Promise<void>
  save(): Promise<void>
  saveAs(): Promise<void>
  undo(): Promise<void>
  redo(): Promise<void>
  setSheet(idx: number): Promise<void>
}

export interface Workbook {
  dims: Dims | null
  sheets: Sheets | null
  status: string
  ready: boolean
  // Bumped whenever an out-of-grid action mutates cells (undo/redo), so the
  // grid knows to refetch its viewport without a full remount.
  revision: number
  actions: WorkbookActions
}

// Owns the workbook-level bridge state (dimensions, sheets, a transient status
// line) and the actions the menubar/toolbar invoke. Actions that change the
// workbook (open, save, undo/redo) refresh the derived state, so the chrome
// always reflects what the engine holds.
export function useWorkbook(): Workbook {
  const [dims, setDims] = useState<Dims | null>(null)
  const [sheets, setSheets] = useState<Sheets | null>(null)
  const [status, setStatus] = useState('')
  const [revision, setRevision] = useState(0)

  const refresh = useCallback(async () => {
    const [d, s] = await Promise.all([bridge.dims(), bridge.sheets()])
    setDims(d)
    setSheets(s)
  }, [])

  const flash = useCallback((msg: string) => {
    setStatus(msg)
    if (msg) {
      window.setTimeout(() => setStatus((cur) => (cur === msg ? '' : cur)), 1800)
    }
  }, [])

  useEffect(() => {
    let alive = true
    whenReady()
      .then(refresh)
      .catch((e: unknown) => alive && setStatus(String(e)))
    return () => {
      alive = false
    }
  }, [refresh])

  const actions = useMemo<WorkbookActions>(
    () => ({
      open: async () => {
        const r = await bridge.open_dialog()
        if (r.ok) {
          await refresh()
          flash('opened')
        } else if (r.error) {
          flash('open failed')
        }
      },
      save: async () => {
        let r = await bridge.save()
        if (!r.ok && r.needs_path) r = await bridge.save_dialog()
        if (r.ok) {
          await refresh()
          flash('saved')
        } else if (!r.cancelled) {
          flash('save failed')
        }
      },
      saveAs: async () => {
        const r = await bridge.save_dialog()
        if (r.ok) {
          await refresh()
          flash('saved')
        }
      },
      undo: async () => {
        await bridge.undo()
        await refresh()
        setRevision((n) => n + 1)
      },
      redo: async () => {
        await bridge.redo()
        await refresh()
        setRevision((n) => n + 1)
      },
      setSheet: async (idx: number) => {
        setSheets(await bridge.set_active(idx))
      },
    }),
    [refresh, flash],
  )

  return { dims, sheets, status, ready: Boolean(dims && sheets), revision, actions }
}
