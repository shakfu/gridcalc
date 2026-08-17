# formula

The Excel formula language used by EXCEL and HYBRID modes. Nothing on this path calls `eval()`: the source is tokenized, parsed into an AST, and walked by an evaluator that implements Excel's coercion and error-propagation rules.

## Parser

::: gridcalc.formula.parser
    options:
      members:
        - parse
        - ParseError

## Lexer

::: gridcalc.formula.lexer
    options:
      members:
        - tokenize
        - Token

## Evaluator

::: gridcalc.formula.evaluator
    options:
      members:
        - Env
        - Reference
        - LambdaValue

## Dependencies

Static reference extraction, which is what makes topological recalculation possible.

::: gridcalc.formula.deps
    options:
      members:
        - extract_refs
        - has_dynamic_refs

## Errors

::: gridcalc.formula.errors
    options:
      members:
        - ExcelError
        - FormulaError
        - parse_error_literal
        - first_error

## AST nodes

::: gridcalc.formula.ast_nodes
    options:
      show_if_no_docstring: true
      members_order: source
