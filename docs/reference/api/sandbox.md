# sandbox

The security layer: AST validation of formulas and code blocks, module classification, and inspection of a workbook file without executing anything in it. The threat model is in [Security plan](../../security-plan.md).

::: gridcalc.sandbox
    options:
      members:
        - configure_sandbox
        - validate_formula
        - validate_code
        - classify_module
        - load_modules
        - inspect_file
        - FileInfo
        - LoadPolicy
