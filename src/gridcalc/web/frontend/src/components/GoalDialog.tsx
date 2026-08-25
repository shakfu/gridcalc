import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { bridge } from '../bridge/api'
import { fnum } from '../lib/format'

// `:goal <cell> = <value> by <var>` -- adjust a variable cell so a formula cell
// reaches a target. Cell refs are typed (prefilled with the active cell), so
// this needs no grid selection.
export function GoalDialog({
  open,
  onOpenChange,
  activeRef,
  onMutated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  activeRef?: string
  // An applied seek overwrote the variable cell; the grid must refetch.
  onMutated?: () => void
}) {
  const [cell, setCell] = useState('')
  const [target, setTarget] = useState('')
  const [varc, setVarc] = useState('')
  const [lo, setLo] = useState('')
  const [hi, setHi] = useState('')
  const [result, setResult] = useState('')

  useEffect(() => {
    if (open) {
      setCell(activeRef ?? '')
      setResult('')
    }
  }, [open, activeRef])

  const run = async () => {
    if (!cell || target === '' || !varc) {
      setResult('fill in set / to / by')
      return
    }
    const res = await bridge.goal_seek(
      cell,
      parseFloat(target),
      varc,
      lo === '' ? null : parseFloat(lo),
      hi === '' ? null : parseFloat(hi),
    )
    if (!res.ok) {
      setResult(res.error ?? 'failed')
      return
    }
    if (res.applied) onMutated?.()
    setResult(
      res.converged
        ? `${varc} = ${fnum(res.var_value)}   (${cell} = ${fnum(res.formula_value)})`
        : `did not converge (residual ${fnum(res.residual)})`,
    )
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title className="dialog-title">Goal seek</Dialog.Title>
          <div className="field-row">
            <span className="field-label">Set cell</span>
            <input aria-label="Set cell" value={cell} onChange={(e) => setCell(e.target.value)} placeholder="B1" />
          </div>
          <div className="field-row">
            <span className="field-label">To value</span>
            <input aria-label="To value" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="0" />
          </div>
          <div className="field-row">
            <span className="field-label">By cell</span>
            <input aria-label="By cell" value={varc} onChange={(e) => setVarc(e.target.value)} placeholder="A1" />
          </div>
          <div className="field-row">
            <span className="field-label">Bracket</span>
            <input aria-label="Bracket low" value={lo} onChange={(e) => setLo(e.target.value)} placeholder="lo (opt)" />
            <input aria-label="Bracket high" value={hi} onChange={(e) => setHi(e.target.value)} placeholder="hi (opt)" />
          </div>
          <div className="dialog-actions">
            <span className="goal-result">{result}</span>
            <button className="btn-primary" onClick={() => void run()}>
              Run
            </button>
            <Dialog.Close className="btn">Close</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
