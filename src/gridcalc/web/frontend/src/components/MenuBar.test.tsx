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
  }
}

test('File > Open invokes the open action', async () => {
  const actions = makeActions()
  render(<MenuBar actions={actions} onAbout={() => {}} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'File' }))
  await user.click(await screen.findByRole('menuitem', { name: /Open/ }))
  expect(actions.open).toHaveBeenCalledOnce()
})

test('Edit > Undo invokes the undo action', async () => {
  const actions = makeActions()
  render(<MenuBar actions={actions} onAbout={() => {}} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
  await user.click(await screen.findByRole('menuitem', { name: /Undo/ }))
  expect(actions.undo).toHaveBeenCalledOnce()
})

test('Help > About invokes the about callback', async () => {
  const actions = makeActions()
  const onAbout = vi.fn()
  render(<MenuBar actions={actions} onAbout={onAbout} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Help' }))
  await user.click(await screen.findByRole('menuitem', { name: /About/ }))
  expect(onAbout).toHaveBeenCalledOnce()
})

test('not-yet-available items are disabled', async () => {
  render(<MenuBar actions={makeActions()} onAbout={() => {}} />)
  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
  const cut = await screen.findByRole('menuitem', { name: /Cut/ })
  expect(cut).toHaveAttribute('data-disabled')
})
