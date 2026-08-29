import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { installMockBridge } from './bridge/mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

// The toolbar's active-sheet dropdown, which is how a sheet is switched.
async function toSheet(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole('combobox', { name: 'Active sheet' }))
  await user.click(await screen.findByRole('option', { name }))
}

test('boots the chrome and renders the grid over the bridge', async () => {
  render(<App />)
  // Menubar + toolbar are present.
  expect(screen.getByRole('menuitem', { name: 'File' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument()
  // The grid mounts and shows seeded cell content fetched over the bridge.
  // ('Widget' is a non-active cell, so it is unambiguous vs the formula bar.)
  await waitFor(() => expect(screen.getByText('Widget')).toBeInTheDocument())
})

test('the Bold toolbar button formats the active cell', async () => {
  render(<App />)
  await waitFor(() => screen.getByText('Widget')) // grid ready, selection = A1
  await userEvent.setup().click(screen.getByRole('button', { name: 'B' }))
  await waitFor(() => {
    const cell = [...document.querySelectorAll('.cell')].find(
      (e) => e.textContent === 'gridcalc demo',
    )
    expect(cell?.classList.contains('b')).toBe(true)
  })
})

test('Edit > Delete reaches the grid through the command handle', async () => {
  // The menu items were placeholders until the grid exposed commands; this is
  // the wiring that makes the menu tell the truth about what the app can do.
  const { container } = render(<App />)
  const cells = () => container.querySelector('.cell-layer') as HTMLElement
  await waitFor(() => expect(cells()).toHaveTextContent('gridcalc demo'))

  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Edit' }))
  await user.click(await screen.findByRole('menuitem', { name: 'Delete' }))

  // A1 is the cursor cell, so Delete clears it.
  await waitFor(() => expect(cells()).not.toHaveTextContent('gridcalc demo'))
})

test('an edit marks the workbook modified in the status bar', async () => {
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))
  expect(screen.queryByText('modified')).not.toBeInTheDocument()

  const scroll = container.querySelector('.grid-scroll') as HTMLElement
  scroll.focus()
  await userEvent.setup().keyboard('{Delete}')
  await waitFor(() => expect(screen.getByText('modified')).toBeInTheDocument())
})

test('the status bar summarizes the selection', async () => {
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))
  const scroll = container.querySelector('.grid-scroll') as HTMLElement
  scroll.focus()
  const user = userEvent.setup()
  await user.keyboard('{ArrowRight}{ArrowDown}{ArrowDown}{ArrowDown}') // B4
  await user.keyboard('{Shift>}{ArrowDown}{ArrowDown}{/Shift}') // B4:B6 = 10, 4, 7
  await waitFor(() => expect(screen.getByText('sum 21')).toBeInTheDocument())
})

test('the cursor survives a round trip through another sheet', async () => {
  // Switching sheets remounts the grid, so without a per-sheet stash every tab
  // switch used to land back on A1.
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))
  const nameBox = () => (container.querySelector('.name-box') as HTMLInputElement).value
  const user = userEvent.setup()

  ;(container.querySelector('.grid-scroll') as HTMLElement).focus()
  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowRight}')
  expect(nameBox()).toBe('B3')

  await toSheet(user, 'Data')
  await waitFor(() => expect(nameBox()).toBe('A1')) // never visited, so it starts at A1

  await toSheet(user, 'Sheet1')
  await waitFor(() => expect(nameBox()).toBe('B3'))
})

test('a solve paints the sheet, and editing clears it again', async () => {
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))

  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Data' }))
  await user.click(await screen.findByRole('menuitem', { name: /Optimize/ }))
  await user.click(screen.getByRole('button', { name: 'Solve selection' }))
  await screen.findByTestId('solve-result')
  await waitFor(() => expect(container.querySelectorAll('.annot').length).toBeGreaterThan(0))

  // An edit invalidates the solution, so the annotations must not linger.
  await user.keyboard('{Escape}') // close the dialog
  const scroll = container.querySelector('.grid-scroll') as HTMLElement
  scroll.focus()
  await user.keyboard('{Delete}')
  await waitFor(() => expect(container.querySelectorAll('.annot').length).toBe(0))
})

test('a solve does not follow the user to another sheet', async () => {
  // Annotations are addressed in A1 and painted by position, so leaving them
  // up across a tab switch would mark cells that had nothing to do with the
  // solve -- worse than merely stale.
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))

  const user = userEvent.setup()
  await user.click(screen.getByRole('menuitem', { name: 'Data' }))
  await user.click(await screen.findByRole('menuitem', { name: /Optimize/ }))
  await user.click(screen.getByRole('button', { name: 'Solve selection' }))
  await screen.findByTestId('solve-result')
  await waitFor(() => expect(container.querySelectorAll('.annot').length).toBeGreaterThan(0))

  await user.keyboard('{Escape}') // close the dialog
  await toSheet(user, 'Data')
  await waitFor(() => expect(container.querySelectorAll('.annot').length).toBe(0))

  // And they do not come back on the way home: the solve is over, not paused.
  await toSheet(user, 'Sheet1')
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))
  expect(container.querySelectorAll('.annot').length).toBe(0)
})

test('a renamed sheet keeps the cursor it was left on', async () => {
  // The per-sheet view stash is keyed by sheet name, which a rename changes.
  // It survives because the entry is written on unmount from the closure of
  // the last render, so it lands under the new name -- an invariant worth
  // pinning, since keying the stash differently would quietly break it.
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))
  const nameBox = () => (container.querySelector('.name-box') as HTMLInputElement).value
  const user = userEvent.setup()

  ;(container.querySelector('.grid-scroll') as HTMLElement).focus()
  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowRight}')
  expect(nameBox()).toBe('B3')

  await user.click(screen.getByRole('menuitem', { name: 'Sheet' }))
  await user.click(await screen.findByRole('menuitem', { name: /Rename/ }))
  const input = await screen.findByLabelText('Name')
  await user.clear(input)
  await user.type(input, 'Renamed')
  await user.click(screen.getByRole('button', { name: 'Rename' }))

  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Active sheet' })).toHaveTextContent('Renamed'))
  await toSheet(user, 'Data')
  await waitFor(() => expect(nameBox()).toBe('A1'))
  await toSheet(user, 'Renamed')
  await waitFor(() => expect(nameBox()).toBe('B3'))
})

test('reopening a workbook at the same path resets the cursor', async () => {
  // The grid was keyed on filename alone, so a second open of the same path
  // did not remount it and the cursor stayed where the *previous* workbook had
  // been left -- pointing into a sheet that had since been replaced.
  const { container } = render(<App />)
  await waitFor(() => expect(container.querySelector('.cell-layer')).toHaveTextContent('Widget'))
  const nameBox = () => (container.querySelector('.name-box') as HTMLInputElement).value
  const user = userEvent.setup()

  const openWorkbook = async () => {
    await user.click(screen.getByRole('menuitem', { name: 'File' }))
    await user.click(await screen.findByRole('menuitem', { name: /Open/ }))
  }

  await openWorkbook()
  await waitFor(() => expect(nameBox()).toBe('A1'))

  ;(container.querySelector('.grid-scroll') as HTMLElement).focus()
  await user.keyboard('{ArrowDown}{ArrowDown}{ArrowRight}')
  expect(nameBox()).toBe('B3')

  // Same path as the previous open, so nothing about the key changes but the
  // workbook behind it is new.
  await openWorkbook()
  await waitFor(() => expect(nameBox()).toBe('A1'))
})
