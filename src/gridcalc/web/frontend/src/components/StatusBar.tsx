import { useEffect, useState } from 'react'
import { bridge } from '../bridge/api'
import type { Stats } from '../bridge/types'
import type { Selection } from '../lib/grid'
import { fnum } from '../lib/format'
import type { StatusKind } from '../hooks/useWorkbook'

// The bottom line: what the selection is, what it adds up to, and whatever the
// app last needed to say. The aggregates come from the engine (`Api.stats`)
// rather than the rendered viewport, because the client only ever receives
// cells as formatted text -- and only the ones currently scrolled into view.
export function StatusBar({
  selection,
  status,
  statusKind,
  dirty,
  revision,
}: {
  selection: Selection | null
  status: string
  statusKind: StatusKind
  dirty: boolean
  // Bumped on every mutation, so the aggregates follow edits, not just moves.
  revision: number
}) {
  const [stats, setStats] = useState<Stats | null>(null)

  const r0 = selection?.r0
  const c0 = selection?.c0
  const r1 = selection?.r1
  const c1 = selection?.c1

  useEffect(() => {
    if (r0 === undefined || c0 === undefined || r1 === undefined || c1 === undefined) {
      setStats(null)
      return
    }
    let alive = true
    bridge
      .stats(r0, c0, r1, c1)
      .then((s) => alive && setStats(s))
      .catch(() => alive && setStats(null)) // a stats failure must not nag
    return () => {
      alive = false
    }
  }, [r0, c0, r1, c1, revision])

  const cells = selection ? (selection.r1 - selection.r0 + 1) * (selection.c1 - selection.c0 + 1) : 0

  return (
    <div className="statusbar">
      <span className="status-ref">{selection?.ref ?? ''}</span>
      {cells > 1 && <span className="status-dim">{cells} cells</span>}
      {stats && stats.numeric > 0 && (
        <>
          <span className="status-stat">sum {fnum(stats.sum)}</span>
          <span className="status-stat">avg {fnum(stats.avg)}</span>
          <span className="status-stat">min {fnum(stats.min)}</span>
          <span className="status-stat">max {fnum(stats.max)}</span>
          <span className="status-stat">count {stats.numeric}</span>
        </>
      )}
      <span className="tool-spacer" />
      {dirty && (
        <span className="status-dirty" title="unsaved changes">
          modified
        </span>
      )}
      {/* Announced, so a failure is not a purely visual event. */}
      <span className={'status-msg ' + statusKind} role="status" aria-live="polite">
        {status}
      </span>
    </div>
  )
}
