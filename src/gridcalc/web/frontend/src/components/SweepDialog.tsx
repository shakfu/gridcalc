import { useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { bridge } from '../bridge/api'
import type { SweepResult } from '../bridge/types'
import { fnum } from '../lib/format'

// A parametric right-hand-side sweep (`opt.sweep`): re-solve the model across a
// range of RHS values for one constraint and plot how the objective responds.
// Unlike Optimize, this never writes to the sheet -- it is pure what-if.
//
// The objective curve is piecewise linear and its slope is the constraint's
// shadow price, so the interesting points are the breakpoints where that slope
// changes; they are marked on the line and flagged in the table.
export function SweepDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [sense, setSense] = useState<'max' | 'min'>('max')
  const [objective, setObjective] = useState('')
  const [vars, setVars] = useState('')
  const [constraints, setConstraints] = useState('')
  const [constraint, setConstraint] = useState('')
  const [lo, setLo] = useState('')
  const [hi, setHi] = useState('')
  const [steps, setSteps] = useState('10')
  const [result, setResult] = useState<SweepResult | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    if (!objective || !vars || !constraint || lo === '' || hi === '') {
      setResult({ ok: false, error: 'fill in objective, vars, constraint, and the RHS range' })
      return
    }
    setBusy(true)
    try {
      setResult(
        await bridge.opt_sweep({
          sense,
          objective,
          vars,
          constraints,
          constraint,
          lo: parseFloat(lo),
          hi: parseFloat(hi),
          steps: parseInt(steps, 10) || 10,
        }),
      )
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const points = result?.ok ? (result.points ?? []) : []
  const solved = points.filter((p) => p.objective !== null)

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content wide">
          <Dialog.Title className="dialog-title">Sweep</Dialog.Title>
          <Dialog.Description className="dialog-desc">
            Re-solve across a range of right-hand-side values for one constraint. The sheet is
            never modified.
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
          </div>
          <div className="field-row">
            <span className="field-label">Objective</span>
            <input aria-label="Objective" value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="B2" />
            <span className="field-label">Vars</span>
            <input aria-label="Vars" value={vars} onChange={(e) => setVars(e.target.value)} placeholder="A2:A3" />
          </div>
          <div className="field-row">
            <span className="field-label">Constraints</span>
            <input
              aria-label="Constraints"
              value={constraints}
              onChange={(e) => setConstraints(e.target.value)}
              placeholder="C2:C4"
            />
            <span className="field-label">Sweep</span>
            <input
              aria-label="Sweep constraint"
              value={constraint}
              onChange={(e) => setConstraint(e.target.value)}
              placeholder="C3"
            />
          </div>
          <div className="field-row">
            <span className="field-label">RHS from</span>
            <input aria-label="RHS from" value={lo} onChange={(e) => setLo(e.target.value)} placeholder="0" />
            <span className="field-label">to</span>
            <input aria-label="RHS to" value={hi} onChange={(e) => setHi(e.target.value)} placeholder="24" />
            <span className="field-label">Steps</span>
            <input aria-label="Steps" value={steps} onChange={(e) => setSteps(e.target.value)} placeholder="10" />
            <button className="btn-primary" onClick={() => void run()} disabled={busy}>
              Run
            </button>
          </div>

          {result && !result.ok && <p className="error">{result.error}</p>}

          {solved.length > 0 && (
            <div className="chart-box" data-testid="sweep-chart">
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={solved} margin={{ top: 16, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="rhs" stroke="var(--muted)" fontSize={12} />
                  <YAxis stroke="var(--muted)" fontSize={12} />
                  <Tooltip
                    contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)' }}
                    cursor={{ stroke: 'var(--border)' }}
                  />
                  <Line
                    type="linear"
                    dataKey="objective"
                    stroke="var(--accent)"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  {solved
                    .filter((p) => p.breakpoint)
                    .map((p) => (
                      <ReferenceDot
                        key={p.rhs}
                        x={p.rhs}
                        y={p.objective as number}
                        r={4}
                        fill="var(--err)"
                        stroke="none"
                      />
                    ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {points.length > 0 && (
            <table className="sens" data-testid="sweep-table">
              <thead>
                <tr>
                  <th className="k">rhs</th>
                  <th className="k">status</th>
                  <th>objective</th>
                  <th>shadow price</th>
                  <th>delta</th>
                  <th className="k">breakpoint</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.rhs} className={p.breakpoint ? 'breakpoint' : ''}>
                    <td className="k">{fnum(p.rhs)}</td>
                    <td className="k">{p.status}</td>
                    <td>{p.objective === null ? '--' : fnum(p.objective)}</td>
                    <td>{p.shadow_price === null ? '--' : fnum(p.shadow_price)}</td>
                    <td>{p.delta === null ? '--' : fnum(p.delta)}</td>
                    <td className="k">{p.breakpoint ? 'yes' : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="dialog-actions">
            <Dialog.Close className="btn">Close</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
