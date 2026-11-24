import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { bridge } from '../bridge/api'
import type { DataItemInfo } from '../bridge/types'
import type { Selection } from '../lib/grid'

interface DataItemsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selection: Selection | null
  // Run a shared command (`item`, `unitem`) on the selection; resolves when done.
  runCommand: (name: string, args: string[]) => Promise<void>
  // Show an item's range: switch sheet if needed and select it.
  onGoto: (sheet: string, ref: string) => void
  // Bumps when the workbook changes, so the list is reread.
  revision: string
}

// SolverStudio's "Model Data Items" dialog: the workbook's data items, and a
// form that makes the selection one. A set (no index) can index others.
export function DataItemsDialog({
  open,
  onOpenChange,
  selection,
  runCommand,
  onGoto,
  revision,
}: DataItemsDialogProps) {
  const [items, setItems] = useState<DataItemInfo[]>([])
  const [name, setName] = useState('')
  const [index1, setIndex1] = useState('')
  const [index2, setIndex2] = useState('')
  const [missing, setMissing] = useState('')
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    const r = await bridge.data_items()
    setItems(r.items)
  }, [])

  useEffect(() => {
    if (open) void reload()
  }, [open, revision, reload])

  const sets = items.filter((i) => i.index.length === 0 && i.ref?.includes(':'))

  const add = async () => {
    setError('')
    if (!name.trim()) {
      setError('give the item a name')
      return
    }
    const args = [name.trim(), ...[index1, index2].filter(Boolean)]
    if (missing.trim() !== '') args.push(`missing=${missing.trim()}`)
    await runCommand('item', args)
    setName('')
    setIndex1('')
    setIndex2('')
    setMissing('')
    await reload()
  }

  const remove = async (item: string) => {
    await runCommand('unitem', [item])
    await reload()
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content data-items-dialog">
          <Dialog.Title className="dialog-title">Data items</Dialog.Title>
          {items.length === 0 ? (
            <p className="note">No data items yet. Select a range and add one below.</p>
          ) : (
            <table className="data-items" aria-label="Data items">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Range</th>
                  <th>Index</th>
                  <th>Missing</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((i) => (
                  <tr key={i.name} className={i.problem ? 'bad' : undefined} title={i.problem}>
                    <td>{i.name}</td>
                    <td>
                      {i.sheet && i.ref ? (
                        <button
                          type="button"
                          className="link"
                          onClick={() => {
                            onGoto(i.sheet as string, i.ref as string)
                            onOpenChange(false)
                          }}
                        >
                          {i.sheet}!{i.ref}
                        </button>
                      ) : (
                        <span className="muted">(undefined)</span>
                      )}
                    </td>
                    <td>{i.index.join(', ')}</td>
                    <td>{i.has_missing ? String(i.missing) : 'error'}</td>
                    <td>
                      <button type="button" aria-label={`Delete ${i.name}`} onClick={() => void remove(i.name)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {items.some((i) => i.problem) && (
            <ul className="model-problems">
              {items
                .filter((i) => i.problem)
                .map((i) => (
                  <li key={i.name}>{i.problem}</li>
                ))}
            </ul>
          )}
          <div className="field-row">
            <span className="field-label">Name</span>
            <input aria-label="Item name" value={name} onChange={(e) => setName(e.target.value)} placeholder="costs" />
            <span className="muted">{selection ? `for ${selection.ref}` : ''}</span>
          </div>
          <div className="field-row">
            <span className="field-label">Index</span>
            {[
              [index1, setIndex1, 'Row index'],
              [index2, setIndex2, 'Column index'],
            ].map(([value, set, label]) => (
              <select
                key={label as string}
                aria-label={label as string}
                value={value as string}
                onChange={(e) => (set as (v: string) => void)(e.target.value)}
              >
                <option value="">(none)</option>
                {sets.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            ))}
          </div>
          <div className="field-row">
            <span className="field-label">Missing</span>
            <input
              aria-label="Missing value"
              value={missing}
              onChange={(e) => setMissing(e.target.value)}
              placeholder="error (blank) or a value"
            />
          </div>
          <div className="dialog-actions">
            <span className="goal-result">{error}</span>
            <button className="btn-primary" onClick={() => void add()}>
              Add from selection
            </button>
            <Dialog.Close className="btn">Close</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
