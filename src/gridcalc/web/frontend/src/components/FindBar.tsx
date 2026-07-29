import { useEffect, useRef, useState } from 'react'
import { bridge } from '../bridge/api'
import type { SearchMatch } from '../bridge/types'

// The `/` `n` `N` of the TUI, as a find bar. Matching happens engine-side
// (`Api.search`, over both a cell's source text and a formula's computed
// value), because the client only ever holds the formatted text of the cells
// currently scrolled into view -- it cannot search what it has not fetched.
//
// The bar owns the match list and the position within it; jumping is delegated
// to the grid's `goto`, so navigation shares the code path the name box uses
// and cannot drift from it.
export function FindBar({
  open,
  onClose,
  onGoto,
  onError,
  // Bumped on every mutation, so a search re-runs against edited cells rather
  // than pointing at stale hits.
  revision,
}: {
  open: boolean
  onClose: () => void
  onGoto: (ref: string) => void
  onError?: (msg: string) => void
  revision: number
}) {
  const [pattern, setPattern] = useState('')
  const [matches, setMatches] = useState<SearchMatch[]>([])
  const [total, setTotal] = useState(0)
  const [truncated, setTruncated] = useState(false)
  const [index, setIndex] = useState(0)
  const inputEl = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) inputEl.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    let alive = true
    bridge
      .search(pattern)
      .then((r) => {
        if (!alive) return
        setMatches(r.matches)
        setTotal(r.total)
        setTruncated(r.truncated)
        setIndex(0)
        // Land on the first hit as the user types, the way an editor's
        // incremental find does -- without waiting for Enter.
        if (r.matches.length) onGoto(r.matches[0].ref)
      })
      .catch((e: unknown) => onError?.(`search: ${e instanceof Error ? e.message : String(e)}`))
    return () => {
      alive = false
    }
    // `onGoto` is deliberately not a dependency: it is rebuilt every render by
    // the app, and depending on it would re-run the search on every keystroke
    // anywhere in the shell.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pattern, open, revision])

  const step = (delta: number) => {
    if (!matches.length) return
    const next = (index + delta + matches.length) % matches.length
    setIndex(next)
    onGoto(matches[next].ref)
  }

  if (!open) return null

  const count = total === 0 ? (pattern ? 'no matches' : '') : `${index + 1} of ${total}`

  return (
    <div className="findbar" role="search">
      <input
        ref={inputEl}
        className="find-input"
        value={pattern}
        placeholder="Find"
        aria-label="Find"
        onChange={(e) => setPattern(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            step(e.shiftKey ? -1 : 1)
          } else if (e.key === 'Escape') {
            e.preventDefault()
            onClose()
          }
        }}
      />
      <span className="find-count" role="status" aria-live="polite">
        {count}
        {/* Never let a capped list read as the whole story. */}
        {truncated && <span className="find-note"> (first {matches.length} shown)</span>}
      </span>
      <button className="tool-btn" onClick={() => step(-1)} disabled={!matches.length}>
        Prev
      </button>
      <button className="tool-btn" onClick={() => step(1)} disabled={!matches.length}>
        Next
      </button>
      <button className="tool-btn" onClick={onClose} aria-label="Close find">
        Close
      </button>
    </div>
  )
}
