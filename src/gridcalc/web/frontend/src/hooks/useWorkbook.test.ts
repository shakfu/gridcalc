import { act, renderHook, waitFor } from '@testing-library/react'
import { useWorkbook } from './useWorkbook'
import { installMockBridge } from '../bridge/mock'
import type { TrustInfo } from '../bridge/types'

const trustInfo = (path: string): TrustInfo => ({
  path,
  name: path.split('/').pop() ?? path,
  cells: 42,
  formulas: 17,
  has_code: true,
  code: 'def f():\n    return 1\n',
  code_lines: 2,
  requires: [],
  blocked: [],
  side_effect: [],
  unknown: [],
})

// The mock bridge holds mutable workbook state; reset it before each test so
// order-dependent mutations (a save recording a filename, an open replacing the
// sheets) do not leak between cases.
beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

test('loads dimensions and sheets once the bridge is ready', async () => {
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  expect(result.current.dims?.ncol).toBe(256)
  expect(result.current.sheets?.names).toEqual(['Sheet1', 'Data'])
})

test('save with no filename falls back to the save dialog', async () => {
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  expect(result.current.dims?.filename).toBe('')
  await act(async () => {
    await result.current.actions.save()
  })
  await waitFor(() => expect(result.current.dims?.filename).toBe('/tmp/mock-workbook.json'))
  expect(result.current.status).toBe('saved')
})

test('open replaces the workbook and refreshes the sheet list', async () => {
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => {
    await result.current.actions.open()
  })
  await waitFor(() => expect(result.current.sheets?.names).toEqual(['Sheet1', 'Budget', 'Data']))
  expect(result.current.dims?.filename).toBe('/tmp/opened.json')
})

test('switching sheets updates the active index', async () => {
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => {
    await result.current.actions.setSheet(1)
  })
  await waitFor(() => expect(result.current.sheets?.active).toBe(1))
})

// A bridge call that *resolves* can still report that it did nothing. These
// wrappers ignored the result and marked the workbook dirty regardless, so the
// status bar and the close-confirmation guard claimed unsaved changes over a
// sheet nothing had touched.
test('a refused format does not mark the workbook dirty', async () => {
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  expect(result.current.dirty).toBe(false)

  window.pywebview!.api.set_format = () =>
    Promise.resolve({ ok: false, error: 'bad format spec' })
  await act(async () => {
    await result.current.actions.format({ r0: 0, c0: 0, r1: 0, c1: 0 }, 'nonsense')
  })
  expect(result.current.dirty).toBe(false)
})

test('an accepted format does mark the workbook dirty', async () => {
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))

  await act(async () => {
    await result.current.actions.format({ r0: 0, c0: 0, r1: 0, c1: 0 }, '0.00')
  })
  expect(result.current.dirty).toBe(true)
})

// --- the trust decision ----------------------------------------------------
// A workbook's code does not run until someone says so, and the hook is what
// carries the question from the bridge to the dialog and the answer back.

test('a startup workbook whose code was withheld raises the decision on boot', async () => {
  window.pywebview!.api.pending_trust = () =>
    Promise.resolve({ needs_trust: true, ...trustInfo('/tmp/hybrid.json') } as const)
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.trust?.path).toBe('/tmp/hybrid.json'))
})

test('nothing is asked when the startup workbook has no code', async () => {
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  expect(result.current.trust).toBeNull()
})

test('opening a file with code asks instead of loading it', async () => {
  window.pywebview!.api.open_dialog = () =>
    Promise.resolve({ ok: false, needs_trust: true, ...trustInfo('/tmp/trust.json') } as const)
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => {
    await result.current.actions.open()
  })
  await waitFor(() => expect(result.current.trust?.path).toBe('/tmp/trust.json'))
  // The workbook on screen is untouched: nothing was loaded.
  expect(result.current.dims?.filename).toBe('')
})

test('approving completes the open with the policy', async () => {
  const calls: unknown[] = []
  window.pywebview!.api.open_file = (path: string, policy?: unknown) => {
    calls.push([path, policy])
    return Promise.resolve({ ok: true, filename: path })
  }
  window.pywebview!.api.open_dialog = () =>
    Promise.resolve({ ok: false, needs_trust: true, ...trustInfo('/tmp/trust.json') } as const)
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => {
    await result.current.actions.open()
  })
  await act(async () => {
    await result.current.actions.resolveTrust({ load_code: true, allow_unknown: false })
  })
  expect(calls).toEqual([['/tmp/trust.json', { load_code: true, allow_unknown: false }]])
  expect(result.current.trust).toBeNull()
  expect(result.current.status).toBe('opened with code')
})

test('cancelling loads nothing', async () => {
  let opened = 0
  window.pywebview!.api.open_file = (path: string) => {
    opened += 1
    return Promise.resolve({ ok: true, filename: path })
  }
  window.pywebview!.api.open_dialog = () =>
    Promise.resolve({ ok: false, needs_trust: true, ...trustInfo('/tmp/trust.json') } as const)
  const { result } = renderHook(() => useWorkbook())
  await waitFor(() => expect(result.current.ready).toBe(true))
  await act(async () => {
    await result.current.actions.open()
  })
  await act(async () => {
    await result.current.actions.resolveTrust(null)
  })
  expect(opened).toBe(0)
  expect(result.current.trust).toBeNull()
})
