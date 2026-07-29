import type { ReactNode } from 'react'
import * as Menubar from '@radix-ui/react-menubar'
import type { WorkbookActions } from '../hooks/useWorkbook'
import type { Sheets } from '../bridge/types'

// The grid commands the Edit menu drives. Supplied by the app from the grid's
// imperative handle, so the menu and the keyboard run the same code.
export interface EditCommands {
  cut(): void
  copy(): void
  paste(): void
  clear(): void
  fillDown(): void
  fillRight(): void
}

// Structural edits act on whatever the grid has selected: a three-row
// selection inserts three rows and deletes three. Supplied by the app, which
// owns the selection; null when nothing is selected yet.
export interface StructureCommands {
  insertRows(): void
  insertCols(): void
  deleteRows(): void
  deleteCols(): void
  // Human-readable count for the menu labels ("Delete 3 Rows").
  rows: number
  cols: number
}

interface MenuBarProps {
  actions: WorkbookActions
  commands: EditCommands
  structure: StructureCommands | null
  sheets: Sheets | null
  onAbout: () => void
  onOptimize: () => void
  onGoal: () => void
  onSweep: () => void
  onChart: () => void
  onFormat: (spec: string) => void
  onDefaultFormat: (fmt: string) => void
  onAddSheet: () => void
  onRenameSheet: () => void
  onFind: () => void
}

const NO_SELECTION = 'select a cell or range first'

// Pluralize a menu label without saying "1 Rows" or the bare noun for a range.
const many = (n: number, word: string) => (n > 1 ? `${n} ${word}s` : word)

function Item(props: {
  children: ReactNode
  shortcut?: string
  onSelect?: () => void
  disabled?: boolean
  title?: string
}) {
  return (
    <Menubar.Item
      className="menu-item"
      disabled={props.disabled}
      title={props.title}
      onSelect={props.onSelect}
    >
      <span>{props.children}</span>
      {props.shortcut && <span className="menu-shortcut">{props.shortcut}</span>}
    </Menubar.Item>
  )
}

function Menu(props: { label: string; children: ReactNode }) {
  return (
    <Menubar.Menu>
      <Menubar.Trigger className="menu-trigger">{props.label}</Menubar.Trigger>
      <Menubar.Portal>
        <Menubar.Content className="menu-content" align="start" sideOffset={4}>
          {props.children}
        </Menubar.Content>
      </Menubar.Portal>
    </Menubar.Menu>
  )
}

export function MenuBar({
  actions,
  commands,
  structure,
  sheets,
  onAbout,
  onOptimize,
  onGoal,
  onSweep,
  onChart,
  onFormat,
  onDefaultFormat,
  onAddSheet,
  onRenameSheet,
  onFind,
}: MenuBarProps) {
  const rows = structure?.rows ?? 1
  const cols = structure?.cols ?? 1
  const active = sheets ? sheets.names[sheets.active] : ''
  const lastSheet = (sheets?.names.length ?? 0) <= 1
  return (
    <Menubar.Root className="menubar">
      <Menu label="File">
        <Item shortcut="⌘O" onSelect={() => void actions.open()}>
          Open…
        </Item>
        <Item shortcut="⌘S" onSelect={() => void actions.save()}>
          Save
        </Item>
        <Item onSelect={() => void actions.saveAs()}>Save As…</Item>
      </Menu>

      <Menu label="Edit">
        <Item shortcut="⌘Z" onSelect={() => void actions.undo()}>
          Undo
        </Item>
        <Item shortcut="⇧⌘Z" onSelect={() => void actions.redo()}>
          Redo
        </Item>
        <Menubar.Separator className="menu-sep" />
        <Item shortcut="⌘X" onSelect={commands.cut}>
          Cut
        </Item>
        <Item shortcut="⌘C" onSelect={commands.copy}>
          Copy
        </Item>
        <Item shortcut="⌘V" onSelect={commands.paste}>
          Paste
        </Item>
        <Item onSelect={commands.clear}>Delete</Item>
        <Menubar.Separator className="menu-sep" />
        <Item shortcut="⌘F" onSelect={onFind}>
          Find…
        </Item>
        <Menubar.Separator className="menu-sep" />
        <Item shortcut="⌘D" onSelect={commands.fillDown}>
          Fill Down
        </Item>
        <Item shortcut="⌘R" onSelect={commands.fillRight}>
          Fill Right
        </Item>
      </Menu>

      <Menu label="Insert">
        <Item
          disabled={!structure}
          title={structure ? undefined : NO_SELECTION}
          onSelect={structure?.insertRows}
        >
          {`Insert ${many(rows, 'Row')} Above`}
        </Item>
        <Item
          disabled={!structure}
          title={structure ? undefined : NO_SELECTION}
          onSelect={structure?.insertCols}
        >
          {`Insert ${many(cols, 'Column')} Left`}
        </Item>
        <Menubar.Separator className="menu-sep" />
        <Item
          disabled={!structure}
          title={structure ? undefined : NO_SELECTION}
          onSelect={structure?.deleteRows}
        >
          {`Delete ${many(rows, 'Row')}`}
        </Item>
        <Item
          disabled={!structure}
          title={structure ? undefined : NO_SELECTION}
          onSelect={structure?.deleteCols}
        >
          {`Delete ${many(cols, 'Column')}`}
        </Item>
      </Menu>

      <Menu label="Sheet">
        <Item onSelect={onAddSheet}>New Sheet…</Item>
        <Item onSelect={onRenameSheet} disabled={!sheets}>
          Rename…
        </Item>
        <Item
          onSelect={() => void actions.deleteSheet(active)}
          disabled={lastSheet}
          title={lastSheet ? 'a workbook needs at least one sheet' : undefined}
        >
          Delete
        </Item>
        <Menubar.Separator className="menu-sep" />
        <Item
          onSelect={() => void actions.moveSheet(active, (sheets?.active ?? 0) - 1)}
          disabled={!sheets || sheets.active === 0}
        >
          Move Left
        </Item>
        <Item
          onSelect={() => void actions.moveSheet(active, (sheets?.active ?? 0) + 1)}
          disabled={!sheets || sheets.active >= sheets.names.length - 1}
        >
          Move Right
        </Item>
      </Menu>

      <Menu label="Format">
        <Item shortcut="⌘B" onSelect={() => onFormat('b')}>
          Bold
        </Item>
        <Item shortcut="⌘I" onSelect={() => onFormat('i')}>
          Italic
        </Item>
        <Item shortcut="⌘U" onSelect={() => onFormat('u')}>
          Underline
        </Item>
        <Menubar.Separator className="menu-sep" />
        <Item onSelect={() => onFormat('G')}>Number: General</Item>
        <Item onSelect={() => onFormat('I')}>Number: Integer</Item>
        <Item onSelect={() => onFormat('$')}>Number: Currency</Item>
        <Item onSelect={() => onFormat('%')}>Number: Percent</Item>
        <Item onSelect={() => onFormat(',')}>Number: Comma</Item>
        <Item onSelect={() => onFormat('*')}>Bar chart</Item>
        <Menubar.Separator className="menu-sep" />
        <Item onSelect={() => onFormat('L')}>Align Left</Item>
        <Item onSelect={() => onFormat('R')}>Align Right</Item>
        <Menubar.Separator className="menu-sep" />
        <Item onSelect={() => onDefaultFormat('G')}>Default: General</Item>
        <Item onSelect={() => onDefaultFormat('I')}>Default: Integer</Item>
        <Item onSelect={() => onDefaultFormat('$')}>Default: Currency</Item>
        <Item onSelect={() => onDefaultFormat('%')}>Default: Percent</Item>
      </Menu>

      <Menu label="Data">
        <Item onSelect={onOptimize}>Optimize…</Item>
        <Item onSelect={onGoal}>Goal Seek…</Item>
        <Item onSelect={onSweep}>Sweep…</Item>
        <Menubar.Separator className="menu-sep" />
        <Item onSelect={onChart}>Chart…</Item>
      </Menu>

      <Menu label="Help">
        <Item onSelect={onAbout}>About gridcalc</Item>
      </Menu>
    </Menubar.Root>
  )
}
