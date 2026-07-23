import type { ReactNode } from 'react'
import * as Menubar from '@radix-ui/react-menubar'
import type { WorkbookActions } from '../hooks/useWorkbook'

interface MenuBarProps {
  actions: WorkbookActions
  onAbout: () => void
  onOptimize: () => void
  onGoal: () => void
  onChart: () => void
  onFormat: (spec: string) => void
  onDefaultFormat: (fmt: string) => void
}

// Items that need the grid's cursor/selection or a feature dialog are shown but
// disabled until their phase lands, so the menu structure reads complete.
const SOON = 'arrives with the grid / feature dialogs in a later phase'

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
  onAbout,
  onOptimize,
  onGoal,
  onChart,
  onFormat,
  onDefaultFormat,
}: MenuBarProps) {
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
        <Item disabled title={SOON} shortcut="⌘X">
          Cut
        </Item>
        <Item disabled title={SOON} shortcut="⌘C">
          Copy
        </Item>
        <Item disabled title={SOON} shortcut="⌘V">
          Paste
        </Item>
        <Item disabled title={SOON}>
          Delete
        </Item>
        <Menubar.Separator className="menu-sep" />
        <Item disabled title={SOON} shortcut="⌘D">
          Fill Down
        </Item>
        <Item disabled title={SOON} shortcut="⌘R">
          Fill Right
        </Item>
      </Menu>

      <Menu label="Insert">
        <Item disabled title={SOON}>
          Row
        </Item>
        <Item disabled title={SOON}>
          Column
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
        <Item disabled title={SOON}>
          Sweep…
        </Item>
        <Menubar.Separator className="menu-sep" />
        <Item onSelect={onChart}>Chart…</Item>
      </Menu>

      <Menu label="Help">
        <Item onSelect={onAbout}>About gridcalc</Item>
      </Menu>
    </Menubar.Root>
  )
}
