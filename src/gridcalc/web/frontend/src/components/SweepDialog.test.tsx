import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SweepDialog } from './SweepDialog'
import { installMockBridge } from '../bridge/mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

async function fillModel(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByPlaceholderText('B2'), 'B2')
  await user.type(screen.getByPlaceholderText('A2:A3'), 'A2:A3')
  await user.type(screen.getByPlaceholderText('C3'), 'C3')
  await user.type(screen.getByPlaceholderText('0'), '0')
  await user.type(screen.getByPlaceholderText('24'), '24')
}

test('runs a sweep and renders the points, flagging breakpoints', async () => {
  render(<SweepDialog open onOpenChange={() => {}} />)
  const user = userEvent.setup()
  await fillModel(user)
  await user.click(screen.getByRole('button', { name: 'Run' }))

  await waitFor(() => expect(screen.getByTestId('sweep-table')).toBeInTheDocument())
  const rows = screen.getAllByRole('row').slice(1) // drop the header
  expect(rows).toHaveLength(3)
  expect(rows[2]).toHaveTextContent('yes') // the mock's third point is a breakpoint
  expect(rows[2]).toHaveClass('breakpoint')
})

test('an incomplete model is refused before reaching the bridge', async () => {
  render(<SweepDialog open onOpenChange={() => {}} />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Run' }))
  expect(await screen.findByText(/fill in objective/)).toBeInTheDocument()
  expect(screen.queryByTestId('sweep-table')).not.toBeInTheDocument()
})

test('a bridge failure is shown rather than swallowed', async () => {
  window.pywebview!.api.opt_sweep = () => Promise.reject(new Error('solver missing'))
  render(<SweepDialog open onOpenChange={() => {}} />)
  const user = userEvent.setup()
  await fillModel(user)
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(await screen.findByText('solver missing')).toBeInTheDocument()
})

// See GoalDialog: these were labelled by adjacent text only.
test('every field has an accessible name', () => {
  render(<SweepDialog open onOpenChange={() => {}} />)
  for (const name of [
    'Objective',
    'Vars',
    'Constraints',
    'Sweep constraint',
    'RHS from',
    'RHS to',
    'Steps',
  ]) {
    expect(screen.getByLabelText(name)).toBeInTheDocument()
  }
})
