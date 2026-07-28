import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { OptimizeDialog } from './OptimizeDialog'
import { installMockBridge } from '../bridge/mock'
import type { Selection } from '../lib/grid'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

const SEL: Selection = { r0: 0, c0: 0, r1: 3, c1: 2, ref: 'A1:C4', active: 'A1' }

function renderDialog(over: Partial<Parameters<typeof OptimizeDialog>[0]> = {}) {
  const onAnnotations = vi.fn()
  const onMutated = vi.fn()
  render(
    <OptimizeDialog
      open
      onOpenChange={() => {}}
      selection={SEL}
      onAnnotations={onAnnotations}
      onMutated={onMutated}
      {...over}
    />,
  )
  return { onAnnotations, onMutated }
}

// "Solve" and "Solve selection" are both present; anchor the exact one.
const SOLVE = /^Solve$/

async function fillModel(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Objective'), 'B2')
  await user.type(screen.getByLabelText('Decision variables'), 'A2:A3')
  await user.type(screen.getByLabelText('Constraints'), 'C2:C4')
}

test('solving the selection renders the objective and sensitivity tables', async () => {
  renderDialog()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Solve selection' }))
  const view = within(await screen.findByTestId('solve-result'))
  expect(view.getByText('OPTIMAL')).toBeInTheDocument()
  expect(view.getByText(/objective = 36/)).toBeInTheDocument()
  expect(view.getByText('1.5')).toBeInTheDocument() // C3's shadow price
  expect(view.getAllByText('inf').length).toBeGreaterThan(0) // a null ranging bound
})

test('shows the selection range in the description', () => {
  renderDialog()
  expect(screen.getByText(/A1:C4/)).toBeInTheDocument()
})

test('reading from the selection fills the model without solving', async () => {
  renderDialog()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Read from selection' }))
  await waitFor(() => expect(screen.getByLabelText('Objective')).toHaveValue('B2'))
  expect(screen.getByLabelText('Decision variables')).toHaveValue('A2:A3')
  expect(screen.getByLabelText('Constraints')).toHaveValue('C2:C4')
  // Nothing ran, so there is no result panel.
  expect(screen.queryByTestId('solve-result')).not.toBeInTheDocument()
})

test('a model can be saved, listed, and reloaded', async () => {
  renderDialog()
  const user = userEvent.setup()
  await fillModel(user)
  await user.type(screen.getByLabelText('Model name'), 'wyndor')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  await screen.findByText('saved wyndor')

  // It appears in the workbook's model list and reloads into the fields.
  const select = screen.getByLabelText('Saved models')
  await waitFor(() => expect(within(select).getByText('wyndor')).toBeInTheDocument())
  await user.clear(screen.getByLabelText('Objective'))
  await user.selectOptions(select, 'wyndor')
  await waitFor(() => expect(screen.getByLabelText('Objective')).toHaveValue('B2'))
})

test('saving an incomplete model reports why', async () => {
  renderDialog()
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Model name'), 'partial')
  await user.type(screen.getByLabelText('Objective'), 'B2')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText(/missing required field/)).toBeInTheDocument()
})

test('a saved model can be deleted', async () => {
  renderDialog()
  const user = userEvent.setup()
  await fillModel(user)
  await user.type(screen.getByLabelText('Model name'), 'gone')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  await screen.findByText('saved gone')
  await user.click(screen.getByRole('button', { name: 'Delete' }))
  await screen.findByText('deleted gone')
  expect(screen.getByLabelText('Objective')).toHaveValue('')
})

test('a solve publishes grid annotations and explains them', async () => {
  const { onAnnotations } = renderDialog()
  const user = userEvent.setup()
  await fillModel(user)
  await user.click(screen.getByRole('button', { name: SOLVE }))
  await screen.findByTestId('solve-result')

  const annotations = onAnnotations.mock.calls.at(-1)?.[0] as Record<
    string,
    { role: string; title?: string }
  >
  expect(annotations.B2.role).toBe('objective')
  expect(annotations.A2.role).toBe('decision')
  expect(annotations.C3.role).toBe('binding') // shadow price 1.5, slack 0
  expect(annotations.C3.title).toContain('shadow price')
  expect(annotations.C2.role).toBe('slack') // slack 2, not binding

  // The legend names only the roles actually painted.
  const legend = within(screen.getByTestId('annot-legend'))
  expect(legend.getByText('binding')).toBeInTheDocument()
  expect(legend.getByText('slack')).toBeInTheDocument()
})

test('an applied solve reports the write so the grid can refetch', async () => {
  const { onMutated } = renderDialog()
  const user = userEvent.setup()
  await fillModel(user)
  await user.click(screen.getByRole('button', { name: SOLVE }))
  await waitFor(() => expect(onMutated).toHaveBeenCalled())
})

test('a bridge failure is shown rather than swallowed', async () => {
  window.pywebview!.api.solve_model = () => Promise.reject(new Error('solver missing'))
  renderDialog()
  const user = userEvent.setup()
  await fillModel(user)
  await user.click(screen.getByRole('button', { name: SOLVE }))
  expect(await screen.findByText('solver missing')).toBeInTheDocument()
})
