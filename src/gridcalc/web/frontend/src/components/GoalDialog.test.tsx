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

// `parseFloat('1,5')` is 1, and `parseFloat('abc')` is NaN, which crosses the
// bridge as null -- both used to run a seek on a number the user never typed.
test.each(['1,5', 'abc', '5x'])('refuses a target of %s instead of guessing', async (bad) => {
  const seek = vi.spyOn(window.pywebview!.api, 'goal_seek')
  render(<GoalDialog open onOpenChange={() => {}} activeRef="B1" />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('To value'), bad)
  await user.type(screen.getByLabelText('By cell'), 'A1')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(screen.getByText(/not a number/)).toBeInTheDocument()
  expect(seek).not.toHaveBeenCalled()
})

test('refuses a bracket that is not a number', async () => {
  const seek = vi.spyOn(window.pywebview!.api, 'goal_seek')
  render(<GoalDialog open onOpenChange={() => {}} activeRef="B1" />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('To value'), '10')
  await user.type(screen.getByLabelText('By cell'), 'A1')
  await user.type(screen.getByLabelText('Bracket low'), '1,5')
  await user.click(screen.getByRole('button', { name: 'Run' }))
  expect(screen.getByText(/not a number/)).toBeInTheDocument()
  expect(seek).not.toHaveBeenCalled()
})

test('Run is disabled while a seek is in flight', async () => {
  let finish = () => {}
  const seek = vi.fn(
    () =>
      new Promise<{ ok: boolean }>((res) => {
        finish = () => res({ ok: false })
      }),
  )
  window.pywebview!.api.goal_seek = seek
  render(<GoalDialog open onOpenChange={() => {}} activeRef="B1" />)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('To value'), '10')
  await user.type(screen.getByLabelText('By cell'), 'A1')
  const run = screen.getByRole('button', { name: 'Run' })
  await user.click(run)
  expect(run).toBeDisabled()
  await user.click(run)
  expect(seek).toHaveBeenCalledOnce()
  finish()
  await waitFor(() => expect(run).not.toBeDisabled())
})
