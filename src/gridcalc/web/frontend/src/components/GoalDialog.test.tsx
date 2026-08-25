import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { GoalDialog } from './GoalDialog'
import { installMockBridge } from '../bridge/mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

test('prefills the active cell and runs goal seek', async () => {
  render(<GoalDialog open onOpenChange={() => {}} activeRef="B1" />)
  const user = userEvent.setup()
  expect(screen.getByPlaceholderText('B1')).toHaveValue('B1') // set-cell prefilled
  await user.type(screen.getByPlaceholderText('0'), '10')
  await user.type(screen.getByPlaceholderText('A1'), 'A1')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  // mock: var_value = target/2 = 5, formula_value = 10
  await waitFor(() => expect(screen.getByText(/A1 = 5/)).toBeInTheDocument())
})

test('requires the three cells before running', async () => {
  render(<GoalDialog open onOpenChange={() => {}} activeRef="" />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Run' }))
  expect(screen.getByText(/fill in set/)).toBeInTheDocument()
})

// The fields were labelled only by an adjacent <span>, which is visual
// adjacency and not an accessible name -- a screen reader announced five
// unnamed text boxes. `getByLabelText` fails unless each input has a real one.
test('every field has an accessible name', () => {
  render(<GoalDialog open onOpenChange={() => {}} activeRef="B1" />)
  for (const name of ['Set cell', 'To value', 'By cell', 'Bracket low', 'Bracket high']) {
    expect(screen.getByLabelText(name)).toBeInTheDocument()
  }
})
