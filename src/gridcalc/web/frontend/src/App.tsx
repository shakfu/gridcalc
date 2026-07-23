import { useCallback, useEffect, useState } from 'react'
import { MenuBar } from './components/MenuBar'
import { Toolbar } from './components/Toolbar'
import { AboutDialog } from './components/AboutDialog'
import { ResultsDialog } from './components/ResultsDialog'
import { GoalDialog } from './components/GoalDialog'
import { ChartDialog } from './components/ChartDialog'
import { Grid } from './components/Grid'
import { useWorkbook } from './hooks/useWorkbook'
import type { Selection } from './lib/grid'

// The application shell: Radix menubar + toolbar wired to the workbook bridge, a
// virtualized grid, and the feature dialogs (optimize / goal seek / chart) the
// Data menu opens over the current selection.
export function App() {
  const wb = useWorkbook()
  const [selection, setSelection] = useState<Selection | null>(null)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [optOpen, setOptOpen] = useState(false)
  const [goalOpen, setGoalOpen] = useState(false)
  const [chartOpen, setChartOpen] = useState(false)

  const formatSel = useCallback(
    (spec: string) => {
      if (selection) void wb.actions.format(selection, spec)
    },
    [selection, wb.actions],
  )

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
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [wb.actions, formatSel])

  return (
    <div className="app">
      <MenuBar
        actions={wb.actions}
        onAbout={() => setAboutOpen(true)}
        onOptimize={() => setOptOpen(true)}
        onGoal={() => setGoalOpen(true)}
        onChart={() => setChartOpen(true)}
        onFormat={formatSel}
        onDefaultFormat={(fmt) => void wb.actions.setDefaultFormat(fmt)}
      />
      <Toolbar wb={wb} onFormat={formatSel} />
      <main className="stage">
        {wb.ready && wb.dims && wb.sheets ? (
          <Grid
            key={`${wb.dims.filename}:${wb.sheets.active}`}
            ncol={wb.dims.ncol}
            nrow={wb.dims.nrow}
            revision={wb.revision}
            onSelectionChange={setSelection}
          />
        ) : (
          <p className="note">connecting to engine...</p>
        )}
      </main>
      <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} />
      <ResultsDialog open={optOpen} onOpenChange={setOptOpen} selection={selection} />
      <GoalDialog open={goalOpen} onOpenChange={setGoalOpen} activeRef={selection?.active} />
      <ChartDialog open={chartOpen} onOpenChange={setChartOpen} rangeRef={selection?.ref} />
    </div>
  )
}
