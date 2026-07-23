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
