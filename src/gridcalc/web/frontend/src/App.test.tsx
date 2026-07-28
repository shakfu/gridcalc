import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { App } from './App'
import { installMockBridge } from './bridge/mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

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
