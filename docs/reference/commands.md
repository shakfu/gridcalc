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
