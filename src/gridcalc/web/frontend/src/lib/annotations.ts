import type { SolveResult } from '../bridge/types'
import type { CellAnnotation } from './grid'
import { fnum } from './format'

// Turn a solve result into per-cell annotations for the grid.
//
// The results panel already tabulates all of this. The point of also painting
// it on the sheet is that a shadow price means far more sitting on the
// constraint row it belongs to than in a column of numbers -- which constraints
// bind, and therefore where the model is actually tight, becomes something you
// read off the layout rather than reconstruct from cell references.
export function annotationsFrom(
  result: SolveResult | null,
  objectiveRef?: string,
): Record<string, CellAnnotation> {
  const out: Record<string, CellAnnotation> = {}
  if (!result?.ok || !result.optimal) return out

  for (const [cell, value] of Object.entries(result.values ?? {})) {
    out[cell] = { role: 'decision', title: `decision ${cell} = ${fnum(value)}` }
  }

  // Reduced costs refine the decision cells rather than adding new ones: a
  // non-basic variable at a bound is the interesting case, so say so.
  for (const v of result.sensitivity?.variables ?? []) {
    const parts = [`decision ${v.cell} = ${fnum(v.value)}`]
    if (v.reduced_cost) parts.push(`reduced cost ${fnum(v.reduced_cost)}`)
    parts.push(`obj coef ${fnum(v.obj_coef)} in [${fnum(v.obj_from)}, ${fnum(v.obj_till)}]`)
    out[v.cell] = { role: 'decision', title: parts.join('\n') }
  }

  for (const c of result.sensitivity?.constraints ?? []) {
    out[c.cell] = c.binding
      ? {
          role: 'binding',
          title:
            `binding: ${c.cell} at its limit ${fnum(c.rhs)}\n` +
            `shadow price ${fnum(c.shadow_price)} per unit\n` +
            `valid for rhs in [${fnum(c.rhs_from)}, ${fnum(c.rhs_till)}]`,
        }
      : { role: 'slack', title: `slack ${fnum(c.slack)} on ${c.cell} -- not binding` }
  }

  if (objectiveRef) {
    out[objectiveRef] = {
      role: 'objective',
      title: `objective = ${fnum(result.objective)}`,
    }
  }
  return out
}

// Which roles are actually present, so the legend only explains what is drawn.
export function rolesUsed(annotations: Record<string, CellAnnotation>): string[] {
  const order = ['objective', 'decision', 'binding', 'slack']
  const seen = new Set(Object.values(annotations).map((a) => a.role))
  return order.filter((r) => seen.has(r as CellAnnotation['role']))
}
