import { render, screen, waitFor } from '@testing-library/react'
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
