import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Toolbar } from './Toolbar'
import type { Workbook } from '../hooks/useWorkbook'

function makeWb(overrides: Partial<Workbook> = {}): Workbook {
  return {
    dims: { ncol: 256, nrow: 1024, filename: 'book.json' },
    sheets: { active: 0, names: ['Sheet1', 'Data'] },
    status: '',
    ready: true,
    revision: 0,
    actions: {
      open: vi.fn(async () => {}),
      save: vi.fn(async () => {}),
      saveAs: vi.fn(async () => {}),
      undo: vi.fn(async () => {}),
      redo: vi.fn(async () => {}),
      setSheet: vi.fn(async () => {}),
    },
    ...overrides,
  }
}

test('Save button calls the save action', async () => {
  const wb = makeWb()
  render(<Toolbar wb={wb} />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Save' }))
  expect(wb.actions.save).toHaveBeenCalledOnce()
})

test('shows the loaded filename', () => {
  render(<Toolbar wb={makeWb()} />)
  expect(screen.getByText('book.json')).toBeInTheDocument()
})

test('a single-sheet workbook shows a static label, not a dropdown', () => {
  render(<Toolbar wb={makeWb({ sheets: { active: 0, names: ['Sheet1'] } })} />)
  expect(screen.getByText('Sheet1')).toBeInTheDocument()
  expect(screen.queryByLabelText('Active sheet')).not.toBeInTheDocument()
})

test('toolbar actions are disabled until the bridge is ready', () => {
  render(<Toolbar wb={makeWb({ ready: false })} />)
  expect(screen.getByRole('button', { name: 'Open' })).toBeDisabled()
})
