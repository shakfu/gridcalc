// The command registry behind the palette (Ctrl-K).
//
// gridcalc's terminal frontend reaches everything through `:` commands. A GUI
// cannot inherit that modal line editor, but it should not lose the reach
// either: menus only ever justify the common commands, leaving `:width`,
// `:name`, `:names`, `:unname`, `!` and friends with nowhere to live. The
// palette is where they live, so a command needs a registry entry rather than
// a bespoke dialog before it is usable.

export interface Command {
  id: string
  title: string
  // Shown right-aligned: a keyboard shortcut, or a short note about scope.
  hint?: string
  // Groups the list; also matched against, so typing "sheet" finds them all.
  group: string
  // Commands that need a value declare a prompt. The palette collects the
  // string in a second step and hands it to `run` -- one input mechanism for
  // every such command, rather than one dialog each.
  arg?: { label: string; placeholder?: string; initial?: () => string }
  run: (value: string) => void
  // Hidden from the list without being removed from the registry: a command
  // that cannot act right now (no selection, single sheet) should not be
  // offered and then fail.
  enabled?: () => boolean
}

// Ranks a command against the typed query. Returns null for no match.
//
// Deliberately subsequence-based rather than exact-substring: "isr" should
// find "Insert Row", which is the whole point of typing into a palette instead
// of reading a menu. A contiguous match still outranks a scattered one, and a
// match on the title outranks one that only hit the group name.
export function score(cmd: Command, query: string): number | null {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const title = cmd.title.toLowerCase()
  const direct = title.indexOf(q)
  if (direct === 0) return 1000
  if (direct > 0) return 800 - direct
  const sub = subsequenceScore(title, q)
  if (sub !== null) return 500 + sub
  if (`${cmd.group.toLowerCase()} ${title}`.includes(q)) return 200
  return null
}

// Highest when the query's characters appear close together and early.
function subsequenceScore(text: string, q: string): number | null {
  let ti = 0
  let gaps = 0
  let first = -1
  for (const ch of q) {
    const found = text.indexOf(ch, ti)
    if (found < 0) return null
    if (first < 0) first = found
    if (ti > 0) gaps += found - ti
    ti = found + 1
  }
  return Math.max(0, 100 - gaps - first)
}

export function rank(commands: Command[], query: string): Command[] {
  const scored: Array<{ cmd: Command; s: number }> = []
  for (const cmd of commands) {
    if (cmd.enabled && !cmd.enabled()) continue
    const s = score(cmd, query)
    if (s !== null) scored.push({ cmd, s })
  }
  // Stable within a score so an unfiltered palette keeps registry order --
  // the list should not reshuffle itself as the user deletes characters.
  return scored
    .map((x, i) => ({ ...x, i }))
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map((x) => x.cmd)
}
