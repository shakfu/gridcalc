import { useCallback, useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { bridge } from '../bridge/api'
import type { ModelSpec, SavedModel, SolveResult } from '../bridge/types'
import type { CellAnnotation, Selection } from '../lib/grid'
import { annotationsFrom, rolesUsed } from '../lib/annotations'
import { SolveResultView } from './SolveResultView'

// A blank model, and the shape the fields edit. Everything is a spec *string*,
// matching how the engine persists a model -- cell refs resolve at solve time.
const EMPTY: SavedModel = {
  name: '',
  sense: 'max',
  objective: '',
  vars: '',
  constraints: '',
  bounds: '',
  integers: '',
  binaries: '',
}

function toSpec(m: SavedModel): ModelSpec {
  return {
    sense: m.sense,
    objective: m.objective,
    vars: m.vars,
    constraints: m.constraints,
    bounds: m.bounds ?? '',
    integers: m.integers ?? '',
    binaries: m.binaries ?? '',
  }
}

// The optimization workspace: define a model (by hand, inferred from a block on
// the sheet, or loaded from one saved in the workbook), solve it, and read the
// result both as tables and painted onto the grid.
//
// Models are workbook state, not dialog state: one saved here is the same
// object the TUI's `:opt run <name>` executes, and it survives save/reopen.
export function OptimizeDialog({
  open,
  onOpenChange,
  selection,
  onAnnotations,
  onMutated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  selection: Selection | null
  onAnnotations?: (annotations: Record<string, CellAnnotation>) => void
  // An applied solve overwrote the decision cells; the grid must refetch.
  onMutated?: () => void
}) {
  const [model, setModel] = useState<SavedModel>(EMPTY)
  const [saved, setSaved] = useState<SavedModel[]>([])
  const [result, setResult] = useState<SolveResult | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [applyToSheet, setApplyToSheet] = useState(true)

  const set = <K extends keyof SavedModel>(k: K, v: SavedModel[K]) =>
    setModel((m) => ({ ...m, [k]: v }))

  const refreshModels = useCallback(async () => {
    try {
      setSaved((await bridge.list_models()).models)
    } catch {
      /* listing is advisory; a failure must not block solving */
    }
  }, [])

  useEffect(() => {
    if (!open) return
    setResult(null)
    setNote('')
    void refreshModels()
  }, [open, refreshModels])

  const run = async (fn: () => Promise<SolveResult>) => {
    setBusy(true)
    setNote('')
    try {
      const res = await fn()
      setResult(res)
      // Only a solve that actually reached an optimum has something to paint.
      onAnnotations?.(annotationsFrom(res, model.objective || undefined))
      if (res.applied) onMutated?.()
      await refreshModels() // a selection solve stores `default`
    } catch (e) {
      setResult({ ok: false, error: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const solveSelection = () =>
    selection &&
    run(() =>
      bridge.solve_selection(selection.r0, selection.c0, selection.r1, selection.c1, model.sense),
    )

  const solveModel = () =>
    run(() => bridge.solve_model({ ...toSpec(model), apply: applyToSheet }))

  const inferFromSelection = async () => {
    if (!selection) return
    const res = await bridge.infer_model_spec(
      selection.r0,
      selection.c0,
      selection.r1,
      selection.c1,
      model.sense,
    )
    if (!res.ok) {
      setNote(res.error ?? 'could not read a model from that selection')
      return
    }
    setModel((m) => ({
      ...m,
      sense: res.sense ?? m.sense,
      objective: res.objective ?? '',
      vars: res.vars ?? '',
      constraints: res.constraints ?? '',
    }))
    setNote(`read from ${selection.ref}`)
  }

  const load = (name: string) => {
    const m = saved.find((s) => s.name === name)
    if (m) {
      setModel({ ...EMPTY, ...m })
      setNote(`loaded ${name}`)
    }
  }

  const save = async () => {
    const res = await bridge.save_model(model.name, toSpec(model))
    setNote(res.ok ? `saved ${res.name ?? model.name}` : (res.error ?? 'could not save the model'))
    if (res.ok) await refreshModels()
  }

  const remove = async () => {
    const res = await bridge.delete_model(model.name)
    setNote(res.ok ? `deleted ${model.name}` : (res.error ?? 'could not delete'))
    if (res.ok) {
      setModel(EMPTY)
      await refreshModels()
    }
  }

  const annotations = annotationsFrom(result, model.objective || undefined)
  const roles = rolesUsed(annotations)

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content wide">
          <Dialog.Title className="dialog-title">Optimize</Dialog.Title>
          <Dialog.Description className="dialog-desc">
            Solve a linear model over the sheet. Infer one from the selection
            {selection ? ` ${selection.ref}` : ''}, or work with a model saved in the workbook.
          </Dialog.Description>

          <div className="field-row">
            <span className="field-label">Model</span>
            <select
              className="model-select"
              aria-label="Saved models"
              value={saved.some((s) => s.name === model.name) ? model.name : ''}
              onChange={(e) => load(e.target.value)}
            >
              <option value="">(unsaved)</option>
              {saved.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </select>
            <input
              aria-label="Model name"
              value={model.name}
              onChange={(e) => set('name', e.target.value)}
              placeholder="name"
            />
            <button className="btn" onClick={() => void save()} disabled={busy}>
              Save
            </button>
            <button className="btn" onClick={() => void remove()} disabled={busy || !model.name}>
              Delete
            </button>
          </div>

          <div className="field-row">
            <span className="field-label">Sense</span>
            <label className="radio">
              <input
                type="radio"
                checked={model.sense === 'max'}
                onChange={() => set('sense', 'max')}
              />
              Maximize
            </label>
            <label className="radio">
              <input
                type="radio"
                checked={model.sense === 'min'}
                onChange={() => set('sense', 'min')}
              />
              Minimize
            </label>
            <button
              className="btn"
              onClick={() => void inferFromSelection()}
              disabled={busy || !selection}
            >
              Read from selection
            </button>
          </div>

          <div className="field-row">
            <span className="field-label">Objective</span>
            <input
              aria-label="Objective"
              value={model.objective}
              onChange={(e) => set('objective', e.target.value)}
              placeholder="B2"
            />
            <span className="field-label">Vars</span>
            <input
              aria-label="Decision variables"
              value={model.vars}
              onChange={(e) => set('vars', e.target.value)}
              placeholder="A2:A3"
            />
          </div>
          <div className="field-row">
            <span className="field-label">Constraints</span>
            <input
              aria-label="Constraints"
              value={model.constraints}
              onChange={(e) => set('constraints', e.target.value)}
              placeholder="C2:C4"
            />
            <span className="field-label">Bounds</span>
            <input
              aria-label="Bounds"
              value={model.bounds ?? ''}
              onChange={(e) => set('bounds', e.target.value)}
              placeholder="A2=0:10"
            />
          </div>
          <div className="field-row">
            <span className="field-label">Integers</span>
            <input
              aria-label="Integer variables"
              value={model.integers ?? ''}
              onChange={(e) => set('integers', e.target.value)}
              placeholder="(optional)"
            />
            <span className="field-label">Binaries</span>
            <input
              aria-label="Binary variables"
              value={model.binaries ?? ''}
              onChange={(e) => set('binaries', e.target.value)}
              placeholder="(optional)"
            />
          </div>

          <div className="field-row">
            <label className="radio">
              <input
                type="checkbox"
                checked={applyToSheet}
                onChange={(e) => setApplyToSheet(e.target.checked)}
              />
              Write the solution to the sheet
            </label>
            <button
              className="btn"
              onClick={() => void solveSelection()}
              disabled={busy || !selection}
            >
              Solve selection
            </button>
            <button
              className="btn-primary"
              onClick={() => void solveModel()}
              disabled={busy || !model.objective || !model.vars}
            >
              Solve
            </button>
          </div>

          {note && <p className="note">{note}</p>}
          {result && <SolveResultView result={result} sense={model.sense} />}

          {roles.length > 0 && (
            <div className="annot-legend" data-testid="annot-legend">
              <span>On the sheet:</span>
              {roles.map((role) => (
                <span key={role}>
                  <span className={'swatch ' + role} />
                  {role}
                </span>
              ))}
            </div>
          )}

          <div className="dialog-actions">
            <Dialog.Close className="btn">Close</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
