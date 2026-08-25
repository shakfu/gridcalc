// Distinguishing a *rejected* bridge call from a *refused* one.
//
// The guards in Grid and useWorkbook catch rejections -- the marshalled Python
// call threw -- and return null. But a call can also resolve normally and still
// report that it did nothing: `Api.paste` answers `{ok: false}` when there is no
// clipboard, and several mutators do the same for input they will not accept.
// Treating every non-null result as success marked the workbook dirty, bumped
// the revision and refetched the viewport for a mutation that never happened,
// so the UI showed unsaved changes over an unchanged sheet.

/** The failure reason when `res` is a structured refusal, else null. */
export function failureOf(res: unknown): string | null {
  if (res === null || typeof res !== 'object') return null
  const r = res as { ok?: unknown; error?: unknown }
  if (r.ok !== false) return null
  return typeof r.error === 'string' && r.error ? r.error : 'refused'
}
