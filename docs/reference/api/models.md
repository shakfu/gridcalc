# models

Cross-tab models over sheet data: data items read from named ranges and tables, a PuLP-compatible modelling subset solved by HiGHS, and the runner that executes a sheet's model in a confined child process. See the [Cross-tab models guide](../../guide/models.md) for the commands.

## dataitems

::: gridcalc.dataitems
    options:
      members:
        - DataItem
        - ItemDict
        - read_items
        - validate
        - plan_writes
        - apply_writes
        - collect_writes
        - boxes
        - ItemBox
        - DataItemError

## lpmodel

::: gridcalc.lpmodel
    options:
      members:
        - LpProblem
        - LpVariable
        - LpAffineExpression
        - LpConstraint
        - lpSum
        - value
        - PulpError

## modelrun

::: gridcalc.modelrun
    options:
      members:
        - run_model
        - ModelJob
        - ModelResult
        - ModelError
        - check_model
        - check_workbook
        - set_backend
