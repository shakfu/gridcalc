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
