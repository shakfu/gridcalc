// The solver result rendering shared by every path that runs a solve --
// status, objective, decision values, and the sensitivity tables.
import type { SolveResult } from '../bridge/types'
import { fmtCell, fnum } from '../lib/format'

interface Col {
  key: string
  head: string
  kind?: 'k' | 'bool'
}

const VAR_COLS: Col[] = [
  { key: 'cell', head: 'cell', kind: 'k' },
  { key: 'value', head: 'value' },
  { key: 'reduced_cost', head: 'reduced cost' },
  { key: 'obj_coef', head: 'obj coef' },
  { key: 'obj_from', head: 'obj from' },
  { key: 'obj_till', head: 'obj till' },
]

const CON_COLS: Col[] = [
  { key: 'cell', head: 'cell', kind: 'k' },
  { key: 'shadow_price', head: 'shadow price' },
  { key: 'rhs', head: 'rhs' },
  { key: 'slack', head: 'slack' },
  { key: 'binding', head: 'binding', kind: 'bool' },
  { key: 'rhs_from', head: 'rhs from' },
  { key: 'rhs_till', head: 'rhs till' },
]

function SensTable({ rows, cols }: { rows: readonly object[]; cols: Col[] }) {
  return (
    <table className="sens">
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c.key} className={c.kind === 'k' ? 'k' : ''}>
              {c.head}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {cols.map((c) => (
              <td key={c.key} className={c.kind === 'k' ? 'k' : ''}>
                {fmtCell((row as Record<string, unknown>)[c.key], c.kind)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function SolveResultView({ result, sense }: { result: SolveResult; sense: string }) {
  if (!result.ok) return <p className="error">{result.error}</p>
  const values = result.values ?? {}
  return (
    <div className="solve-result" data-testid="solve-result">
      <div className="result-head">
        <span className={'badge ' + (result.optimal ? 'ok' : 'bad')}>{result.status}</span>
        {result.optimal && (
          <span className="result-obj">
            {sense} objective = {fnum(result.objective)}
          </span>
        )}
      </div>

      {result.optimal && Object.keys(values).length > 0 && (
        <SensTable
          rows={Object.entries(values).map(([cell, value]) => ({ cell, value }))}
          cols={[
            { key: 'cell', head: 'cell', kind: 'k' },
            { key: 'value', head: 'value' },
          ]}
        />
      )}

      {result.sensitivity ? (
        <>
          <div className="panel-subtitle">Variables</div>
          <SensTable rows={result.sensitivity.variables} cols={VAR_COLS} />
          <div className="panel-subtitle">Constraints</div>
          <SensTable rows={result.sensitivity.constraints} cols={CON_COLS} />
        </>
      ) : result.optimal ? (
        <p className="sens-note">No sensitivity for integer models.</p>
      ) : null}

      {result.conflict && (
        <p className="diag">Conflicting constraints: {result.conflict.join(', ')}</p>
      )}
      {result.unbounded && (
        <p className="diag">
          Unbounded variables: {result.unbounded.join(', ') || '(unidentified)'}
        </p>
      )}
    </div>
  )
}
