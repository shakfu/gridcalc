import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MenuBar } from './MenuBar'
import type { WorkbookActions } from '../hooks/useWorkbook'

function makeActions(): WorkbookActions {
  return {
    open: vi.fn(async () => {}),
    save: vi.fn(async () => {}),
    saveAs: vi.fn(async () => {}),
    undo: vi.fn(async () => {}),
    redo: vi.fn(async () => {}),
    setSheet: vi.fn(async () => {}),
    addSheet: vi.fn(async () => {}),
    deleteSheet: vi.fn(async () => {}),
    renameSheet: vi.fn(async () => {}),
    moveSheet: vi.fn(async () => {}),
    runCommand: vi.fn(async () => {}),
    format: vi.fn(async () => {}),
    setDefaultFormat: vi.fn(async () => {}),
    resolveTrust: vi.fn(async () => {}),
  }
}

function makeCommands() {
  return {
    cut: vi.fn(),
    copy: vi.fn(),
    paste: vi.fn(),
    clear: vi.fn(),
    fillDown: vi.fn(),
    fillRight: vi.fn(),
  }
}

function makeStructure(rows = 1, cols = 1) {
  return {
    rows,
    cols,
    insertRows: vi.fn(),
    insertCols: vi.fn(),
    deleteRows: vi.fn(),
    deleteCols: vi.fn(),
  }
}

function renderMenu(over: Partial<Parameters<typeof MenuBar>[0]> = {}) {
  const props = {
    actions: makeActions(),
    commands: makeCommands(),
    structure: makeStructure(),
    sheets: { active: 0, names: ['Sheet1', 'Data'] },
    onAbout: vi.fn(),
    onOptimize: vi.fn(),
    onGoal: vi.fn(),
    onSweep: vi.fn(),
    onChart: vi.fn(),
    onFormat: vi.fn(),
    onDefaultFormat: vi.fn(),
    onAddSheet: vi.fn(),
    onRenameSheet: vi.fn(),
    onFind: vi.fn(),
    ...over,
  }
  render(<MenuBar {...props} />)
  return props
}

test('File > Open invokes the open action', async () => {
  const { actions } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'File' }))
  await user.click(await screen.findByRole('menuitem', { name: /Open/ }))
  expect(actions.open).toHaveBeenCalledOnce()
})

test('Edit > Undo invokes the undo action', async () => {
  const { actions } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
  await user.click(await screen.findByRole('menuitem', { name: /Undo/ }))
  expect(actions.undo).toHaveBeenCalledOnce()
})

test('Data > Optimize invokes the optimize callback', async () => {
  const { onOptimize } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Data' }))
  await user.click(await screen.findByRole('menuitem', { name: /Optimize/ }))
  expect(onOptimize).toHaveBeenCalledOnce()
})

test('Format > Bold emits a bold format spec', async () => {
  const { onFormat } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Format' }))
  await user.click(await screen.findByRole('menuitem', { name: /Bold/ }))
  expect(onFormat).toHaveBeenCalledWith('b')
})

test('Format > Currency emits a currency format spec', async () => {
  const { onFormat } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Format' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Number: Currency' }))
  expect(onFormat).toHaveBeenCalledWith('$')
})

test('Format > Default: Currency sets the global default format', async () => {
  const { onDefaultFormat } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Format' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Default: Currency' }))
  expect(onDefaultFormat).toHaveBeenCalledWith('$')
})

test('Help > About invokes the about callback', async () => {
  const { onAbout } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Help' }))
  await user.click(await screen.findByRole('menuitem', { name: /About/ }))
  expect(onAbout).toHaveBeenCalledOnce()
})

test.each([
  ['Cut', 'cut'],
  ['Copy', 'copy'],
  ['Paste', 'paste'],
  ['Delete', 'clear'],
  ['Fill Down', 'fillDown'],
  ['Fill Right', 'fillRight'],
] as const)('Edit > %s runs the grid command', async (label, cmd) => {
  const { commands } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
  await user.click(await screen.findByRole('menuitem', { name: new RegExp(label) }))
  expect(commands[cmd]).toHaveBeenCalledOnce()
})

test('Data > Sweep invokes the sweep callback', async () => {
  const { onSweep } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Data' }))
  await user.click(await screen.findByRole('menuitem', { name: /Sweep/ }))
  expect(onSweep).toHaveBeenCalledOnce()
})

test.each([
  [/Insert Row Above/, 'insertRows'],
  [/Insert Column Left/, 'insertCols'],
  [/Delete Row/, 'deleteRows'],
  [/Delete Column/, 'deleteCols'],
] as const)('Insert > %s runs the structural command', async (label, cmd) => {
  const structure = makeStructure()
  renderMenu({ structure })
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Insert' }))
  await user.click(await screen.findByRole('menuitem', { name: label }))
  expect(structure[cmd]).toHaveBeenCalledOnce()
})

test('structural items are disabled with nothing selected', async () => {
  // There is no sensible place to insert without a selection, and silently
  // acting on row 0 would be worse than saying so.
  renderMenu({ structure: null })
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Insert' }))
  expect(await screen.findByRole('menuitem', { name: /Insert Row/ })).toHaveAttribute(
    'data-disabled',
  )
})

test('structural labels count the selected span', async () => {
  renderMenu({ structure: makeStructure(3, 2) })
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Insert' }))
  expect(await screen.findByRole('menuitem', { name: 'Delete 3 Rows' })).toBeTruthy()
  expect(await screen.findByRole('menuitem', { name: 'Insert 2 Columns Left' })).toBeTruthy()
})

test('Sheet > Delete removes the active sheet by name', async () => {
  const { actions } = renderMenu({ sheets: { active: 1, names: ['Sheet1', 'Data'] } })
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Sheet' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Delete' }))
  expect(actions.deleteSheet).toHaveBeenCalledWith('Data')
})

test('Sheet > Delete is disabled on a single-sheet workbook', async () => {
  renderMenu({ sheets: { active: 0, names: ['Sheet1'] } })
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Sheet' }))
  expect(await screen.findByRole('menuitem', { name: 'Delete' })).toHaveAttribute('data-disabled')
})

test('Sheet > Move Left is disabled on the first sheet and moves otherwise', async () => {
  renderMenu({ sheets: { active: 0, names: ['Sheet1', 'Data'] } })
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Sheet' }))
  expect(await screen.findByRole('menuitem', { name: 'Move Left' })).toHaveAttribute(
    'data-disabled',
  )
})

test('Sheet > Move Right reorders the active sheet', async () => {
  const { actions } = renderMenu({ sheets: { active: 0, names: ['Sheet1', 'Data'] } })
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Sheet' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Move Right' }))
  expect(actions.moveSheet).toHaveBeenCalledWith('Sheet1', 1)
})

test('Sheet > New opens the name dialog rather than acting immediately', async () => {
  const { onAddSheet } = renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Sheet' }))
  await user.click(await screen.findByRole('menuitem', { name: /New Sheet/ }))
  expect(onAddSheet).toHaveBeenCalledOnce()
})

test('Edit items are enabled -- the commands behind them all exist', async () => {
  // A disabled item here would be the menu misrepresenting the app: every one
  // of these has worked from the keyboard since the grid landed.
  renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
  for (const name of [/Cut/, /Copy/, /Paste/, /Fill Down/, /Fill Right/]) {
    expect(await screen.findByRole('menuitem', { name })).not.toHaveAttribute('data-disabled')
  }
})
