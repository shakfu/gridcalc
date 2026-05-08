# Excel function coverage

Status of EXCEL/HYBRID-mode function library against Microsoft's
documented Excel function set. Implemented functions live in
`src/gridcalc/libs/xlsx.py` (registered via `BUILTINS`) plus a handful
of bare aggregates and trig in `src/gridcalc/engine.py`
(`_make_eval_globals`).

**As of last audit: 310 names in `xlsx.BUILTINS` plus 8 aggregates
(`SUM`/`AVG`/`MIN`/`MAX`/`COUNT`/`ABS`/`SQRT`/`INT`) and ~23
math constants/funcs in the engine globals — call it ~318 unique
Excel-callable names** out of ~480–500. Practical coverage is the
overwhelming majority of formulas seen in real workbooks. Remaining
gaps are now concentrated in Excel 365 functional features
(`LET`/`LAMBDA`/`MAP`/...) and 2D-aware return types
(`TRANSPOSE`/`LINEST`/...) — both architectural — plus low-value niche
families (bond/Treasury finance, complex numbers, numeral conversion,
unit conversion). The full statistical-distribution suite is now
covered.

## Currently implemented

Broad-enough categories. (Full registered list is the source of
truth — read `xlsx.BUILTINS` if in doubt.)

| Category | Functions |
|---|---|
| Aggregates | `SUM`, `AVG`/`AVERAGE`, `AVERAGEA`, `MIN`, `MINA`, `MAX`, `MAXA`, `COUNT`, `COUNTA`, `COUNTBLANK`, `MEDIAN`, `LARGE`, `SMALL`, `SUMPRODUCT`, `PRODUCT` |
| Conditional aggregates | `SUMIF`, `COUNTIF`, `AVERAGEIF`, `SUMIFS`, `COUNTIFS`, `AVERAGEIFS`, `MAXIFS`, `MINIFS` |
| Logical | `IF`, `AND`, `OR`, `NOT`, `IFERROR`, `IFS`, `SWITCH`, `IFNA`, `XOR` |
| Math | `ABS`, `INT`, `SQRT`, `MOD`, `POWER`, `SIGN`, `ROUND`, `ROUNDUP`, `ROUNDDOWN`, `CEILING`, `CEILING.MATH`, `FLOOR`, `FLOOR.MATH`, `MROUND`, `ODD`, `EVEN`, `FACT`, `GCD`, `LCM`, `TRUNC`, `QUOTIENT`, `COMBIN`, `COMBINA`, `PERMUT`, `PERMUTATIONA`, `MULTINOMIAL`, `RADIANS`, `DEGREES`, `SUMSQ`, `SUMX2MY2`, `SUMX2PY2`, `SUMXMY2`, `ERF`, `ERFC`, `GAMMA`, `GAMMALN`, `GAMMALN.PRECISE`, `PHI`, `STANDARDIZE` |
| Trig (engine globals) | `pi`, `e`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`, `log`, `log2`, `log10`, `floor`, `ceil`, `fabs`, `degrees`, `radians`, `fsum`, `isnan`, `isinf` |
| Hyperbolic | `SINH`, `COSH`, `TANH`, `ASINH`, `ACOSH`, `ATANH` |
| Bitwise | `BITAND`, `BITOR`, `BITXOR`, `BITLSHIFT`, `BITRSHIFT` |
| Random (volatile) | `RAND`, `RANDBETWEEN`, `RANDARRAY` |
| Lookup | `VLOOKUP`, `HLOOKUP`, `INDEX`, `MATCH`, `XLOOKUP`, `XMATCH`, `CHOOSE` |
| Reference | `ROW`, `COLUMN`, `ROWS`, `COLUMNS`, `ADDRESS` |
| Text | `CONCAT`, `CONCATENATE`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `PROPER`, `SUBSTITUTE`, `REPT`, `EXACT`, `FIND`, `SEARCH`, `REPLACE`, `TEXTJOIN`, `TEXTSPLIT`, `TEXTBEFORE`, `TEXTAFTER`, `CHAR`, `CODE`, `VALUE`, `TEXT`, `CLEAN`, `NUMBERVALUE`, `FIXED`, `DOLLAR`, `T`, `UNICHAR`, `UNICODE` |
| Date/time | `NOW`, `TODAY`, `DATE`, `TIME`, `DATEVALUE`, `TIMEVALUE`, `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`, `WEEKDAY`, `WEEKNUM`, `ISOWEEKNUM`, `EDATE`, `EOMONTH`, `DATEDIF`, `DAYS`, `DAYS360`, `YEARFRAC`, `NETWORKDAYS`, `WORKDAY` |
| Information | `ISNUMBER`, `ISTEXT`, `ISBLANK`, `ISERROR`, `ISNA`, `ISERR`, `ISLOGICAL`, `ISEVEN`, `ISODD`, `ISFORMULA`, `ISREF`, `ISNONTEXT`, `NA`, `N`, `TYPE`, `ERROR.TYPE` |
| Statistical (descriptive) | `STDEV`/`STDEV.S`/`STDEV.P`, `STDEVP`, `VAR`/`VAR.S`/`VAR.P`, `VARP`, `CORREL`, `COVAR`, `COVARIANCE.P`/`COVARIANCE.S`, `RANK`/`RANK.EQ`/`RANK.AVG`, `PERCENTILE`/`PERCENTILE.INC`/`PERCENTILE.EXC`, `QUARTILE`/`QUARTILE.INC`/`QUARTILE.EXC`, `MODE`/`MODE.SNGL`/`MODE.MULT`, `GEOMEAN`, `HARMEAN`, `AVEDEV`, `DEVSQ`, `SLOPE`, `INTERCEPT`, `RSQ`, `STEYX`, `SKEW`, `KURT`, `PERCENTRANK` |
| Statistical (distributions) | `NORM.DIST`/`NORM.INV`, `NORM.S.DIST`/`NORM.S.INV`, `T.DIST`/`T.DIST.2T`/`T.DIST.RT`/`T.INV`/`T.INV.2T`, `F.DIST`/`F.DIST.RT`/`F.INV`/`F.INV.RT`, `CHISQ.DIST`/`CHISQ.DIST.RT`/`CHISQ.INV`/`CHISQ.INV.RT`, `GAMMA.DIST`/`GAMMA.INV`, `BETA.DIST`/`BETA.INV`, `LOGNORM.DIST`/`LOGNORM.INV`, `WEIBULL.DIST`, `BINOM.DIST`/`BINOM.INV`, `NEGBINOM.DIST`, `POISSON.DIST`, `EXPON.DIST`, `HYPGEOM.DIST`, `CONFIDENCE.NORM`/`CONFIDENCE.T`, plus pre-2010 aliases (`NORMDIST`, `NORMSDIST`, `TDIST`, `TINV`, `FDIST`, `FINV`, `CHIDIST`, `CHIINV`, `GAMMADIST`, `GAMMAINV`, `BETADIST`, `BETAINV`, `LOGNORMDIST`, `LOGINV`, `WEIBULL`, `BINOMDIST`, `CRITBINOM`, `NEGBINOMDIST`, `HYPGEOMDIST`, `POISSON`, `EXPONDIST`, `CONFIDENCE`) |
| Statistical (tests) | `CHISQ.TEST`, `T.TEST`, `Z.TEST`, `PROB`, plus aliases `CHITEST`, `TTEST`, `ZTEST` |
| Forecasting (scalar) | `FORECAST`, `FORECAST.LINEAR`, `TREND` (scalar/1D new-x only) |
| Database (D-functions) | `DSUM`, `DAVERAGE`, `DCOUNT`, `DCOUNTA`, `DGET`, `DMAX`, `DMIN`, `DPRODUCT`, `DSTDEV`, `DSTDEVP`, `DVAR`, `DVARP` |
| Financial | `PV`, `FV`, `PMT`, `NPER`, `RATE`, `NPV`, `IRR`, `IPMT`, `PPMT`, `SLN`, `SYD`, `DB`, `DDB`, `VDB` (integer periods), `EFFECT`, `NOMINAL`, `CUMIPMT`, `CUMPRINC`, `MIRR`, `XNPV`, `XIRR` |
| Engineering — number-base | `DEC2BIN`, `DEC2OCT`, `DEC2HEX`, `BIN2DEC`, `OCT2DEC`, `HEX2DEC`, `BIN2OCT`, `BIN2HEX`, `OCT2BIN`, `OCT2HEX`, `HEX2BIN`, `HEX2OCT` |
| Excel 365 dynamic-array (1D-only) | `FILTER`, `SORT`, `UNIQUE`, `SEQUENCE`, `RANDARRAY`, `XLOOKUP`, `XMATCH` |

Dynamic-array entries operate on flat `Vec` data. They do not "spill"
into adjacent cells — the result Vec is held in a single cell and
consumed by surrounding formulas via `INDEX`, `SUM`, etc. True spill
semantics need a `Cell`/`Grid` model change.

## Gaps — by tractability

### Mechanical (low risk, hours-to-days of effort)

| Group | Missing | Notes |
|---|---|---|
| Numeral conversion | `ARABIC`, `ROMAN`, `BASE`, `DECIMAL` | Hours each, niche. |
| Engineering — other | `CONVERT` (unit conversion table), `DELTA`, `GESTEP` | `DELTA`/`GESTEP` trivial; `CONVERT` needs a unit-table data file. |
| Date variants | `NETWORKDAYS.INTL`, `WORKDAY.INTL` | Custom weekend masks + holiday lists. Hours. |
| Hyperlinks/external | `HYPERLINK`, `IMAGE`, `WEBSERVICE`, `FILTERXML`, `ENCODEURL`, `RTD` | Defer indefinitely — out of scope for a local TUI. |
| Bond/Treasury finance (~25) | `PRICE`, `YIELD`, `DURATION`, `MDURATION`, `COUPDAYBS`/...coupon family, `TBILLEQ`/`TBILLPRICE`/`TBILLYIELD`, `ACCRINT`/`ACCRINTM`, `RECEIVED`, `INTRATE`, `DOLLARDE`/`DOLLARFR`, `RRI`, `PDURATION`, `ISPMT` | Day-count conventions and coupon-period math are tedious but mechanical. Skip until requested by a real workbook. |
| Engineering — complex numbers (~40) | `COMPLEX`, `IMABS`, `IMAGINARY`, `IMREAL`, `IMSUM`, `IMPRODUCT`, ... | Need a string-encoded complex type round-tripped through `Cell`. Days of work; defer. |
| Statistical — fringe | `FISHER`, `FISHERINV`, `LARGE` (already have), `TRIMMEAN`, `KURT`/`SKEW.P`, `RANK.EQ`/`RANK.AVG` (already have), `PEARSON` (= `CORREL`), `F.TEST`, `Z.TEST.RT` | A handful of named conveniences over existing infra. Hour or two. |

### Architectural blockers

| Capability | Blocks | Notes |
|---|---|---|
| 2D-aware result type | `TRANSPOSE`, true `HSTACK`, `LINEST`/`LOGEST` 2D output, multi-regressor `TREND`/`GROWTH`, `FREQUENCY`, `CHOOSEROWS`/`CHOOSECOLS`, `WRAPROWS`/`WRAPCOLS`, full spill | `Vec` already carries `cols` for 2D ranges; need to wire it through arithmetic, persistence, and surrounding formula consumers. |
| Spilled results | Excel 365 spill semantics for `FILTER`/`SORT`/`UNIQUE`/`SEQUENCE`/`RANDARRAY`/the 2D-aware functions above | Today these return a `Vec` stored in one cell rather than spilling into neighbours. Major change to `Cell` model and recalc — depends on user demand. |
| Reference value type | `OFFSET`, `LOOKUP` (legacy), proper `INDIRECT`, `AREAS`, `FORMULATEXT` | Need a "reference object" distinct from a materialised value, threaded through the evaluator and dependency tracker. `INDIRECT` is deliberately omitted — defeats static dep analysis. |
| Closures / let-binding | `LET`, `LAMBDA`, `BYROW`, `BYCOL`, `MAP`, `REDUCE`, `SCAN`, `MAKEARRAY` | Evaluator currently has no environment for user-defined names beyond `named_ranges`. Requires real lexical scope. |
| Multi-sheet model | `SHEET`, `SHEETS`, cross-sheet refs in `INDIRECT` | Single-sheet today. |
| Cube / OLAP | `CUBEMEMBER`, `CUBEVALUE`, etc. | Out of scope. |

### Tricky-but-tractable

- **`TEXTSPLIT` with `pad_with`** — current implementation flattens 2D
  splits and ignores `pad_with`. Once 2D Vecs are real this becomes
  meaningful.
- **`VDB` fractional periods** — current implementation returns `#NUM!`
  for non-integer `start`/`end`. Excel's actual algorithm prorates
  partial periods; documented well in MS reference but tedious.
- **`XIRR` convergence on hard cases** — current Newton step caps at
  100 iterations with a single guess. Excel uses bisection fallback.
  Adequate for typical workbooks; switch to bisection if a user reports
  convergence failure.
- **Distribution inverses by bisection** — `F.INV`/`CHISQ.INV`/`GAMMA.INV`/`BETA.INV`
  use 200-step bisection on the CDF (1e-12 in p). ~10 decimal digits
  of accuracy in x, matching Excel's documented precision. Newton would
  be faster but the CDF is already an iterative approximation, so the
  payoff is small.
- **`CHISQ.TEST` on 2D contingency tables** — current implementation
  treats inputs as 1D arrays with `df = n - 1`. Excel's 2D form computes
  `df = (rows-1)(cols-1)` from row/column sums. Needs 2D Vec to fix
  cleanly.

## Summary

| Tier | Count | Effort | Priority |
|---|---|---|---|
| Implemented | ~318 | done | — |
| Numeral conversion + `CONVERT`/`DELTA`/`GESTEP` + `NETWORKDAYS.INTL`/`WORKDAY.INTL` + `FISHER`/`TRIMMEAN`/`PEARSON` | ~12 | 1 day | low — niche fillers |
| Bond/Treasury finance | ~25 | weeks | low — niche, no current asks |
| Complex numbers | ~40 | weeks | defer |
| Multi-regressor / 2D output (`LINEST`/`TRANSPOSE`/`HSTACK`/`FREQUENCY`/full spill) | many | weeks | blocked on 2D Vec |
| `LET`/`LAMBDA` family | 7 | weeks | blocked on evaluator scope |
| `OFFSET`/`LOOKUP`/`AREAS`/`FORMULATEXT` | ~5 | weeks | blocked on reference type |
| External I/O / cube | many | — | out of scope |

The only mechanical batches left are small (numeral conversion,
unit conversion, fringe stats) and add little practical coverage. The
real next move is a strategic call between **architectural lifts**
(2D Vec / reference type / lexical scope) — each unblocks a whole
family — and **deferring further work** until a concrete workbook
demands something specific. Bond/Treasury finance and complex numbers
are best driven by demand rather than coverage-completeness.
