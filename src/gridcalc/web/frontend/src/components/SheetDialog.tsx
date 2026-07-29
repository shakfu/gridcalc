import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { WorkbookActions } from '../hooks/useWorkbook'
import type { Sheets } from '../bridge/types'

export type SheetMode = 'add' | 'rename'

// Name prompt for `:sheet add` / `:sheet rename`. A native `prompt()` is not
// dependable inside a webview, and the engine is the authority on whether a
// name is acceptable -- so this only collects the string and lets the failed
// call report through the status bar like every other bridge error.
export function SheetDialog({
  open,
  mode,
  sheets,
  actions,
  onOpenChange,
}: {
  open: boolean
  mode: SheetMode
  sheets: Sheets | null
  actions: WorkbookActions
  onOpenChange: (open: boolean) => void
}) {
  const current = sheets ? sheets.names[sheets.active] : ''
  const [name, setName] = useState('')

  // Rename starts from the current name (the common edit is a small tweak);
  // add starts from the next free `SheetN`.
  useEffect(() => {
    if (!open) return
    if (mode === 'rename') {
      setName(current)
      return
    }
    const taken = new Set(sheets?.names ?? [])
    let n = (sheets?.names.length ?? 0) + 1
    while (taken.has(`Sheet${n}`)) n += 1
    setName(`Sheet${n}`)
  }, [open, mode, current, sheets])

  const submit = () => {
    const value = name.trim()
    if (!value) return
    void (mode === 'add' ? actions.addSheet(value) : actions.renameSheet(current, value))
    onOpenChange(false)
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title className="dialog-title">
            {mode === 'add' ? 'New sheet' : `Rename ${current}`}
          </Dialog.Title>
          <div className="field-row">
            <span className="field-label">Name</span>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
            />
          </div>
          <div className="dialog-actions">
            <button className="btn-primary" onClick={submit}>
              {mode === 'add' ? 'Create' : 'Rename'}
            </button>
            <Dialog.Close className="btn">Cancel</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
