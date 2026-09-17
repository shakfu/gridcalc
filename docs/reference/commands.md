# Command reference

```text
File          :w [file]   :wq   :q   :q!   :o file   :e
Edit          :b   :clear   :dr   :dc   :ir   :ic   :m   :r
              :sort [col] [desc]   yank/paste: y/p (syncs system clipboard)
              undo/redo: u / Ctrl-R   (aliases: Ctrl-Z / Ctrl-Y)
              :recalc (or !) recompute every formula
Format        :f <spec>   :gf <spec>   :width <n>   Ctrl-B / Ctrl-U
Search        /pattern   n   N
Sheets        :sheets (picker)   :sheet [name|N|add|del|rename|move]
Names         :name <n> [range]   :names   :unname <n>
Modes         :mode [excel|hybrid|python]
Import/export :csv save/load   :xlsx save/load   :pd save/load
Optimization  :opt   :opt def   :opt run   :opt sens   :opt sweep
              :opt list   :opt undef
              :goal <cell> = <target> by <cell> [in <lo>:<hi>]
View          :view   E   :title <v|h|b|n>  (aliases :tv/:th/:tb/:tn)
```

Most of these are defined once in a [frontend-neutral registry](https://github.com/shakfu/gridcalc/blob/main/src/gridcalc/commands.py) and dispatched by both frontends, so the terminal's `:` line and the desktop app's Ctrl-K palette run the same implementation. A conformance test fails if either frontend loses a shared command.

Details by area:

- [Formatting](../guide/formatting.md) -- `:f`, `:gf`, `:width`

- [Multi-sheet workbooks](../guide/sheets.md) -- `:sheet`, `:sheets`

- [Formulas](../guide/formulas.md) -- `:name`, `:names`, `:unname`, `:e`

- [Formula modes](../guide/modes.md) -- `:mode`

- [Import and export](../guide/import-export.md) -- `:csv`, `:xlsx`, `:pd`

- [Headless CLI](cli.md) -- running the same operations in batch, without opening the editor

- [Optimization](../guide/optimization.md) -- `:opt` and its subcommands

- [Goal seek](../guide/goal-seek.md) -- `:goal`

- [Configuration](../guide/config.md) -- rebinding any of the keys above

## Saving and opening

`:w` picks the format from the extension: `.xlsx`, `.csv`, or JSON for anything else. It asks before:

- a format that drops formulas, other sheets, names, models or the code block;

- overwriting an existing file other than the one open.

A failed save, in any format, leaves the existing file unchanged.

`:o`, `:xlsx load`, `:csv load` and `:pd load` ask before discarding unsaved changes. `:o` and `:xlsx load` replace the workbook and clear undo history. `:csv load` and `:pd load` replace the active sheet and can be undone.

## Undo

`u` undoes cell edits, formatting, structural commands (`:dr`, `:ic`, `:sort`, `:clear`), `:opt` and `:goal` results, sheet add/delete/rename/move, `:name`, `:unname` and `:mode`. Undoing a command that rewrote formulas on several sheets restores all of them.

Not undoable: `:e`, `:width`, `:opt def` and `:opt undef`.
