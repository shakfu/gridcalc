# Excel function coverage

Status of EXCEL/HYBRID-mode function library against Microsoft's
documented Excel function set. Implemented functions live in
`src/gridcalc/libs/xlsx.py` (plus a handful of bare aggregates in
`src/gridcalc/engine.py`).

**As of last audit: 121 unique function names implemented out of
~480-500 in Excel.** Practical coverage is ~75% of formulas in typical
real-world spreadsheets; the gaps are mostly Excel 365 dynamic arrays,
full statistical distributions, and bond/depreciation math.

## Currently implemented (121)

Categories where coverage is broad enough to be useful:

| Category | Functions |
|---|---|
| Aggregates | `SUM`, `AVG`/`AVERAGE`, `MIN`, `MAX`, `COUNT`, `MEDIAN`, `LARGE`, `SMALL`, `SUMPRODUCT` |
| Conditional aggregates | `SUMIF`, `COUNTIF`, `AVERAGEIF`, `SUMIFS`, `COUNTIFS`, `AVERAGEIFS`, `MAXIFS`, `MINIFS` |
| Logical | `IF`, `AND`, `OR`, `NOT`, `IFERROR`, `IFS`, `SWITCH`, `IFNA`, `XOR` |
| Math | `ABS`, `INT`, `SQRT`, `MOD`, `POWER`, `SIGN`, `ROUND`, `ROUNDUP`, `ROUNDDOWN`, `CEILING`, `FLOOR`, `MROUND`, `ODD`, `EVEN`, `FACT`, `GCD`, `LCM`, `TRUNC` |
| Trig (via `_eval_globals`) | `pi`, `e`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`, `log`, `log2`, `log10`, `floor`, `ceil`, `fabs`, `degrees`, `radians` |
| Lookup | `VLOOKUP`, `HLOOKUP`, `INDEX`, `MATCH`, `CHOOSE` |
| Reference | `ROW`, `COLUMN`, `ROWS`, `COLUMNS` |
| Text | `CONCAT`, `CONCATENATE`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `PROPER`, `SUBSTITUTE`, `REPT`, `EXACT`, `FIND`, `SEARCH`, `REPLACE`, `TEXTJOIN`, `CHAR`, `CODE`, `VALUE`, `TEXT` |
| Date/time | `NOW`, `TODAY`, `DATE`, `TIME`, `DATEVALUE`, `TIMEVALUE`, `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`, `WEEKDAY`, `EDATE`, `EOMONTH`, `DATEDIF`, `NETWORKDAYS`, `WORKDAY` |
| Information | `ISNUMBER`, `ISTEXT`, `ISBLANK`, `ISERROR`, `ISNA`, `ISERR`, `ISLOGICAL`, `ISEVEN`, `ISODD`, `NA`, `N` |
| Statistical | `STDEV`, `STDEVP`, `VAR`, `VARP`, `CORREL`, `COVAR`, `RANK`, `PERCENTILE`, `QUARTILE`, `MODE`, `GEOMEAN`, `HARMEAN` |
| Financial | `PV`, `FV`, `PMT`, `NPER`, `RATE`, `NPV`, `IRR`, `IPMT`, `PPMT` |

## Gaps by tier

### Tier 3 — mechanical fill-ins (~50 functions)

No architectural changes. Tracked as a single TODO entry. ~1 day each.

| Category | Missing |
|---|---|
| Aggregates | `COUNTA`, `COUNTBLANK`, `PRODUCT`, `AVERAGEA`, `MAXA`, `MINA` |
| Stats (modern names) | `STDEV.S`, `STDEV.P`, `VAR.S`, `VAR.P`, `MODE.SNGL`, `MODE.MULT`, `COVARIANCE.P`, `COVARIANCE.S`, `PERCENTILE.INC`, `PERCENTILE.EXC`, `QUARTILE.INC`, `QUARTILE.EXC`, `RANK.EQ`, `RANK.AVG` |
| Stats (additional) | `AVEDEV`, `DEVSQ`, `SLOPE`, `INTERCEPT`, `RSQ`, `STEYX`, `SKEW`, `KURT`, `PERCENTRANK` |
| Date | `DAYS`, `DAYS360`, `WEEKNUM`, `ISOWEEKNUM`, `YEARFRAC` |
| Information | `ERROR.TYPE`, `TYPE`, `ISFORMULA`, `ISREF`, `ISNONTEXT` (`CELL` deferred — needs format/style metadata surface) |
| Text | `CLEAN`, `NUMBERVALUE`, `FIXED`, `DOLLAR`, `T`, `UNICHAR`, `UNICODE` |
| Math | `COMBIN`, `COMBINA`, `PERMUT`, `PERMUTATIONA`, `MULTINOMIAL`, `QUOTIENT`, `CEILING.MATH`, `FLOOR.MATH`, `RADIANS`, `DEGREES` (last two: uppercase aliases for existing `_eval_globals` entries) |
| Math (paired sums) | `SUMSQ`, `SUMX2MY2`, `SUMX2PY2`, `SUMXMY2` |
| Hyperbolic trig | `SINH`, `COSH`, `TANH`, `ASINH`, `ACOSH`, `ATANH` |
| Bitwise | `BITAND`, `BITOR`, `BITXOR`, `BITLSHIFT`, `BITRSHIFT` |
| Random (volatile) | `RAND`, `RANDBETWEEN` — must register as volatile so topo recalc adds them every pass |
| Reference | `ADDRESS` (deferred, mechanical) |

Two prerequisites worth knowing about:

- **`.` in function names** — `STDEV.S`, `PERCENTILE.INC`, etc. require
  the lexer/parser to accept dotted identifiers as function names.
  Worth verifying before touching this group.
- **Volatile registry** — `RAND`/`RANDBETWEEN` need a marker so the
  topo recalc closure includes them on every pass. Today
  `formula.deps.DYNAMIC_REF_FUNCS` covers `INDIRECT`/`OFFSET`/`INDEX`
  for the same purpose; either add to that set or introduce a parallel
  `VOLATILE_FUNCS` set.

`TRANSPOSE` is *not* in this tier — it returns a reshaped 2D array,
which requires a 2D-aware result type. Defer to dynamic-array work.

### Tier 4 — domain-specific extensions (~75 functions)

Complete categories where we have a representative subset.

**Financial** (have 9, missing ~40)
Depreciation (`DB`, `DDB`, `SLN`, `SYD`, `VDB`); cumulative
(`CUMIPMT`, `CUMPRINC`); rate conversion (`EFFECT`, `NOMINAL`); bonds
(`PRICE`, `PRICEDISC`, `PRICEMAT`, `YIELD`, `YIELDDISC`, `YIELDMAT`,
`DURATION`, `MDURATION`, coupon-period functions); Treasury
(`TBILLEQ`, `TBILLPRICE`, `TBILLYIELD`); non-periodic (`XIRR`, `XNPV`,
`MIRR`); odds and ends (`RRI`, `PDURATION`, `ISPMT`, `DOLLARDE`,
`DOLLARFR`, `ACCRINT`, `ACCRINTM`, `RECEIVED`, `INTRATE`).

Recommendation: add `DB`, `DDB`, `SLN`, `SYD`, `XIRR`, `XNPV` if
anyone runs financial models. Skip the rest until requested.

**Statistical distributions** (have 0, missing ~25)
`NORM.DIST`/`INV`, `NORM.S.DIST`/`INV`, `T.DIST`/`INV`/`TEST`,
`F.DIST`/`INV`/`TEST`, `CHISQ.DIST`/`INV`/`TEST`,
`BINOM.DIST`/`INV`, `NEGBINOM.DIST`, `POISSON.DIST`, `EXPON.DIST`,
`GAMMA.DIST`/`INV`, `BETA.DIST`/`INV`, `CONFIDENCE`, `PROB`.

Implementations exist in `scipy.stats`; bind them through if scipy
is acceptable as a dep. Otherwise hand-roll.

**Forecasting** (have 0, all require array results)
`FORECAST`, `FORECAST.LINEAR`, `TREND`, `GROWTH`, `LINEST`, `LOGEST`.

**Database / D-functions** (have 0)
`DAVERAGE`, `DCOUNT`, `DCOUNTA`, `DGET`, `DMAX`, `DMIN`, `DPRODUCT`,
`DSTDEV`, `DSTDEVP`, `DSUM`, `DVAR`, `DVARP`. Need column-header-driven
table semantics — a small DSL inside the function for criteria ranges.

**Date variants**
`NETWORKDAYS.INTL`, `WORKDAY.INTL` (custom weekend masks + holiday
lists).

### Tier 5 — architectural or niche (~250 functions)

| Group | Status |
|---|---|
| Excel 365 dynamic arrays | Need spilled-result support: results that occupy adjacent cells. Major change to `Cell` model and recalc. `FILTER`, `SORT`, `SORTBY`, `UNIQUE`, `SEQUENCE`, `RANDARRAY`, `XLOOKUP`, `XMATCH`, `TEXTSPLIT`, `TEXTBEFORE`, `TEXTAFTER`, `VSTACK`, `HSTACK`, `TAKE`, `DROP`, `CHOOSEROWS`, `CHOOSECOLS`, `TOROW`, `TOCOL`, `WRAPROWS`, `WRAPCOLS`, `EXPAND`, `MAKEARRAY`. |
| Excel 365 functional | `LET`, `LAMBDA`, `BYROW`, `BYCOL`, `MAP`, `REDUCE`, `SCAN`. Need closure / let-binding semantics in the evaluator. |
| Reference / dynamic | `OFFSET` (deferred — needs reference value type), `INDIRECT` (deliberately omitted — defeats static analysis), `LOOKUP` (older API, deprecated by `XLOOKUP`), `AREAS`, `FORMULATEXT`, `HYPERLINK`, `RTD`, `GETPIVOTDATA`. |
| Engineering — number-base | `BIN2DEC`, `DEC2BIN`, `HEX2DEC`, `DEC2HEX`, `OCT2BIN`, etc. (12) — niche but trivial. |
| Engineering — complex numbers | `COMPLEX`, `IMABS`, `IMAGINARY`, `IMREAL`, `IMSUM`, `IMPRODUCT`, ... (~40) — needs string-encoded complex type. |
| Engineering — other | `ERF`, `ERFC`, `CONVERT` (unit conversion), `DELTA`, `GESTEP`. |
| Cube / OLAP | `CUBEMEMBER`, `CUBEVALUE`, etc. — not relevant for a single-file spreadsheet. |
| Web / external | `ENCODEURL`, `FILTERXML`, `WEBSERVICE`, `IMAGE` — defer indefinitely. |
| Multi-sheet | `SHEET`, `SHEETS` — blocked on multi-sheet support. |
| Numeral conversion | `ARABIC`, `ROMAN`, `BASE`, `DECIMAL`. |
| Localization | `BAHTTEXT`, byte-aware text (`LEFTB`, `MIDB`, etc.) — irrelevant outside double-byte locales. |

## Summary

| Tier | Count | Effort | Priority |
|---|---|---|---|
| Implemented | ~121 | done | — |
| Tier 3 (mechanical) | ~50 | days | medium — fills holes |
| Tier 4 (financial / stat distributions / D-functions) | ~75 | weeks | low — domain-specific |
| Tier 5 (architectural / niche / Excel 365) | ~250 | months / N/A | mostly never |

The big remaining gaps are dynamic arrays (Excel 365), full
statistical distributions, and bond / depreciation math. None block
typical use; all are deferrable.
