import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ResultsDialog } from './ResultsDialog'
import { installMockBridge } from '../bridge/mock'
import type { Selection } from '../lib/grid'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

const SEL: Selection = { r0: 0, c0: 0, r1: 3, c1: 2, ref: 'A1:C4', active: 'A1' }

test('solving the selection renders the objective and sensitivity tables', async () => {
  render(<ResultsDialog open onOpenChange={() => {}} selection={SEL} />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Solve' }))
  const result = await screen.findByTestId('solve-result')
  const view = within(result)
  expect(view.getByText('OPTIMAL')).toBeInTheDocument()
  expect(view.getByText(/objective = 36/)).toBeInTheDocument()
  // Constraint sensitivity: C3's shadow price and a null ranging bound as inf.
  expect(view.getByText('1.5')).toBeInTheDocument()
  expect(view.getAllByText('inf').length).toBeGreaterThan(0)
})

test('shows the selection range in the description', () => {
  render(<ResultsDialog open onOpenChange={() => {}} selection={SEL} />)
  expect(screen.getByText(/A1:C4/)).toBeInTheDocument()
})
