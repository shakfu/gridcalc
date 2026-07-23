import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChartDialog } from './ChartDialog'
import { installMockBridge } from '../bridge/mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

test('drawing a valid range builds the chart', async () => {
  render(<ChartDialog open onOpenChange={() => {}} rangeRef="A4:C6" />)
  expect(screen.getByPlaceholderText('A4:D6')).toHaveValue('A4:C6')
  await userEvent.setup().click(screen.getByRole('button', { name: 'Draw' }))
  await waitFor(() => expect(screen.getByTestId('chart-box')).toBeInTheDocument())
})

test('a bad range shows an error', async () => {
  render(<ChartDialog open onOpenChange={() => {}} rangeRef="nonsense" />)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Draw' }))
  await waitFor(() => expect(screen.getByText(/bad range/)).toBeInTheDocument())
})
