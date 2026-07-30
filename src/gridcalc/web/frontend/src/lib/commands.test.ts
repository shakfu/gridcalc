import { rank, score, type Command } from './commands'
import type { RegistryDeps } from './registry'

// A do-nothing dependency set, so a test only has to state the part it cares
// about. Keyed off `RegistryDeps` so a new dependency breaks compilation here
// rather than silently defaulting to undefined at runtime.
function stubDeps(): RegistryDeps {
  const noop = () => {}
  const asyncNoop = async () => {}
  return {
    actions: {
      open: asyncNoop, save: asyncNoop, saveAs: asyncNoop, undo: asyncNoop, redo: asyncNoop,
      setSheet: asyncNoop, addSheet: asyncNoop, deleteSheet: asyncNoop, renameSheet: asyncNoop,
      moveSheet: asyncNoop, runCommand: asyncNoop, format: asyncNoop, setDefaultFormat: asyncNoop,
    },
    commands: { cut: noop, copy: noop, paste: noop, clear: noop, fillDown: noop, fillRight: noop },
    structure: null,
    sheets: { active: 0, names: ['Sheet1'] },
    selection: { r0: 0, c0: 0, r1: 0, c1: 0, ref: 'A1', active: 'A1' },
    shared: [],
    runShared: noop,
    goto: noop, openFind: noop, openOptimize: noop, openGoal: noop, openSweep: noop,
    openChart: noop, openAbout: noop, addSheet: noop, renameSheet: noop,
    onFormat: noop, onDefaultFormat: noop, touched: noop, notify: noop, fail: noop,
  }
}

const cmd = (id: string, title: string, group = 'Edit', extra: Partial<Command> = {}): Command => ({
  id,
  title,
  group,
  run: () => {},
  ...extra,
})

test('an empty query keeps every command in registry order', () => {
  const list = [cmd('a', 'Undo'), cmd('b', 'Redo'), cmd('c', 'Cut')]
  expect(rank(list, '').map((c) => c.id)).toEqual(['a', 'b', 'c'])
})

test('a prefix match outranks a later substring match', () => {
  const list = [cmd('later', 'Fill right'), cmd('prefix', 'Right align')]
  expect(rank(list, 'right')[0].id).toBe('prefix')
})

test('initials find a multi-word command', () => {
  // The point of typing into a palette rather than reading a menu.
  const list = [cmd('ins', 'Insert rows'), cmd('del', 'Delete columns')]
  expect(rank(list, 'isr')[0].id).toBe('ins')
})

test('a contiguous match outranks a scattered subsequence', () => {
  const tight = cmd('tight', 'Set column name') // "name" appears intact
  const loose = cmd('loose', 'Nudge a memo') // only n-a-m-e strung across it
  expect(score(tight, 'name')).toBeGreaterThan(score(loose, 'name') as number)
})

test('a subsequence that is not present at all scores null', () => {
  expect(score(cmd('a', 'Number: general'), 'name')).toBeNull()
})

test('the group name is searchable, so "sheet" finds all of them', () => {
  const list = [cmd('add', 'New', 'Sheet'), cmd('del', 'Delete', 'Sheet'), cmd('u', 'Undo', 'Edit')]
  expect(rank(list, 'sheet').map((c) => c.id).sort()).toEqual(['add', 'del'])
})

test('a non-matching query returns nothing rather than everything', () => {
  expect(rank([cmd('a', 'Undo')], 'zzzz')).toEqual([])
})

test('disabled commands are hidden, not offered and then failed', () => {
  const list = [cmd('on', 'Insert rows'), cmd('off', 'Insert columns', 'Insert', { enabled: () => false })]
  expect(rank(list, 'insert').map((c) => c.id)).toEqual(['on'])
})

test('matching is case-insensitive in both directions', () => {
  expect(score(cmd('a', 'Goal Seek'), 'goal seek')).not.toBeNull()
  expect(score(cmd('a', 'goal seek'), 'GOAL')).not.toBeNull()
})

// -- the shared half of the registry ---------------------------------------

test('every shared descriptor becomes exactly one palette entry', async () => {
  // The parity guarantee, client side: the palette is generated from what the
  // bridge reports, so a command added in `gridcalc.commands` must appear here
  // with no edit to this file. A filter or a typo in the mapping would drop it
  // silently, which is the failure this catches.
  const { buildRegistry } = await import('./registry')
  const shared = [
    { name: 'sort', aliases: [], title: 'Sort rows', group: 'Data', needs_selection: true, args: [] },
    { name: 'names', aliases: [], title: 'List named ranges', group: 'Name', needs_selection: false, args: [] },
  ]
  const built = buildRegistry({ ...stubDeps(), shared })
  for (const c of shared) {
    const entry = built.find((e) => e.id === `shared.${c.name}`)
    expect(entry, `missing palette entry for ${c.name}`).toBeTruthy()
    expect(entry!.title).toBe(c.title)
    expect(entry!.group).toBe(c.group)
  }
})

test('a shared command that needs a selection is hidden without one', async () => {
  const { buildRegistry } = await import('./registry')
  const shared = [
    { name: 'sort', aliases: [], title: 'Sort rows', group: 'Data', needs_selection: true, args: [] },
  ]
  const withSel = buildRegistry({ ...stubDeps(), shared })
  const without = buildRegistry({ ...stubDeps(), shared, selection: null })
  expect(rank(withSel, 'sort').length).toBe(1)
  expect(rank(without, 'sort').length).toBe(0)
})

test('a shared command with arguments prompts for them', async () => {
  const { buildRegistry } = await import('./registry')
  const shared = [
    {
      name: 'name',
      aliases: [],
      title: 'Define name',
      group: 'Name',
      needs_selection: true,
      args: [
        { name: 'name', help: 'the name', required: true, kind: 'text', choices: [] },
        { name: 'range', help: 'defaults to the selection', required: false, kind: 'range', choices: [] },
      ],
    },
  ]
  const entry = buildRegistry({ ...stubDeps(), shared }).find((e) => e.id === 'shared.name')!
  expect(entry.arg?.label).toBe('name range')
})

test('a multi-word argument is split like a `:` command line', async () => {
  // `:name Revenue A1:B3` -- one field, whitespace-split, so the two frontends
  // share one mental model rather than inventing a second.
  const { buildRegistry } = await import('./registry')
  const runShared = vi.fn()
  const shared = [
    {
      name: 'name',
      aliases: [],
      title: 'Define name',
      group: 'Name',
      needs_selection: false,
      args: [{ name: 'name', help: '', required: true, kind: 'text', choices: [] }],
    },
  ]
  const entry = buildRegistry({ ...stubDeps(), shared, runShared }).find(
    (e) => e.id === 'shared.name',
  )!
  entry.run('  Revenue A1:B3  ')
  expect(runShared).toHaveBeenCalledWith('name', ['Revenue', 'A1:B3'])
  entry.run('   ')
  expect(runShared).toHaveBeenLastCalledWith('name', [])
})
