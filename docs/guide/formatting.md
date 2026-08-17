# Formatting

```text
:f b                Toggle bold (also Ctrl-B)
:f u                Toggle underline (also Ctrl-U)
:f i                Toggle italic
:f bi               Combine: bold + italic

:f $                Dollar (2 decimal places)
:f %                Percentage (value*100, 2 decimals)
:f I                Integer (truncate)
:f *                Bar chart (asterisks proportional to value)
:f L | R | G | D    Left / right / general / use-global-format

:f ,.2f             Any Python format spec: 1,234.50
:f .1%              15.7%
:f .2e              1.23e+04
```

`:gf <fmt>` sets the workbook-wide default format. `:width <n>` sets the column width (4 to 40) in the terminal; in the [desktop app](../desktop.md) columns are resized by dragging their edge and the width is measured in pixels.

Labels longer than the column width spill into adjacent empty cells, Excel-style.
