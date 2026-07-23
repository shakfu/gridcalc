import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { bridge } from '../bridge/api'
import type { SolveResult } from '../bridge/types'
import type { Selection } from '../lib/grid'
import { fmtCell, fnum } from '../lib/format'

interface Col {
  key: string
  head: string
  kind?: 'k' | 'bool'
}

const VAR_COLS: Col[] = [
  { key: 'cell', head: 'cell', kind: 'k' },
  { key: 'value', head: 'value' },
  { key: 'reduced_cost', head: 'reduced cost' },
  { key: 'obj_coef', head: 'obj coef' },
  { key: 'obj_from', head: 'obj from' },
  { key: 'obj_till', head: 'obj till' },
]

const CON_COLS: Col[] = [
  { key: 'cell', head: 'cell', kind: 'k' },
  { key: 'shadow_price', head: 'shadow price' },
  { key: 'rhs', head: 'rhs' },
  { key: 'slack', head: 'slack' },
  { key: 'binding', head: 'binding', kind: 'bool' },
  { key: 'rhs_from', head: 'rhs from' },
  { key: 'rhs_till', head: 'rhs till' },
]

function SensTable({ rows, cols }: { rows: readonly object[]; cols: Col[] }) {
  return (
    <table className="sens">
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c.key} className={c.kind === 'k' ? 'k' : ''}>
              {c.head}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {cols.map((c) => (
              <td key={c.key} className={c.kind === 'k' ? 'k' : ''}>
                {fmtCell((row as Record<string, unknown>)[c.key], c.kind)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SolveResultView({ result, sense }: { result: SolveResult; sense: string }) {
  if (!result.ok) return <p className="error">{result.error}</p>
  const values = result.values ?? {}
  return (
    <div className="solve-result" data-testid="solve-result">
      <div className="result-head">
        <span className={'badge ' + (result.optimal ? 'ok' : 'bad')}>{result.status}</span>
        {result.optimal && (
          <span className="result-obj">
            {sense} objective = {fnum(result.objective)}
          </span>
        )}
      </div>

      {result.optimal && Object.keys(values).length > 0 && (
        <SensTable
          rows={Object.entries(values).map(([cell, value]) => ({ cell, value }))}
          cols={[
            { key: 'cell', head: 'cell', kind: 'k' },
            { key: 'value', head: 'value' },
          ]}
        />
      )}

      {result.sensitivity ? (
        <>
          <div className="panel-subtitle">Variables</div>
          <SensTable rows={result.sensitivity.variables} cols={VAR_COLS} />
          <div className="panel-subtitle">Constraints</div>
          <SensTable rows={result.sensitivity.constraints} cols={CON_COLS} />
        </>
      ) : result.optimal ? (
        <p className="sens-note">No sensitivity for integer models.</p>
      ) : null}

      {result.conflict && (
        <p className="diag">Conflicting constraints: {result.conflict.join(', ')}</p>
      )}
      {result.unbounded && (
        <p className="diag">
          Unbounded variables: {result.unbounded.join(', ') || '(unidentified)'}
        </p>
      )}
    </div>
  )
}

export function ResultsDialog({
  open,
  onOpenChange,
  selection,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  selection: Selection | null
}) {
  const [sense, setSense] = useState<'max' | 'min'>('max')
  const [result, setResult] = useState<SolveResult | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) setResult(null)
  }, [open])

  const solve = async () => {
    if (!selection) return
    setBusy(true)
    setResult(
      await bridge.solve_selection(
        selection.r0,
        selection.c0,
        selection.r1,
        selection.c1,
        sense,
      ),
    )
    setBusy(false)
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content wide">
          <Dialog.Title className="dialog-title">Optimize</Dialog.Title>
          <Dialog.Description className="dialog-desc">
            Infer and solve a linear model from the selection {selection?.ref ?? '(none)'}.
          </Dialog.Description>
          <div className="field-row">
            <span className="field-label">Sense</span>
            <label className="radio">
              <input type="radio" checked={sense === 'max'} onChange={() => setSense('max')} />
              Maximize
            </label>
            <label className="radio">
              <input type="radio" checked={sense === 'min'} onChange={() => setSense('min')} />
              Minimize
            </label>
            <button className="btn-primary" onClick={() => void solve()} disabled={busy || !selection}>
              Solve
            </button>
          </div>
          {result && <SolveResultView result={result} sense={sense} />}
          <div className="dialog-actions">
            <Dialog.Close className="btn">Close</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
