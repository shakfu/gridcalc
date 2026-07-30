import { bridge } from '../bridge/api'
import type { Command } from './commands'
import type { EditCommands, StructureCommands } from '../components/MenuBar'
import type { WorkbookActions } from '../hooks/useWorkbook'
import type { Sheets, SharedCommand } from '../bridge/types'
import type { Selection } from './grid'

// Everything the palette can run. Menu-backed commands are listed too, not
// just the ones with no other home: the palette is the fastest way to reach
// *any* command once the user is typing, and a palette that only knows the
// obscure half would be a worse menu rather than a faster one.
export interface RegistryDeps {
  actions: WorkbookActions
  commands: EditCommands
  structure: StructureCommands | null
  sheets: Sheets | null
  // The shared registry as fetched from `Api.list_commands`, turned into
  // palette entries below. Empty until the bridge answers.
  shared: SharedCommand[]
  // Runs one of those, with the current selection as its rectangle.
  runShared: (name: string, args: string[]) => void
  selection: Selection | null
  goto: (ref: string) => void
  openFind: () => void
  openOptimize: () => void
  openGoal: () => void
  openSweep: () => void
  openChart: () => void
  openAbout: () => void
  addSheet: () => void
  renameSheet: () => void
  onFormat: (spec: string) => void
  onDefaultFormat: (fmt: string) => void
  // Something changed outside the grid's own edit path; refetch.
  touched: () => void
  notify: (msg: string) => void
  fail: (msg: string) => void
}

export function buildRegistry(d: RegistryDeps): Command[] {
  const active = d.sheets ? d.sheets.names[d.sheets.active] : ''
  const multiSheet = (d.sheets?.names.length ?? 0) > 1

  // Shared commands become palette entries mechanically -- title, group,
  // argument prompt and enabled-ness all come from the descriptor, so a
  // command added to `gridcalc.commands` appears here with no edit at all.
  //
  // Multi-argument commands get one field and are split on whitespace, exactly
  // as `:name Revenue A1:B3` is: matching the `:` line keeps one mental model
  // across the two frontends rather than inventing a second.
  const fromShared = d.shared.map((c): Command => {
    const label = c.args.map((a) => a.name).join(' ')
    const placeholder = c.args.map((a) => a.help).filter(Boolean).join(' / ')
    return {
      id: `shared.${c.name}`,
      group: c.group,
      title: c.title,
      hint: `:${c.name}`,
      enabled: c.needs_selection ? () => d.selection !== null : undefined,
      arg: c.args.length ? { label, placeholder } : undefined,
      run: (v) => d.runShared(c.name, v.trim() ? v.trim().split(/\s+/) : []),
    }
  })

  return [
    ...fromShared,
    { id: 'file.open', group: 'File', title: 'Open workbook', hint: '⌘O', run: () => void d.actions.open() },
    { id: 'file.save', group: 'File', title: 'Save', hint: '⌘S', run: () => void d.actions.save() },
    { id: 'file.saveAs', group: 'File', title: 'Save as', run: () => void d.actions.saveAs() },

    { id: 'edit.undo', group: 'Edit', title: 'Undo', hint: '⌘Z', run: () => void d.actions.undo() },
    { id: 'edit.redo', group: 'Edit', title: 'Redo', hint: '⇧⌘Z', run: () => void d.actions.redo() },
    { id: 'edit.cut', group: 'Edit', title: 'Cut', hint: '⌘X', run: d.commands.cut },
    { id: 'edit.copy', group: 'Edit', title: 'Copy', hint: '⌘C', run: d.commands.copy },
    { id: 'edit.paste', group: 'Edit', title: 'Paste', hint: '⌘V', run: d.commands.paste },
    { id: 'edit.clear', group: 'Edit', title: 'Clear selection', run: d.commands.clear },
    { id: 'edit.fillDown', group: 'Edit', title: 'Fill down', hint: '⌘D', run: d.commands.fillDown },
    { id: 'edit.fillRight', group: 'Edit', title: 'Fill right', hint: '⌘R', run: d.commands.fillRight },
    { id: 'edit.find', group: 'Edit', title: 'Find', hint: '⌘F', run: d.openFind },

    {
      id: 'nav.goto',
      group: 'Navigate',
      title: 'Go to reference',
      arg: { label: 'Reference', placeholder: 'B12', initial: () => d.selection?.active ?? '' },
      run: (v) => d.goto(v.trim().toUpperCase()),
    },

    { id: 'sheet.add', group: 'Sheet', title: 'New sheet', run: d.addSheet },
    { id: 'sheet.rename', group: 'Sheet', title: 'Rename sheet', run: d.renameSheet },
    {
      id: 'sheet.delete',
      group: 'Sheet',
      title: 'Delete sheet',
      hint: active,
      enabled: () => multiSheet,
      run: () => void d.actions.deleteSheet(active),
    },
    {
      id: 'sheet.moveLeft',
      group: 'Sheet',
      title: 'Move sheet left',
      enabled: () => Boolean(d.sheets && d.sheets.active > 0),
      run: () => void d.actions.moveSheet(active, (d.sheets?.active ?? 0) - 1),
    },
    {
      id: 'sheet.moveRight',
      group: 'Sheet',
      title: 'Move sheet right',
      enabled: () => Boolean(d.sheets && d.sheets.active < d.sheets.names.length - 1),
      run: () => void d.actions.moveSheet(active, (d.sheets?.active ?? 0) + 1),
    },

    { id: 'format.bold', group: 'Format', title: 'Bold', hint: '⌘B', run: () => d.onFormat('b') },
    { id: 'format.italic', group: 'Format', title: 'Italic', hint: '⌘I', run: () => d.onFormat('i') },
    { id: 'format.underline', group: 'Format', title: 'Underline', hint: '⌘U', run: () => d.onFormat('u') },
    { id: 'format.currency', group: 'Format', title: 'Number: currency', run: () => d.onFormat('$') },
    { id: 'format.percent', group: 'Format', title: 'Number: percent', run: () => d.onFormat('%') },
    { id: 'format.integer', group: 'Format', title: 'Number: integer', run: () => d.onFormat('I') },
    { id: 'format.general', group: 'Format', title: 'Number: general', run: () => d.onFormat('G') },
    {
      id: 'format.default',
      group: 'Format',
      title: 'Workbook default number format',
      arg: { label: 'One of L R I G D $ % *', placeholder: 'G' },
      run: (v) => d.onDefaultFormat(v.trim().toUpperCase()),
    },
    // Column width stays a client-side command rather than a shared one: the
    // web view measures columns in pixels per column, while the TUI's `:width`
    // is a single width in character cells. Same word, different operation.
    {
      id: 'format.colWidth',
      group: 'Format',
      title: 'Set column width',
      hint: 'pixels',
      enabled: () => d.selection !== null,
      arg: { label: 'Width in pixels', placeholder: '90' },
      run: (v) => {
        const px = Number(v.trim())
        const col = d.selection?.c0
        if (col === undefined || !Number.isFinite(px)) {
          d.fail('column width: give a number of pixels')
          return
        }
        void bridge
          .set_col_width(col, Math.round(px))
          .then((r) => (r.ok ? d.touched() : d.fail(r.error ?? 'could not set the width')))
          .catch((e: unknown) => d.fail(`column width: ${String(e)}`))
      },
    },

    { id: 'data.optimize', group: 'Data', title: 'Optimize', run: d.openOptimize },
    { id: 'data.goal', group: 'Data', title: 'Goal seek', run: d.openGoal },
    { id: 'data.sweep', group: 'Data', title: 'Sweep', run: d.openSweep },
    { id: 'data.chart', group: 'Data', title: 'Chart', run: d.openChart },

    { id: 'help.about', group: 'Help', title: 'About gridcalc', run: d.openAbout },
  ]
}
