import { useEffect, useState } from 'react'
import { MenuBar } from './components/MenuBar'
import { Toolbar } from './components/Toolbar'
import { AboutDialog } from './components/AboutDialog'
import { Grid } from './components/Grid'
import { useWorkbook } from './hooks/useWorkbook'

// Phase 1 shell: the application chrome (Radix menubar + toolbar) wired to the
// workbook-level bridge actions, over a placeholder stage. The grid and feature
// dialogs land in later phases.
export function App() {
  const wb = useWorkbook()
  const [aboutOpen, setAboutOpen] = useState(false)

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
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [wb.actions])

  return (
    <div className="app">
      <MenuBar actions={wb.actions} onAbout={() => setAboutOpen(true)} />
      <Toolbar wb={wb} />
      <main className="stage">
        {wb.ready && wb.dims && wb.sheets ? (
          <Grid
            key={`${wb.dims.filename}:${wb.sheets.active}`}
            ncol={wb.dims.ncol}
            nrow={wb.dims.nrow}
            revision={wb.revision}
          />
        ) : (
          <p className="note">connecting to engine...</p>
        )}
      </main>
      <AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} />
    </div>
  )
}
