import { render, screen, waitFor } from '@testing-library/react'
import { StatusBar } from './StatusBar'
import { installMockBridge } from '../bridge/mock'
import type { Selection } from '../lib/grid'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

// The seeded mock workbook has 10 / 4 / 7 down column B (rows 4-6).
const QTY: Selection = { r0: 3, c0: 1, r1: 5, c1: 1, ref: 'B4:B6', active: 'B4' }

function renderBar(over: Partial<Parameters<typeof StatusBar>[0]> = {}) {
  return render(
    <StatusBar
      selection={null}
      status=""
      statusKind="info"
      dirty={false}
      revision={0}
      {...over}
    />,
  )
}

test('shows the selection reference', async () => {
  renderBar({ selection: QTY })
  expect(await screen.findByText('B4:B6')).toBeInTheDocument()
})

test('aggregates the numeric cells in the selection', async () => {
  renderBar({ selection: QTY })
  await waitFor(() => expect(screen.getByText('sum 21')).toBeInTheDocument())
  expect(screen.getByText('avg 7')).toBeInTheDocument()
  expect(screen.getByText('min 4')).toBeInTheDocument()
  expect(screen.getByText('max 10')).toBeInTheDocument()
  expect(screen.getByText('count 3')).toBeInTheDocument()
  expect(screen.getByText('3 cells')).toBeInTheDocument()
})

test('a selection with no numbers shows no aggregates', async () => {
  // A1 holds the label "gridcalc demo".
  renderBar({ selection: { r0: 0, c0: 0, r1: 0, c1: 0, ref: 'A1', active: 'A1' } })
  await screen.findByText('A1')
  await waitFor(() => expect(screen.queryByText(/^sum /)).not.toBeInTheDocument())
})

test('an error is announced, not just coloured', () => {
  renderBar({ status: 'engine exploded', statusKind: 'error' })
  const msg = screen.getByRole('status')
  expect(msg).toHaveTextContent('engine exploded')
  expect(msg).toHaveClass('error')
  expect(msg).toHaveAttribute('aria-live', 'polite')
})

test('unsaved changes are visible in the status bar', () => {
  renderBar({ dirty: true })
  expect(screen.getByText('modified')).toBeInTheDocument()
})
