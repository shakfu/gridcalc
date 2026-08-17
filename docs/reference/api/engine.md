# engine

The workbook model: a `Grid` of `Sheet`s, each a sparse `dict[(col, row)] -> Cell`, plus the array type ranges evaluate to, the reference parsing and adjustment rules, and JSON load/save.

::: gridcalc.engine
    options:
      members:
        - Mode
        - Grid
        - Sheet
        - Cell
        - Vec
        - NamedRange
        - ref
        - refabs
        - col_name
        - cellname
        - adjust_refs
