import { failureOf } from './result'

// A rejected call is caught by the guards and becomes null. A *refusal* --
// `{ok: false}` from an empty clipboard or input the engine will not accept --
// resolves normally, and treating it as success marked the workbook dirty for a
// mutation that never happened.

test('a structured refusal is reported', () => {
  expect(failureOf({ ok: false, error: 'nothing to paste' })).toBe('nothing to paste')
})

test('a refusal with no message still reads as a failure', () => {
  expect(failureOf({ ok: false })).toBe('refused')
})

test('a success is not a failure', () => {
  expect(failureOf({ ok: true })).toBeNull()
  expect(failureOf({ ok: true, dirty: true })).toBeNull()
})

test('a result with no ok field is not a failure', () => {
  // Plenty of bridge calls answer with plain data and no envelope.
  expect(failureOf({ rows: 10, cols: 4 })).toBeNull()
  expect(failureOf([])).toBeNull()
})

test('non-objects are not failures', () => {
  expect(failureOf(null)).toBeNull()
  expect(failureOf(undefined)).toBeNull()
  expect(failureOf('text')).toBeNull()
  expect(failureOf(0)).toBeNull()
})
