import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { bridge } from '../bridge/api'
import type { DataItemInfo, TableInfo } from '../bridge/types'
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

// Quoted for the shared command's argument split, so a name may hold spaces.
function quote(s: string): string {
  return /[\s"']/.test(s) ? `"${s.replace(/"/g, '\\"')}"` : s
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
  const [output, setOutput] = useState(false)
  // Where the item's data is: the selected range (a cross-tab) or a table's rows.
  const [source, setSource] = useState<'selection' | 'table'>('selection')
  const [tables, setTables] = useState<TableInfo[]>([])
  const [table, setTable] = useState('')
  const [column, setColumn] = useState('')
  const [asSet, setAsSet] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    const [r, t] = await Promise.all([bridge.data_items(), bridge.tables()])
    setItems(r.items)
    setTables(t.tables)
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
    const args = [name.trim()]
    if (source === 'table') {
      const t = tables.find((x) => x.name === table)
      if (!t || !column) {
        setError('choose a table and a column')
        return
      }
      args.push(`table=${quote(t.name)}`)
      if (asSet) args.push(`column=${quote(column)}`)
      else {
        const keys = t.columns.filter((c) => c !== column)
        args.push(`keys=${quote(keys.join(','))}`, `value=${quote(column)}`)
      }
    } else {
      args.push(...[index1, index2].filter(Boolean))
    }
    if (missing.trim() !== '') args.push(`missing=${missing.trim()}`)
    if (output) args.push('output')
    await runCommand('item', args)
    setName('')
    setIndex1('')
    setIndex2('')
    setMissing('')
    setOutput(false)
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
                  <th>Output</th>
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
                    <td>{i.source || i.index.join(', ')}</td>
                    <td>{i.has_missing ? String(i.missing) : 'error'}</td>
                    <td>{i.output ? 'yes' : ''}</td>
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
            <span className="field-label">Source</span>
            <select
              aria-label="Source"
              value={source}
              onChange={(e) => setSource(e.target.value as 'selection' | 'table')}
            >
              <option value="selection">Selection (cross-tab)</option>
              <option value="table" disabled={tables.length === 0}>
                Table rows (long format)
              </option>
            </select>
          </div>
          {source === 'table' ? (
            <div className="field-row">
              <span className="field-label">Table</span>
              <select
                aria-label="Table"
                value={table}
                onChange={(e) => {
                  setTable(e.target.value)
                  const t = tables.find((x) => x.name === e.target.value)
                  setColumn(t ? (t.columns[t.columns.length - 1] ?? '') : '')
                }}
              >
                <option value="">(choose)</option>
                {tables.map((t) => (
                  <option key={t.name} value={t.name}>
                    {t.name}
                  </option>
                ))}
              </select>
              <select aria-label="Value column" value={column} onChange={(e) => setColumn(e.target.value)}>
                {(tables.find((x) => x.name === table)?.columns ?? []).map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <label className="model-toggle">
                <input
                  type="checkbox"
                  aria-label="Set of column values"
                  checked={asSet}
                  onChange={(e) => setAsSet(e.target.checked)}
                />
                set of its values
              </label>
            </div>
          ) : (
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
          )}
          <div className="field-row">
            <span className="field-label">Missing</span>
            <input
              aria-label="Missing value"
              value={missing}
              onChange={(e) => setMissing(e.target.value)}
              placeholder="error (blank) or a value"
            />
          </div>
          <div className="field-row">
            <span className="field-label">Output</span>
            <label className="model-toggle">
              <input
                type="checkbox"
                aria-label="Output item"
                checked={output}
                onChange={(e) => setOutput(e.target.checked)}
              />
              filled from the model variable of the same name
            </label>
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
