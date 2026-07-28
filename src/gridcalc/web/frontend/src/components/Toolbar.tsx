import * as Select from '@radix-ui/react-select'
import type { Workbook } from '../hooks/useWorkbook'

// The active-sheet dropdown. A single-sheet workbook has nothing to pick, so it
// renders as a static label rather than a control.
function SheetSelect({ wb }: { wb: Workbook }) {
  const sheets = wb.sheets
  if (!sheets) return null
  if (sheets.names.length < 2) {
    return <span className="sheet-label">{sheets.names[sheets.active]}</span>
  }
  return (
    <Select.Root
      value={String(sheets.active)}
      onValueChange={(v) => void wb.actions.setSheet(Number(v))}
    >
      <Select.Trigger className="select-trigger" aria-label="Active sheet">
        <Select.Value />
        <Select.Icon className="select-icon">▾</Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="select-content" position="popper" sideOffset={4}>
          <Select.Viewport>
            {sheets.names.map((name, i) => (
              <Select.Item key={i} value={String(i)} className="select-item">
                <Select.ItemText>{name}</Select.ItemText>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  )
}

export function Toolbar({ wb, onFormat }: { wb: Workbook; onFormat: (spec: string) => void }) {
  const disabled = !wb.ready
  return (
    <div className="toolbar">
      <button className="tool-btn" onClick={() => void wb.actions.open()} disabled={disabled}>
        Open
      </button>
      <button className="tool-btn" onClick={() => void wb.actions.save()} disabled={disabled}>
        Save
      </button>
      <span className="tool-sep" />
      <button
        className="tool-btn"
        onClick={() => void wb.actions.undo()}
        disabled={disabled}
        title="Undo (⌘Z)"
      >
        Undo
      </button>
      <button
        className="tool-btn"
        onClick={() => void wb.actions.redo()}
        disabled={disabled}
        title="Redo (⇧⌘Z)"
      >
        Redo
      </button>
      <span className="tool-sep" />
      <button
        className="tool-btn fmt-b"
        onClick={() => onFormat('b')}
        disabled={disabled}
        title="Bold (⌘B)"
      >
        B
      </button>
      <button
        className="tool-btn fmt-i"
        onClick={() => onFormat('i')}
        disabled={disabled}
        title="Italic (⌘I)"
      >
        I
      </button>
      <button
        className="tool-btn fmt-u"
        onClick={() => onFormat('u')}
        disabled={disabled}
        title="Underline (⌘U)"
      >
        U
      </button>
      <span className="tool-sep" />
      <span className="tool-label">Sheet</span>
      <SheetSelect wb={wb} />

      <span className="tool-spacer" />
      {/* The unsaved marker matches the window title's trailing `*`. */}
      <span className="tool-file">
        {wb.dims?.filename || '(demo)'}
        {wb.dirty ? ' *' : ''}
      </span>
    </div>
  )
}
