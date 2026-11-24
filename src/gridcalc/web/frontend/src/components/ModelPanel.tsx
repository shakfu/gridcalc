import { useCallback, useEffect, useRef, useState } from 'react'
import { bridge } from '../bridge/api'
import type { ModelRunResult } from '../bridge/types'
import { CodeEditor } from './CodeEditor'

const SAVE_DELAY_MS = 400
const POLL_MS = 250

interface ModelPanelProps {
  // Bumps on undo/redo, sheet switch or load: the model text may have changed.
  revision: string
  showModel: boolean
  onShowModel: (on: boolean) => void
  onClose: () => void
  // A solve wrote cells; the grid must refetch.
  onMutated: () => void
  // The model text changed; the workbook now has unsaved changes.
  onEdited: () => void
  notify: (msg: string) => void
  fail: (msg: string) => void
}

// The active sheet's solver model: a CodeMirror editor, Solve / Cancel, the
// model's problems and its output. The solve runs in the engine's background;
// this panel polls for its end, so the grid stays usable meanwhile.
export function ModelPanel({
  revision,
  showModel,
  onShowModel,
  onClose,
  onMutated,
  onEdited,
  notify,
  fail,
}: ModelPanelProps) {
  const [text, setText] = useState('')
  const [sheet, setSheet] = useState('')
  const [backend, setBackend] = useState<'builtin' | 'pulp'>('builtin')
  const [problems, setProblems] = useState<string[]>([])
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [output, setOutput] = useState<string[]>([])
  const [errorLine, setErrorLine] = useState<number | null>(null)
  // Text typed but not yet sent. While set, a refetch must not overwrite it.
  const pending = useRef<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const polling = useRef(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      // Closing the panel must not drop text typed in the last pause.
      if (timer.current) clearTimeout(timer.current)
      if (pending.current !== null) void bridge.set_model(pending.current)
    }
  }, [])

  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    const t = pending.current
    if (t === null) return
    pending.current = null
    const r = await bridge.set_model(t)
    if (!alive.current) return
    if (!r.ok) {
      fail(r.error ?? 'could not save the model')
      return
    }
    setProblems(r.problems ?? [])
    if (r.dirty) onEdited()
  }, [fail, onEdited])

  const finish = useCallback(
    (r: ModelRunResult) => {
      setRunning(false)
      setOutput(r.lines)
      setErrorLine(r.line)
      if (r.changed) onMutated()
      if (r.ok) notify(r.message)
      else fail(r.message)
    },
    [onMutated, notify, fail],
  )

  const poll = useCallback(async () => {
    if (polling.current) return
    polling.current = true
    let offset = 0
    try {
      // Checked before each poll: a closed panel must not take the result,
      // which `solve_status` hands out only once.
      while (alive.current) {
        const st = await bridge.solve_status(offset)
        if (!alive.current) return
        if (!st.running) {
          if (st.result) finish(st.result)
          else setRunning(false)
          return
        }
        setRunning(true)
        setElapsed(st.elapsed ?? 0)
        if (st.output) {
          const text = st.output
          setOutput((o) => [...o, ...text.replace(/\n$/, '').split('\n')])
        }
        offset = st.offset ?? offset
        await new Promise((res) => setTimeout(res, POLL_MS))
      }
    } finally {
      polling.current = false
    }
  }, [finish])

  // Load the model, and pick up a run that started or ended while closed.
  useEffect(() => {
    if (pending.current !== null) return
    let live = true
    void bridge.model().then((m) => {
      if (!live) return
      setText(m.text)
      setSheet(m.sheet)
      setBackend(m.backend)
      setProblems(m.problems)
      void poll()
    })
    return () => {
      live = false
    }
  }, [revision, poll])

  const onChange = useCallback(
    (t: string) => {
      setText(t)
      pending.current = t
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => void flush(), SAVE_DELAY_MS)
    },
    [flush],
  )

  const solve = async () => {
    await flush()
    setOutput([])
    setErrorLine(null)
    const r = await bridge.start_solve()
    if (!r.ok) {
      setOutput(r.lines ?? [])
      fail(r.error ?? 'could not start the model')
      return
    }
    setRunning(true)
    setElapsed(0)
    void poll()
  }

  const chooseBackend = async (b: 'builtin' | 'pulp') => {
    const r = await bridge.set_model_backend(b)
    if (!r.ok) {
      fail(r.error ?? 'could not change the backend')
      return
    }
    setBackend(b)
    setProblems(r.problems ?? [])
    if (r.dirty) onEdited()
  }

  const cancel = async () => {
    const r = await bridge.cancel_solve()
    if (!r.ok) fail(r.error ?? 'could not cancel')
  }

  return (
    <aside className="model-panel" aria-label="Model">
      <header className="model-head">
        <span className="model-title">Model{sheet ? ` - ${sheet}` : ''}</span>
        {running ? (
          <>
            <span className="model-running">running {elapsed.toFixed(0)} s</span>
            <button type="button" onClick={() => void cancel()}>
              Cancel
            </button>
          </>
        ) : (
          <button type="button" className="primary" onClick={() => void solve()}>
            Solve
          </button>
        )}
        <select
          aria-label="Model backend"
          value={backend}
          disabled={running}
          onChange={(e) => void chooseBackend(e.target.value as 'builtin' | 'pulp')}
        >
          <option value="builtin">Built-in (HiGHS)</option>
          <option value="pulp">PuLP library</option>
        </select>
        <label className="model-toggle">
          <input
            type="checkbox"
            checked={showModel}
            onChange={(e) => onShowModel(e.target.checked)}
          />
          Show model
        </label>
        <button type="button" aria-label="Close model panel" onClick={onClose}>
          x
        </button>
      </header>
      <CodeEditor value={text} onChange={onChange} gotoLine={errorLine} />
      {problems.length > 0 && (
        <ul className="model-problems" aria-label="Model problems">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      <pre className="model-output" aria-label="Model output">
        {output.join('\n')}
      </pre>
    </aside>
  )
}
