# Quick tour

Cells hold a number, a label (any string not prefixed with `=`), or a formula (prefixed with `=`). Arrow keys move; `Enter` commits and moves down; `Tab` commits and moves right.

This guide shows the terminal frontend, but the model, formulas, file format, and most commands are the same in the [desktop app](desktop.md).

```text
        A          B          C
1  Revenue   Cost       Margin
2  1000      600        =(A2-B2)/A2*100      <- formula
3  1200      700        =(A3-B3)/A3*100
4  Total     =SUM(B2:B3) =AVG(C2:C3)
```

## The command line

Press `:` for the command line. The basics:

| Command | Purpose |
|---|---|
| `:w [file]` | save (extension `.json` or `.xlsx`) |
| `:o file` | open |
| `:q`, `:q!` | quit, force-quit |
| `:e` | edit the workbook's Python code block in `$EDITOR` |
| `u`, `Ctrl-R` | undo / redo |
| `v` | enter visual selection mode (then `y` yanks, `p` pastes) |
| `/text` | search (`n`/`N` to cycle matches) |
| `>` | go to a named cell (e.g. `> AA10`) |

The full set is in the [command reference](reference/commands.md), and every key is rebindable -- see [Configuration](guide/config.md).

## Where to go next

- [Formula modes](guide/modes.md) -- pick strict Excel, Excel plus Python, or full Python for a workbook.
- [Formulas](guide/formulas.md) -- syntax, the function library, named ranges, and the per-workbook code block.
- [Multi-sheet workbooks](guide/sheets.md) -- tabs, cross-sheet references, and what the dep graph does with them.
- [Optimization](guide/optimization.md) -- define an LP, MIP, or QP in the sheet and solve it.
