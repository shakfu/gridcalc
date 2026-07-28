import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MenuBar, type EditCommands } from './components/MenuBar'
import { Toolbar } from './components/Toolbar'
import { StatusBar } from './components/StatusBar'
import { AboutDialog } from './components/AboutDialog'
import { OptimizeDialog } from './components/OptimizeDialog'
import { GoalDialog } from './components/GoalDialog'
import { SweepDialog } from './components/SweepDialog'
import { ChartDialog } from './components/ChartDialog'
import { Grid, type GridHandle } from './components/Grid'
import { useWorkbook } from './hooks/useWorkbook'
import type { CellAnnotation, Selection } from './lib/grid'

// The application shell: Radix menubar + toolbar wired to the workbook bridge, a
// virtualized grid, a status bar, and the feature dialogs (optimize / goal seek
// / sweep / chart) the Data menu opens over the current selection.
//
// The grid owns its cursor and selection (both change on every mouse move, so
// lifting them would re-render the whole shell); it exposes an imperative
// handle instead, and everything that acts on the grid -- menu items, the
// keyboard -- goes through that one command set.
export function App() {
  const wb = useWorkbook()
  const grid = useRef<GridHandle>(null)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [optOpen, setOptOpen] = useState(false)
  const [goalOpen, setGoalOpen] = useState(false)
  const [sweepOpen, setSweepOpen] = useState(false)
  const [chartOpen, setChartOpen] = useState(false)
  // Solver output painted on the sheet. Cleared when the workbook changes
  // underneath it, since an annotation describes one particular solution.
  const [annotations, setAnnotations] = useState<Record<string, CellAnnotation>>({})

  // An edit invalidates the last solve: shadow prices describe the sheet as it
  // was solved, so keeping them painted after a change would be a lie.
  const onGridMutate = useCallback(() => {
    wb.markDirty()
    setAnnotations((a) => (Object.keys(a).length ? {} : a))
  }, [wb])

  const formatSel = useCallback(
    (spec: string) => {
      if (selection) void wb.actions.format(selection, spec)
    },
    [selection, wb.actions],
  )

  // The menu drives the grid's own commands, so a menu item and its keyboard
  // shortcut cannot drift apart. Focus returns to the grid afterwards -- a menu
  // click otherwise leaves the keyboard pointing at the menubar.
  const commands = useMemo<EditCommands>(() => {
    const run = (fn: (g: GridHandle) => void) => () => {
      const g = grid.current
      if (!g) return
      fn(g)
      g.focus()
    }
    return {
      cut: run((g) => g.cut()),
      copy: run((g) => g.copy()),
      paste: run((g) => g.paste()),
      clear: run((g) => g.clear()),
      fillDown: run((g) => g.fillDown()),
      fillRight: run((g) => g.fillRight()),
    }
  }, [])

  const { fail } = wb
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      const k = e.key.toLowerCase()
      if (k === 'o') {
        e.preventDefault()
        void wb.actions.open()
      } else if (k === 's') {
        e.preventDefault()
        void wb.actions.save()
      } else if (k === 'z') {
        e.preventDefault()
        void (e.shiftKey ? wb.actions.redo() : wb.actions.undo())
      } else if (k === 'y') {
        e.preventDefault()
        void wb.actions.redo()
      } else if (k === 'b' || k === 'i' || k === 'u') {
        e.preventDefault()
        formatSel(k)
      }
    }
    // Anything that escapes a local handler still reaches the user. Without
    // this a rejected bridge call in a dialog is a silent no-op.
    const onRejection = (e: PromiseRejectionEvent) => {
      const r: unknown = e.reason
      fail(r instanceof Error ? r.message : String(r))
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('unhandledrejection', onRejection)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('unhandledrejection', onRejection)
    }
  }, [wb.actions, formatSel, fail])

  return (
    <div className="app">
      <MenuBar
        actions={wb.actions}
        commands={commands}
        onAbout={() => setAboutOpen(true)}
        onOptimize={() => setOptOpen(true)}
        onGoal={() => setGoalOpen(true)}
        onSweep={() => setSweepOpen(true)}
        onChart={() => setChartOpen(true)}
        onFormat={formatSel}
        onDefaultFormat={(fmt) => void wb.actions.setDefaultFormat(fmt)}
      />
      <Toolbar wb={wb} onFormat={formatSel} />
      <main className="stage">
        {wb.ready && wb.dims && wb.sheets ? (
          <Grid
            ref={grid}
            key={`${wb.dims.filename}:${wb.sheets.active}`}
            ncol={wb.dims.ncol}
            nrow={wb.dims.nrow}
            revision={wb.revision}
            onSelectionChange={setSelection}
            annotations={annotations}
            onError={wb.fail}
            onMutate={onGridMutate}
          />
        ) : (
          <p className="note">connecting to engine...</p>
        )}
      </main>
      <StatusBar
        selection={selection}
        status={wb.status}
        statusKind={wb.statusKind}
        dirty={wb.dirty}
        revision={wb.mutations}
      />
      <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} />
      <OptimizeDialog
        open={optOpen}
        onOpenChange={setOptOpen}
        selection={selection}
        onAnnotations={setAnnotations}
        onMutated={wb.touched}
      />
      <GoalDialog
        open={goalOpen}
        onOpenChange={setGoalOpen}
        activeRef={selection?.active}
        onMutated={wb.touched}
      />
      <SweepDialog open={sweepOpen} onOpenChange={setSweepOpen} />
      <ChartDialog open={chartOpen} onOpenChange={setChartOpen} rangeRef={selection?.ref} />
    </div>
  )
}
