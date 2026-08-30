import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TrustDialog } from './TrustDialog'
import type { TrustInfo } from '../bridge/types'

const INFO: TrustInfo = {
  path: '/tmp/book.json',
  name: 'book.json',
  cells: 42,
  formulas: 17,
  has_code: true,
  code: 'def rate(x):\n    return x * 0.07\n',
  code_lines: 2,
  requires: ['numpy', 'requests', 'socket', 'mystery'],
  blocked: ['socket'],
  side_effect: ['requests'],
  unknown: ['mystery'],
}

function show(info: Partial<TrustInfo> = {}) {
  const onDecide = vi.fn()
  render(<TrustDialog info={{ ...INFO, ...info }} onDecide={onDecide} />)
  return { onDecide, user: userEvent.setup() }
}

test('nothing is shown when there is no decision to make', () => {
  render(<TrustDialog info={null} onDecide={vi.fn()} />)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('names the file and shows the code that would run', () => {
  show()
  expect(screen.getByText(/Run code from book.json/)).toBeInTheDocument()
  // The code itself, not a summary of it: it is the only thing that lets a
  // user judge the decision.
  expect(screen.getByLabelText('Code block')).toHaveTextContent('return x * 0.07')
})

test('modules are split by how much is known about them', () => {
  show()
  expect(screen.getByText('numpy')).toBeInTheDocument() // classified safe
  expect(screen.getByText('requests')).toBeInTheDocument() // I/O
  expect(screen.getByText('mystery')).toBeInTheDocument() // unclassified
  expect(screen.getByText(/socket .* never imported/)).toBeInTheDocument()
})

test('approving loads the code', async () => {
  const { onDecide, user } = show()
  await user.click(screen.getByRole('button', { name: 'Run code' }))
  expect(onDecide).toHaveBeenCalledWith({ load_code: true, allow_unknown: false })
})

test('unclassified modules need their own answer', async () => {
  const { onDecide, user } = show()
  await user.click(screen.getByRole('checkbox'))
  await user.click(screen.getByRole('button', { name: 'Run code' }))
  expect(onDecide).toHaveBeenCalledWith({ load_code: true, allow_unknown: true })
})

test('no checkbox when every module is classified', () => {
  show({ requires: ['numpy'], blocked: [], side_effect: [], unknown: [] })
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
})

test('formulas only declines the code without cancelling the open', async () => {
  const { onDecide, user } = show()
  await user.click(screen.getByRole('button', { name: 'Formulas only' }))
  expect(onDecide).toHaveBeenCalledWith({ load_code: false })
})

test('cancel answers null', async () => {
  const { onDecide, user } = show()
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(onDecide).toHaveBeenCalledWith(null)
})

// Dismissing has to mean the safe thing, not an unanswered question: the
// workbook stays as it is, formulas only.
test('escape answers null too', async () => {
  const { onDecide, user } = show()
  await user.keyboard('{Escape}')
  expect(onDecide).toHaveBeenCalledWith(null)
})

test('the unknown-module answer does not carry across files', async () => {
  const onDecide = vi.fn()
  const { rerender } = render(<TrustDialog info={INFO} onDecide={onDecide} />)
  await userEvent.setup().click(screen.getByRole('checkbox'))
  expect(screen.getByRole('checkbox')).toBeChecked()
  rerender(<TrustDialog info={{ ...INFO, path: '/tmp/other.json' }} onDecide={onDecide} />)
  expect(screen.getByRole('checkbox')).not.toBeChecked()
})
