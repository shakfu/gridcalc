# Formulas

```text
=A1 + B1 * 2                          arithmetic, Excel precedence
=(A1 + A2) / 2                        grouping
=2^10                                 exponent (PYTHON: ** also works)
=50%                                  percent postfix -> 0.5
="hello " & A1                        string concat
=IF(A1 > 0, "pos", "neg")             conditionals
=IFERROR(B1/C1, 0)                    error catch -- #DIV/0!, #VALUE!, #N/A, ...
=SUM(A1:A10)                          range -> 1D array
=SUM(A1:A3 * B1:B3)                   element-wise array arithmetic
=LET(x, SUM(A1:A9), x/COUNT(A1:A9))   local bindings -- compute once, reuse
=FILTER(A1:A9, B1:B9 > 0)             dynamic arrays: FILTER/SORT/UNIQUE
=SUM(revenue)                         named range
=py.margin(A1, B1)                    HYBRID: call a code-block function
```

Excel error values (`#DIV/0!`, `#N/A`, `#NAME?`, `#REF!`, `#VALUE!`, `#NUM!`, `#NULL!`) propagate through arithmetic and are catchable with `IFERROR`/`IFNA`.

## The function library

**Built-in functions** (always available): `SUM`, `AVG`, `MIN`, `MAX`, `COUNT`, `ABS`, `SQRT`, `INT`, plus everything in `math` (`sin`, `cos`, `log`, `pi`, `e`, and the rest).

**Excel-compatible library** (auto-loaded in `EXCEL` and `HYBRID`): `IF`, `IFERROR`, `AND`, `OR`, `NOT`, `ROUND`, `AVERAGE`, `MEDIAN`, `SUMIF`, `COUNTIF`, `AVERAGEIF`, `LET`, `VLOOKUP`, `HLOOKUP`, `XLOOKUP`, `XMATCH`, `INDEX`, `MATCH`, `FILTER`, `SORT`, `UNIQUE`, `SEQUENCE`, `CONCATENATE`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `SUBSTITUTE`, and 280 others. Dynamic-array functions return whole rows and columns and compose: `=INDEX(SORT(A1:B9), 1, 2)`.

The [function coverage audit](../function_coverage.md) tracks the library against Microsoft's documented function set, including what is deliberately absent.

**PYTHON-only extras**: the `math` module, Python builtins (`sum`, `min`, `max`, `abs`, `len`), list comprehensions, and -- when the relevant extras are installed -- `np.array(...)`, `np.linalg`, matrix multiply (`@`), and `pd.DataFrame(...)`.

![A cell holding =np.array([[1,2],[3,4]]); the status line reads ndarray(2, 2) [1, 2, 3, 4]](../media/terminal-large-ndarray.png)

*PYTHON mode: B19 holds a numpy array. The cell shows the shape badge `[2x2]`; the status line shows the value.*

## Array cells

In PYTHON mode an array stays in the one cell that produced it instead of spilling across its neighbours. That cell shows a badge, not the contents:

| Value | Cell shows | Example |
|---|---|---|
| `Vec` | first element and length | `13750[4]` |
| 1D ndarray | length | `[4]` |
| 2D ndarray | rows and columns | `[2x2]` |
| DataFrame | rows and columns | `df[4x3]` |

The status line prints the full value for the cursor cell. Press `E` on a `Vec`, ndarray, or DataFrame cell to open the object editor and edit elements in a sub-grid.

## Named ranges and custom functions

```text
:name revenue A1:A12       Define a named range (workbook-global)
:names                     List
:unname revenue            Remove
```

Used directly in formulas: `=SUM(revenue)`, `=MAX(revenue - costs)`.

Open the per-workbook Python code block with `:e`. Anything defined there becomes callable from formulas:

```python
def margin(rev, cost):
    return (rev - cost) / rev * 100
```

In `HYBRID`: `=py.margin(A1, B1)`. In `PYTHON`: `=margin(A1, B1)`. `EXCEL` mode forbids code blocks entirely -- see [Formula modes](modes.md).

## Cell references

`$A$1` fixes both; `$A1` fixes the column; `A$1` fixes the row. References adjust automatically on insert, delete, and replicate.

Cross-sheet references (`=Sheet2!A1`) are covered in [Multi-sheet workbooks](sheets.md).
