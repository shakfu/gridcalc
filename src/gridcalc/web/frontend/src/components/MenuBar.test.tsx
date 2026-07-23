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
    format: vi.fn(async () => {}),
    setDefaultFormat: vi.fn(async () => {}),
  }
}

function renderMenu(over: Partial<Parameters<typeof MenuBar>[0]> = {}) {
  const props = {
    actions: makeActions(),
    onAbout: vi.fn(),
    onOptimize: vi.fn(),
    onGoal: vi.fn(),
    onChart: vi.fn(),
    onFormat: vi.fn(),
    onDefaultFormat: vi.fn(),
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

test('not-yet-available items are disabled', async () => {
  renderMenu()
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
  const cut = await screen.findByRole('menuitem', { name: /Cut/ })
  expect(cut).toHaveAttribute('data-disabled')
})
