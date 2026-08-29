import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { MenuBar, type EditCommands, type StructureCommands } from './components/MenuBar'
import { Toolbar } from './components/Toolbar'
import { StatusBar } from './components/StatusBar'
import { AboutDialog } from './components/AboutDialog'
import { OptimizeDialog } from './components/OptimizeDialog'
import { GoalDialog } from './components/GoalDialog'
import { SweepDialog } from './components/SweepDialog'
import { ChartDialog } from './components/ChartDialog'
import { SheetDialog, type SheetMode } from './components/SheetDialog'
import { FindBar } from './components/FindBar'
import { CommandPalette } from './components/CommandPalette'
import { buildRegistry } from './lib/registry'
import { Grid, type GridHandle } from './components/Grid'
import { useWorkbook } from './hooks/useWorkbook'
import type { CellAnnotation, Selection, SheetView } from './lib/grid'
import type { SharedCommand } from './bridge/types'
import { bridge } from './bridge/api'

// Whether an event landed in something the user is typing into. `contentEditable`
// counts: a rich-text host is still a field, even though it is not an <input>.
function isTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

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
  const [sheetOpen, setSheetOpen] = useState(false)
  const [sheetMode, setSheetMode] = useState<SheetMode>('add')
  const [findOpen, setFindOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  // The shared command registry, fetched once. The palette is built from it,
  // so a command added on the Python side needs no change here.
  const [sharedCommands, setSharedCommands] = useState<SharedCommand[]>([])
  // Solver output painted on the sheet. Cleared when the workbook changes
  // underneath it, since an annotation describes one particular solution.
  const [annotations, setAnnotations] = useState<Record<string, CellAnnotation>>({})

  // Kept as one function because the invalidation rule is one rule, applied
  // from two places. Nothing is written when there is nothing painted, so a
  // clear on an unannotated sheet is not a re-render.
  const clearAnnotations = useCallback(() => {
    setAnnotations((a) => (Object.keys(a).length ? {} : a))
  }, [])

  // Where each sheet was last left. A ref rather than state: it is written on
  // the way out of a sheet and read on the way in, so re-rendering the shell
  // for it would be pure waste. Keyed by sheet *name*, so the entry follows a
  // sheet across a reorder and survives a rename (which does not remount the
  // grid, the tab index being unchanged); the filename keeps a newly-opened
  // workbook from inheriting the previous one's positions. The two halves
  // are joined on NUL, which neither a path nor a sheet name can contain, so
  // no pair of them can collide on one key.
  const sheetViews = useRef(new Map<string, SheetView>())
  // A load replaces the workbook, so every remembered position describes a
  // sheet that is gone. The filename in the key was meant to prevent the
  // inheritance, but it does not separate two different workbooks opened from
  // the same path -- the entries have to be dropped on the load itself.
  useEffect(() => {
    sheetViews.current.clear()
  }, [wb.loads])
  const sheetName = wb.sheets ? (wb.sheets.names[wb.sheets.active] ?? '') : ''
  const viewKey = wb.dims ? `${wb.dims.filename}\u0000${sheetName}` : ''

  // An edit invalidates the last solve: shadow prices describe the sheet as it
  // was solved, so keeping them painted after a change would be a lie.
  const onGridMutate = useCallback(() => {
    wb.markDirty()
    clearAnnotations()
  }, [wb, clearAnnotations])

  // So does leaving the sheet. Annotations are addressed in A1 but painted by
  // position, and an A1 reference names a different cell on a different sheet
  // -- so carrying them across a tab switch does not merely show a stale
  // result, it shows it against the wrong cells. Driven by the same key the
  // view state is stashed under, so opening another workbook clears them too.
  useEffect(() => {
    clearAnnotations()
  }, [viewKey, clearAnnotations])

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

  // Insert/delete row and column, scoped to the selection: the engine works one
  // line at a time, so a multi-row selection becomes that many inserts, or one
  // batched delete of the span.
  const structure = useMemo<StructureCommands | null>(() => {
    if (!selection) return null
    const { r0, r1, c0, c1 } = selection
    return {
      rows: r1 - r0 + 1,
      cols: c1 - c0 + 1,
      // Straight to the shared registry, so the menu, the palette and the
      // TUI's `:ir`/`:dr` are one implementation.
      insertRows: () => void wb.actions.runCommand('insrow', [], selection),
      insertCols: () => void wb.actions.runCommand('inscol', [], selection),
      deleteRows: () => void wb.actions.runCommand('delrow', [], selection),
      deleteCols: () => void wb.actions.runCommand('delcol', [], selection),
    }
  }, [selection, wb.actions])

  const openSheetDialog = useCallback((mode: SheetMode) => {
    setSheetMode(mode)
    setSheetOpen(true)
  }, [])

  // Rebuilt whenever anything a command closes over changes -- the selection
  // it acts on, the sheet list it names, the enabled predicates. Cheap: it is
  // a list of closures, built only when the palette is about to read it.
  const registry = useMemo(
    () =>
      buildRegistry({
        actions: wb.actions,
        commands,
        structure,
        sheets: wb.sheets,
        selection,
        shared: sharedCommands,
        runShared: (name, args) => void wb.actions.runCommand(name, args, selection),
        goto: (ref) => grid.current?.goto(ref),
        openFind: () => setFindOpen(true),
        openOptimize: () => setOptOpen(true),
        openGoal: () => setGoalOpen(true),
        openSweep: () => setSweepOpen(true),
        openChart: () => setChartOpen(true),
        openAbout: () => setAboutOpen(true),
        addSheet: () => openSheetDialog('add'),
        renameSheet: () => openSheetDialog('rename'),
        onFormat: formatSel,
        onDefaultFormat: (fmt) => void wb.actions.setDefaultFormat(fmt),
        touched: wb.touched,
        notify: wb.notify,
        fail: wb.fail,
      }),
    [wb, commands, structure, selection, sharedCommands, formatSel, openSheetDialog],
  )

  const { fail, ready } = wb
  useEffect(() => {
    if (!ready) return
    let alive = true
    bridge
      .list_commands()
      .then((r) => alive && setSharedCommands(r.commands))
      .catch(() => {
        // A palette missing its shared half is worth saying so: the menus still
        // work, but half the commands would silently not be there.
        if (alive) fail('could not load the command registry')
      })
    return () => {
      alive = false
    }
  }, [ready, fail])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return
      const k = e.key.toLowerCase()
      // Open and save are app-level commands that no text field lays claim to,
      // so they work wherever focus is. Undo/redo and the format toggles are
      // different: an <input> handles Ctrl+Z itself, and Ctrl+B inside a dialog
      // means nothing to the sheet behind it. Without this guard, fixing a typo
      // while typing a cell ref in Goal Seek undid the *workbook*. The grid's
      // own editors stop propagation themselves; a dialog cannot, because this
      // listener is on the window.
      if (k === 'o') {
        e.preventDefault()
        void wb.actions.open()
        return
      }
      // Find is deliberately above the text-field guard: Ctrl+F while the find
      // input already has focus should re-focus and select it, not fall
      // through to the browser's own find.
      if (k === 'f') {
        e.preventDefault()
        setFindOpen(true)
        return
      }
      if (k === 'k') {
        e.preventDefault()
        setPaletteOpen(true)
        return
      }
      if (k === 's') {
        e.preventDefault()
        void wb.actions.save()
        return
      }
      if (isTextField(e.target)) return
      if (k === 'z') {
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
        structure={structure}
        sheets={wb.sheets}
        onAbout={() => setAboutOpen(true)}
        onOptimize={() => setOptOpen(true)}
        onGoal={() => setGoalOpen(true)}
        onSweep={() => setSweepOpen(true)}
        onChart={() => setChartOpen(true)}
        onFormat={formatSel}
        onDefaultFormat={(fmt) => void wb.actions.setDefaultFormat(fmt)}
        onAddSheet={() => openSheetDialog('add')}
        onRenameSheet={() => openSheetDialog('rename')}
        onFind={() => setFindOpen(true)}
      />
      <Toolbar wb={wb} onFormat={formatSel} />
      <FindBar
        open={findOpen}
        onClose={() => {
          setFindOpen(false)
          grid.current?.focus()
        }}
        onGoto={(ref) => grid.current?.goto(ref)}
        onError={wb.fail}
        revision={wb.mutations}
      />
      <main className="stage">
        {wb.ready && wb.dims && wb.sheets ? (
          <Grid
            ref={grid}
            key={`${wb.dims.filename}:${wb.loads}:${wb.sheets.active}`}
            ncol={wb.dims.ncol}
            nrow={wb.dims.nrow}
            revision={wb.revision}
            onSelectionChange={setSelection}
            annotations={annotations}
            onError={wb.fail}
            onMutate={onGridMutate}
            initialView={sheetViews.current.get(viewKey) ?? null}
            onViewChange={(v) => sheetViews.current.set(viewKey, v)}
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
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} commands={registry} />
      <SheetDialog
        open={sheetOpen}
        mode={sheetMode}
        sheets={wb.sheets}
        actions={wb.actions}
        onOpenChange={setSheetOpen}
      />
    </div>
  )
}
