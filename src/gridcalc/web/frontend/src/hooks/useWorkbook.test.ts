import { act, renderHook, waitFor } from '@testing-library/react'
import { useWorkbook } from './useWorkbook'
import { installMockBridge } from '../bridge/mock'

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
