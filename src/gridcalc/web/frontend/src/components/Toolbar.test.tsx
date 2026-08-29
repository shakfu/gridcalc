import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Toolbar } from './Toolbar'
import type { Workbook } from '../hooks/useWorkbook'

function makeWb(overrides: Partial<Workbook> = {}): Workbook {
  return {
    dims: { ncol: 256, nrow: 1024, filename: 'book.json', dirty: false },
    sheets: { active: 0, names: ['Sheet1', 'Data'] },
    status: '',
    statusKind: 'info',
    ready: true,
    dirty: false,
    revision: 0,
    mutations: 0,
    loads: 0,
    notify: vi.fn(),
    fail: vi.fn(),
    markDirty: vi.fn(),
    touched: vi.fn(),
    actions: {
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
    },
    ...overrides,
  }
}

test('Save button calls the save action', async () => {
  const wb = makeWb()
  render(<Toolbar wb={wb} onFormat={() => {}} />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Save' }))
  expect(wb.actions.save).toHaveBeenCalledOnce()
})

test('the Bold button emits a bold format spec', async () => {
  const onFormat = vi.fn()
  render(<Toolbar wb={makeWb()} onFormat={onFormat} />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'B' }))
  expect(onFormat).toHaveBeenCalledWith('b')
})

test('shows the loaded filename', () => {
  render(<Toolbar wb={makeWb()} onFormat={() => {}} />)
  expect(screen.getByText('book.json')).toBeInTheDocument()
})

test('marks the filename when there are unsaved changes', () => {
  render(<Toolbar wb={makeWb({ dirty: true })} onFormat={() => {}} />)
  expect(screen.getByText(/book\.json \*/)).toBeInTheDocument()
})

test('a single-sheet workbook shows a static label, not a dropdown', () => {
  render(<Toolbar wb={makeWb({ sheets: { active: 0, names: ['Sheet1'] } })} onFormat={() => {}} />)
  expect(screen.getByText('Sheet1')).toBeInTheDocument()
  expect(screen.queryByLabelText('Active sheet')).not.toBeInTheDocument()
})

test('toolbar actions are disabled until the bridge is ready', () => {
  render(<Toolbar wb={makeWb({ ready: false })} onFormat={() => {}} />)
  expect(screen.getByRole('button', { name: 'Open' })).toBeDisabled()
})
