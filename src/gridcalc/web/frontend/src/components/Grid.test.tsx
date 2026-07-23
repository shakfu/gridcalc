import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Grid } from './Grid'
import { installMockBridge } from '../bridge/mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

function renderGrid() {
  const utils = render(<Grid ncol={256} nrow={1024} revision={0} />)
  const scroll = utils.container.querySelector('.grid-scroll') as HTMLElement
  // A1's source also appears in the formula bar, so cell-text assertions are
  // scoped to the cell layer to stay unambiguous.
  const cells = () => within(utils.container.querySelector('.cell-layer') as HTMLElement)
  const nameBox = () => utils.container.querySelector('.name-box')?.textContent ?? ''
  return { ...utils, scroll, cells, nameBox }
}

test('renders seeded cells fetched from the viewport', async () => {
  const { cells } = renderGrid()
  await waitFor(() => expect(cells().getByText('gridcalc demo')).toBeInTheDocument())
  expect(cells().getByText('Widget')).toBeInTheDocument()
  expect(cells().getByText('Price')).toBeInTheDocument()
})

test('arrow keys move the active cell and update the name box', async () => {
  const { cells, scroll, nameBox } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  expect(nameBox()).toBe('A1')
  await userEvent.setup().keyboard('{ArrowDown}{ArrowDown}{ArrowRight}')
  expect(nameBox()).toBe('B3')
})

test('shift+arrow extends a rectangular selection', async () => {
  const { container, cells, scroll } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  await userEvent.setup().keyboard('{Shift>}{ArrowDown}{ArrowRight}{/Shift}')
  expect(container.querySelector('.sel-rect')).toBeInTheDocument()
})

test('editing a cell commits through set_cell', async () => {
  const { cells, scroll } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  const user = userEvent.setup()
  await user.keyboard('{Enter}') // edit A1
  const editor = await screen.findByDisplayValue('gridcalc demo')
  await user.clear(editor)
  await user.type(editor, '42')
  await user.keyboard('{Enter}') // commit
  await waitFor(() => expect(cells().getByText('42')).toBeInTheDocument())
  expect(cells().queryByText('gridcalc demo')).not.toBeInTheDocument()
})

test('a printable key starts editing with that character', async () => {
  const { cells, scroll } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  await userEvent.setup().keyboard('x')
  expect(await screen.findByDisplayValue('x')).toBeInTheDocument()
})

test('Delete clears the active cell via clear_range', async () => {
  const { container, cells, scroll } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  await userEvent.setup().keyboard('{Delete}')
  await waitFor(() => expect(cells().queryByText('gridcalc demo')).not.toBeInTheDocument())
  // The formula bar refreshed too -- the stale source is gone everywhere.
  expect(container.querySelector('.formula-src')?.textContent).toBe('')
})

test('Ctrl+D fills the selection down', async () => {
  const { cells, scroll } = renderGrid()
  await waitFor(() => cells().getByText('Widget')) // A4
  scroll.focus()
  const user = userEvent.setup()
  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}') // to A4
  await user.keyboard('{Shift>}{ArrowDown}{ArrowDown}{/Shift}') // select A4:A6
  await user.keyboard('{Control>}d{/Control}')
  // A4's value fills A5 and A6, overwriting Gadget/Gizmo.
  await waitFor(() => expect(cells().queryAllByText('Widget').length).toBe(3))
})

test('copy then paste duplicates a cell via the internal buffer', async () => {
  const { cells, scroll } = renderGrid()
  await waitFor(() => cells().getByText('Widget')) // A4
  scroll.focus()
  const user = userEvent.setup()
  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}') // A4
  await user.keyboard('{Control>}c{/Control}') // copy A4
  await user.keyboard('{ArrowRight}{ArrowRight}{ArrowRight}') // D4 (empty)
  await user.keyboard('{Control>}v{/Control}') // paste
  await waitFor(() => expect(cells().queryAllByText('Widget').length).toBe(2))
})
