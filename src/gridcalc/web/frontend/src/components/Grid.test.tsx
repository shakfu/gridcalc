import { createRef } from 'react'
import { act, fireEvent, render, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Grid, type GridHandle } from './Grid'
import { bridge } from '../bridge/api'
import { installMockBridge } from '../bridge/mock'
import { CW } from '../lib/grid'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

function renderGrid(props: Partial<Parameters<typeof Grid>[0]> = {}) {
  const utils = render(<Grid ncol={256} nrow={1024} revision={0} {...props} />)
  const scroll = utils.container.querySelector('.grid-scroll') as HTMLElement
  // A1's source also appears in the formula bar, so cell-text assertions are
  // scoped to the cell layer to stay unambiguous.
  const cells = () => within(utils.container.querySelector('.cell-layer') as HTMLElement)
  // The name box and formula bar are inputs (typing a ref jumps; typing a
  // value edits the active cell), so their content is `value`, not text.
  const input = (sel: string) => utils.container.querySelector(sel) as HTMLInputElement
  const nameBox = () => input('.name-box').value
  const formulaBar = () => input('.formula-src').value
  // The in-cell editor and the formula bar mirror the same edit session, so a
  // display-value query would match both -- ask for the cell editor by class.
  const cellEditor = () => input('.cell-editor')
  return { ...utils, scroll, cells, nameBox, formulaBar, cellEditor }
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
  const { cells, scroll, cellEditor } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  const user = userEvent.setup()
  await user.keyboard('{Enter}') // edit A1
  await waitFor(() => expect(cellEditor()).toBeInTheDocument())
  const editor = cellEditor()
  await user.clear(editor)
  await user.type(editor, '42')
  await user.keyboard('{Enter}') // commit
  await waitFor(() => expect(cells().getByText('42')).toBeInTheDocument())
  expect(cells().queryByText('gridcalc demo')).not.toBeInTheDocument()
})

test('a printable key starts editing with that character', async () => {
  const { cells, scroll, cellEditor } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  await userEvent.setup().keyboard('x')
  await waitFor(() => expect(cellEditor()).toHaveValue('x'))
})

test('Delete clears the active cell via clear_range', async () => {
  const { cells, scroll, formulaBar } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  await userEvent.setup().keyboard('{Delete}')
  await waitFor(() => expect(cells().queryByText('gridcalc demo')).not.toBeInTheDocument())
  // The formula bar refreshed too -- the stale source is gone everywhere.
  await waitFor(() => expect(formulaBar()).toBe(''))
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

test('typing a reference in the name box jumps the cursor there', async () => {
  const { container, cells, nameBox } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  const box = container.querySelector('.name-box') as HTMLInputElement
  const user = userEvent.setup()
  await user.clear(box)
  await user.type(box, 'C5{Enter}')
  expect(nameBox()).toBe('C5')
})

test('a bad reference in the name box is refused, not obeyed', async () => {
  const { container, cells, nameBox } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  const box = container.querySelector('.name-box') as HTMLInputElement
  const user = userEvent.setup()
  await user.clear(box)
  await user.type(box, 'not-a-ref{Enter}')
  expect(nameBox()).toBe('not-a-ref') // draft kept so it can be corrected
  await user.tab() // blurring snaps back to where the cursor actually is
  expect(nameBox()).toBe('A1')
})

test('the formula bar edits the active cell', async () => {
  const { container, cells, formulaBar } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  const bar = container.querySelector('.formula-src') as HTMLInputElement
  const user = userEvent.setup()
  await user.clear(bar)
  await user.type(bar, 'edited{Enter}')
  await waitFor(() => expect(cells().getByText('edited')).toBeInTheDocument())
  // The in-cell editor never opened -- the caret stayed in the bar.
  expect(container.querySelector('.cell-editor')).not.toBeInTheDocument()
  expect(formulaBar()).toBe('')  // committing moved down to A2, which is empty
})

test('Escape in the formula bar abandons the edit', async () => {
  const { container, cells, formulaBar } = renderGrid()
  await waitFor(() => cells().getByText('gridcalc demo'))
  const bar = container.querySelector('.formula-src') as HTMLInputElement
  const user = userEvent.setup()
  await user.clear(bar)
  await user.type(bar, 'scrapped{Escape}')
  await waitFor(() => expect(formulaBar()).toBe('gridcalc demo'))
  expect(cells().getByText('gridcalc demo')).toBeInTheDocument()
})

test('the imperative handle drives the same commands as the keyboard', async () => {
  const ref = createRef<GridHandle>()
  const { cells } = renderGrid({ ref })
  await waitFor(() => cells().getByText('gridcalc demo'))

  await act(async () => ref.current?.clear()) // clears A1, the cursor cell
  await waitFor(() => expect(cells().queryByText('gridcalc demo')).not.toBeInTheDocument())

  await act(async () => {
    ref.current?.goto('A4')
    ref.current?.copy()
  })
  await act(async () => {
    ref.current?.goto('D4')
    ref.current?.paste()
  })
  await waitFor(() => expect(cells().queryAllByText('Widget').length).toBe(2))
})

test('a failing bridge call is reported instead of silently swallowed', async () => {
  const onError = vi.fn()
  const api = window.pywebview!.api
  api.set_cell = () => Promise.reject(new Error('engine exploded'))

  const { cells, scroll, cellEditor } = renderGrid({ onError })
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  const user = userEvent.setup()
  await user.keyboard('{Enter}')
  await waitFor(() => expect(cellEditor()).toBeInTheDocument())
  await user.keyboard('9{Enter}')

  await waitFor(() => expect(onError).toHaveBeenCalled())
  expect(String(onError.mock.calls[0][0])).toContain('engine exploded')
})

test('a mutation notifies the app, a plain move does not', async () => {
  const onMutate = vi.fn()
  const { cells, scroll } = renderGrid({ onMutate })
  await waitFor(() => cells().getByText('gridcalc demo'))
  scroll.focus()
  const user = userEvent.setup()

  await user.keyboard('{ArrowDown}{ArrowRight}')
  expect(onMutate).not.toHaveBeenCalled()

  await user.keyboard('{Delete}')
  await waitFor(() => expect(onMutate).toHaveBeenCalled())
})

test('releasing a column-resize drag persists the width and marks the workbook dirty', async () => {
  const onMutate = vi.fn()
  const { container, cells } = renderGrid({ onMutate })
  await waitFor(() => cells().getByText('gridcalc demo'))

  // Widths are per-sheet workbook state, so the release is a mutation: the
  // drag path used to persist without telling the app, leaving the dirty mark
  // clear over a real change.
  const handle = container.querySelector('.col-resize') as HTMLElement
  fireEvent.mouseDown(handle, { clientX: 100 })
  fireEvent.mouseMove(window, { clientX: 160 })
  fireEvent.mouseUp(window)

  await waitFor(() => expect(onMutate).toHaveBeenCalled())
  const { widths } = await bridge.col_widths()
  expect(Number(widths['0'])).toBe(CW + 60)
})

test('solver annotations are painted on the sheet, with hover detail', async () => {
  const { container, cells } = renderGrid({
    annotations: {
      B2: { role: 'objective', title: 'objective = 36' },
      A2: { role: 'decision', title: 'decision A2 = 2' },
      C3: { role: 'binding', title: 'shadow price 1.5 per unit' },
      C2: { role: 'slack', title: 'slack 2 on C2 -- not binding' },
    },
  })
  await waitFor(() => cells().getByText('gridcalc demo'))

  const annots = container.querySelectorAll('.annot')
  expect(annots.length).toBe(4)
  expect(container.querySelector('.annot.binding')).toHaveAttribute(
    'title',
    'shadow price 1.5 per unit',
  )
  // Positioned by reference: C3 is column 2, row 2 (zero-based) -> top 3*22.
  expect((container.querySelector('.annot.binding') as HTMLElement).style.top).toBe('66px')
})

test('a restored view state puts the cursor, selection and scroll back', async () => {
  // The grid is remounted per sheet, so restoring on mount is the whole
  // mechanism by which a sheet switch stops resetting to A1.
  const viewport = vi.fn(window.pywebview!.api.viewport)
  window.pywebview!.api.viewport = viewport

  const { container, nameBox } = renderGrid({
    initialView: { cur: { r: 99, c: 10 }, anchor: { r: 97, c: 10 }, top: 2200, left: 1000 },
  })
  await waitFor(() => expect(viewport).toHaveBeenCalled())

  expect(nameBox()).toBe('K100')
  expect(container.querySelector('.sel-rect')).toBeInTheDocument() // the anchor came back too

  // Scroll offsets are restored before the first fetch, so the rows requested
  // are the ones around the restored position -- not row 0. (happy-dom does no
  // layout -- every box measures zero -- so `scrollTop` is a stored number with
  // no scrolling behind it; what the grid *asks the engine for* is the part
  // that matters and is testable.)
  const [r0, c0] = viewport.mock.calls[0]
  expect(r0).toBe(95) // (2200 - CH) / CH, less the overscan
  expect(c0).toBe(6) // column at x=1000, less the overscan
})

test('leaving the grid reports where the sheet was left', async () => {
  const onViewChange = vi.fn()
  const { container, scroll, unmount } = renderGrid({
    onViewChange,
    initialView: { cur: { r: 0, c: 0 }, anchor: { r: 0, c: 0 }, top: 440, left: 0 },
  })
  // Row 16 is the first fetched at this offset, which is also the proof that
  // the restored scroll drove the fetch.
  await waitFor(() => expect(container.querySelector('.gut')).toHaveTextContent('16'))
  scroll.focus()
  await userEvent.setup().keyboard('{ArrowDown}{ArrowDown}{Shift>}{ArrowRight}{/Shift}')

  expect(onViewChange).not.toHaveBeenCalled() // nothing to stash until it leaves
  unmount()
  expect(onViewChange).toHaveBeenCalledWith({
    cur: { r: 2, c: 1 },
    anchor: { r: 2, c: 0 },
    top: 440,
    left: 0,
  })
})

test('a restored cursor is clamped to the sheet rather than trusted', async () => {
  const { cells, nameBox } = renderGrid({
    initialView: { cur: { r: 5000, c: 900 }, anchor: { r: 5000, c: 900 }, top: 0, left: 0 },
  })
  await waitFor(() => cells().getByText('gridcalc demo'))
  expect(nameBox()).toBe('IV1024') // the last cell of a 256x1024 sheet
})

test('an annotation outside the sheet is skipped rather than misplaced', async () => {
  const { container, cells } = renderGrid({
    annotations: {
      A1: { role: 'decision' },
      'not-a-ref': { role: 'decision' },
    },
  })
  await waitFor(() => cells().getByText('gridcalc demo'))
  expect(container.querySelectorAll('.annot').length).toBe(1)
})
