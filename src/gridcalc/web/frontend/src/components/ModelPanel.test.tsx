import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EditorView } from 'codemirror'
import { ModelPanel } from './ModelPanel'
import { bridge } from '../bridge/api'
import { installMockBridge } from '../bridge/mock'

// The panel polls every 250 ms; under a loaded test run two polls can pass 1 s.
const POLL_WAIT = { timeout: 4000 }

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

// `vi.spyOn` on a method already spied returns the old spy, call history and all.
afterEach(() => {
  vi.restoreAllMocks()
})

function renderPanel(over: Partial<Parameters<typeof ModelPanel>[0]> = {}) {
  const props = {
    revision: '0',
    showModel: false,
    onShowModel: vi.fn(),
    onClose: vi.fn(),
    onMutated: vi.fn(),
    onEdited: vi.fn(),
    notify: vi.fn(),
    fail: vi.fn(),
    ...over,
  }
  const utils = render(<ModelPanel {...props} />)
  return { ...utils, props }
}

test('loads the model into a Python editor', async () => {
  await bridge.set_model('prob = 1\n')
  const { container } = renderPanel()
  await waitFor(() => expect(container.querySelector('.cm-content')).toHaveTextContent('prob = 1'))
  expect(screen.getByText('Model - Sheet1')).toBeInTheDocument()
  // Python highlighting is on: the editor tags the language.
  expect(container.querySelector('.cm-content')).toHaveAttribute('data-language', 'python')
})

test('solve runs in the background, then reports and refetches', async () => {
  await bridge.set_model('prob = 1\n')
  const { props } = renderPanel()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Solve' }))
  expect(await screen.findByRole('button', { name: 'Cancel' })).toBeInTheDocument()
  await waitFor(
    () => expect(props.notify).toHaveBeenCalledWith('Optimal, objective 8400, 11 cells written'),
    POLL_WAIT,
  )
  expect(props.onMutated).toHaveBeenCalledOnce()
  expect(screen.getByLabelText('Model output')).toHaveTextContent('11 cells written')
  expect(screen.getByRole('button', { name: 'Solve' })).toBeInTheDocument()
})

test('a failed run reports through fail', async () => {
  await bridge.set_model('x = 1\nraise ValueError("bad")\n')
  const { props } = renderPanel()
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Solve' }))
  await waitFor(() => expect(vi.mocked(props.fail).mock.calls).toEqual([['line 2: ValueError: bad']]), POLL_WAIT)
  expect(props.onMutated).not.toHaveBeenCalled()
})

test('solve with no model fails without starting', async () => {
  const { props } = renderPanel()
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Solve' }))
  await waitFor(() => expect(props.fail).toHaveBeenCalledWith('sheet Sheet1 has no model'))
  expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull()
})

test('cancel stops the run', async () => {
  await bridge.set_model('prob = 1\n')
  const cancel = vi.spyOn(bridge, 'cancel_solve')
  renderPanel()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Solve' }))
  await user.click(await screen.findByRole('button', { name: 'Cancel' }))
  expect(cancel).toHaveBeenCalledOnce()
})

test('shows problems and toggles the overlay', async () => {
  await bridge.set_model('import os\n')
  const { props } = renderPanel()
  expect(await screen.findByText(/import of 'os' is blocked/)).toBeInTheDocument()
  await userEvent.setup().click(screen.getByLabelText('Show model'))
  expect(props.onShowModel).toHaveBeenCalledWith(true)
})

test('an edit is saved after a pause and marks the workbook dirty', async () => {
  const set = vi.spyOn(bridge, 'set_model')
  const { container, props } = renderPanel()
  const el = await waitFor(() => {
    const e = container.querySelector('.cm-editor') as HTMLElement
    expect(e).not.toBeNull()
    return e
  })
  // happy-dom cannot drive CodeMirror's contenteditable input, so the edit
  // goes in as a transaction: the same path a keystroke ends in.
  const view = EditorView.findFromDOM(el)
  view?.dispatch({ changes: { from: 0, insert: 'x = 2' } })
  await waitFor(() => expect(set).toHaveBeenCalledWith('x = 2'), { timeout: 2000 })
  expect(props.onEdited).toHaveBeenCalled()
})

test('a closed panel leaves the result for the next one', async () => {
  await bridge.set_model('prob = 1\n')
  const { unmount } = renderPanel()
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Solve' }))
  unmount()
  await new Promise((r) => setTimeout(r, 600))
  const { props } = renderPanel()
  await waitFor(() =>
    expect(props.notify).toHaveBeenCalledWith('Optimal, objective 8400, 11 cells written'),
    POLL_WAIT,
  )
})

test('loading the model is not an edit', async () => {
  await bridge.set_model('prob = 1\n')
  const set = vi.spyOn(bridge, 'set_model')
  const { container, props, unmount } = renderPanel()
  await waitFor(() => expect(container.querySelector('.cm-content')).toHaveTextContent('prob = 1'))
  await new Promise((r) => setTimeout(r, 500))
  unmount()
  expect(set).not.toHaveBeenCalled()
  expect(props.onEdited).not.toHaveBeenCalled()
})

test('closing the panel saves text typed in the last pause', async () => {
  const set = vi.spyOn(bridge, 'set_model')
  const { container, unmount } = renderPanel()
  const el = await waitFor(() => {
    const e = container.querySelector('.cm-editor') as HTMLElement
    expect(e).not.toBeNull()
    return e
  })
  EditorView.findFromDOM(el)?.dispatch({ changes: { from: 0, insert: 'y = 3' } })
  unmount()
  expect(set).toHaveBeenCalledWith('y = 3')
})


test('output appears while the model runs', async () => {
  await bridge.set_model('prob = 1\n')
  renderPanel()
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Solve' }))
  await waitFor(() => expect(screen.getByLabelText('Model output')).toHaveTextContent('working'))
  // Replaced by the full result at the end.
  await waitFor(
    () => expect(screen.getByLabelText('Model output')).toHaveTextContent('11 cells written'),
    POLL_WAIT,
  )
})


test('the backend selector switches to the PuLP library', async () => {
  const set = vi.spyOn(bridge, 'set_model_backend')
  const { props } = renderPanel()
  const select = await screen.findByLabelText('Model backend')
  expect(select).toHaveValue('builtin')
  await userEvent.setup().selectOptions(select, 'pulp')
  expect(set).toHaveBeenCalledWith('pulp')
  await waitFor(() => expect(select).toHaveValue('pulp'))
  expect(props.onEdited).toHaveBeenCalled()
  expect((await bridge.model()).backend).toBe('pulp')
})
