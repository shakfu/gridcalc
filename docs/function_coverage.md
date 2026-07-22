# Excel function coverage

Status of EXCEL/HYBRID-mode function library against Microsoft's
documented Excel function set. Implemented functions live in
`src/gridcalc/libs/xlsx.py` (registered via `BUILTINS`) plus a handful
of bare aggregates and trig in `src/gridcalc/engine.py`
(`_make_eval_globals`).

**As of last audit: 405 names in `xlsx.BUILTINS` (plus `LET`/`LAMBDA`,
handled in the evaluator) plus 8 aggregates
(`SUM`/`AVG`/`MIN`/`MAX`/`COUNT`/`ABS`/`SQRT`/`INT`) and ~23
math constants/funcs in the engine globals — call it ~415 unique
Excel-callable names** out of ~480–500. Practical coverage is the
overwhelming majority of formulas seen in real workbooks, and all four
architectural lifts have landed. The 2D-aware return types (`TRANSPOSE`,
`LINEST`/`LOGEST`, `HSTACK`/`VSTACK`, `CHOOSEROWS`/`CHOOSECOLS`,
multi-regressor `TREND`/`GROWTH`, reshape functions, `FREQUENCY`) run on
the `Vec` `cols` machinery and spill into neighbour cells. The full
statistical-distribution suite, the complex-number (`IM*`) family,
numeral conversion (`ROMAN`/`ARABIC`/`BASE`/`DECIMAL`), the entire
bond/Treasury finance family (coupon `PRICE`/`YIELD`/`DURATION`, the
`COUP*` schedule functions, discounted and at-maturity securities,
T-bills), unit conversion (`CONVERT`), the fringe stats
(`SKEW.P`/`F.TEST`), the lexical-scope family
(`LET`/`LAMBDA`/`MAP`/`REDUCE`/`SCAN`/`BYROW`/`BYCOL`/`MAKEARRAY`), and
the reference value type (`OFFSET`/`FORMULATEXT`/`AREAS`/`LOOKUP`) are
all covered. What remains is out of scope by design (external I/O,
cube/OLAP, `INDIRECT`).

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
| Lookup | `VLOOKUP`, `HLOOKUP`, `INDEX`, `MATCH`, `XLOOKUP`, `XMATCH`, `CHOOSE`, `LOOKUP` (vector + array) |
| Reference | `ROW`, `COLUMN`, `ROWS`, `COLUMNS`, `ADDRESS`, `OFFSET`, `FORMULATEXT`, `AREAS`, `ISREF` |
| Text | `CONCAT`, `CONCATENATE`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `PROPER`, `SUBSTITUTE`, `REPT`, `EXACT`, `FIND`, `SEARCH`, `REPLACE`, `TEXTJOIN`, `TEXTSPLIT`, `TEXTBEFORE`, `TEXTAFTER`, `CHAR`, `CODE`, `VALUE`, `TEXT`, `CLEAN`, `NUMBERVALUE`, `FIXED`, `DOLLAR`, `T`, `UNICHAR`, `UNICODE` |
| Date/time | `NOW`, `TODAY`, `DATE`, `TIME`, `DATEVALUE`, `TIMEVALUE`, `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`, `WEEKDAY`, `WEEKNUM`, `ISOWEEKNUM`, `EDATE`, `EOMONTH`, `DATEDIF`, `DAYS`, `DAYS360`, `YEARFRAC`, `NETWORKDAYS`, `NETWORKDAYS.INTL`, `WORKDAY`, `WORKDAY.INTL` |
| Information | `ISNUMBER`, `ISTEXT`, `ISBLANK`, `ISERROR`, `ISNA`, `ISERR`, `ISLOGICAL`, `ISEVEN`, `ISODD`, `ISFORMULA`, `ISREF`, `ISNONTEXT`, `NA`, `N`, `TYPE`, `ERROR.TYPE` |
| Statistical (descriptive) | `STDEV`/`STDEV.S`/`STDEV.P`, `STDEVP`, `VAR`/`VAR.S`/`VAR.P`, `VARP`, `CORREL`, `COVAR`, `COVARIANCE.P`/`COVARIANCE.S`, `RANK`/`RANK.EQ`/`RANK.AVG`, `PERCENTILE`/`PERCENTILE.INC`/`PERCENTILE.EXC`, `QUARTILE`/`QUARTILE.INC`/`QUARTILE.EXC`, `MODE`/`MODE.SNGL`/`MODE.MULT`, `GEOMEAN`, `HARMEAN`, `AVEDEV`, `DEVSQ`, `SLOPE`, `INTERCEPT`, `RSQ`, `STEYX`, `SKEW`, `KURT`, `PERCENTRANK` |
| Statistical (distributions) | `NORM.DIST`/`NORM.INV`, `NORM.S.DIST`/`NORM.S.INV`, `T.DIST`/`T.DIST.2T`/`T.DIST.RT`/`T.INV`/`T.INV.2T`, `F.DIST`/`F.DIST.RT`/`F.INV`/`F.INV.RT`, `CHISQ.DIST`/`CHISQ.DIST.RT`/`CHISQ.INV`/`CHISQ.INV.RT`, `GAMMA.DIST`/`GAMMA.INV`, `BETA.DIST`/`BETA.INV`, `LOGNORM.DIST`/`LOGNORM.INV`, `WEIBULL.DIST`, `BINOM.DIST`/`BINOM.INV`, `NEGBINOM.DIST`, `POISSON.DIST`, `EXPON.DIST`, `HYPGEOM.DIST`, `CONFIDENCE.NORM`/`CONFIDENCE.T`, plus pre-2010 aliases (`NORMDIST`, `NORMSDIST`, `TDIST`, `TINV`, `FDIST`, `FINV`, `CHIDIST`, `CHIINV`, `GAMMADIST`, `GAMMAINV`, `BETADIST`, `BETAINV`, `LOGNORMDIST`, `LOGINV`, `WEIBULL`, `BINOMDIST`, `CRITBINOM`, `NEGBINOMDIST`, `HYPGEOMDIST`, `POISSON`, `EXPONDIST`, `CONFIDENCE`) |
| Statistical (tests) | `CHISQ.TEST`, `T.TEST`, `Z.TEST`, `PROB`, plus aliases `CHITEST`, `TTEST`, `ZTEST` |
| Statistical (fringe) | `FISHER`, `FISHERINV`, `TRIMMEAN`, `PEARSON` (= `CORREL`), `SKEW.P`, `F.TEST` |
| Forecasting (scalar) | `FORECAST`, `FORECAST.LINEAR`, `TREND` (scalar/1D new-x only) |
| Array (spilling) | `FREQUENCY` (counts into bins), plus `TREND`/`GROWTH`/`LINEST`/`SEQUENCE`/`SORT`/`FILTER`/`UNIQUE`/... which now spill |
| Database (D-functions) | `DSUM`, `DAVERAGE`, `DCOUNT`, `DCOUNTA`, `DGET`, `DMAX`, `DMIN`, `DPRODUCT`, `DSTDEV`, `DSTDEVP`, `DVAR`, `DVARP` |
| Financial | `PV`, `FV`, `PMT`, `NPER`, `RATE`, `NPV`, `IRR`, `IPMT`, `PPMT`, `SLN`, `SYD`, `DB`, `DDB`, `VDB` (integer periods), `EFFECT`, `NOMINAL`, `CUMIPMT`, `CUMPRINC`, `MIRR`, `XNPV`, `XIRR`, `RRI`, `PDURATION`, `ISPMT`, `DOLLARDE`, `DOLLARFR` |
| Financial — bonds | `PRICE`, `YIELD`, `DURATION`, `MDURATION`, `ACCRINT`, `ACCRINTM`, `DISC`, `PRICEDISC`, `YIELDDISC`, `PRICEMAT`, `YIELDMAT`, `RECEIVED`, `INTRATE`, `COUPPCD`, `COUPNCD`, `COUPNUM`, `COUPDAYBS`, `COUPDAYS`, `COUPDAYSNC` |
| Financial — Treasury | `TBILLEQ`, `TBILLPRICE`, `TBILLYIELD` |
| Engineering — number-base | `DEC2BIN`, `DEC2OCT`, `DEC2HEX`, `BIN2DEC`, `OCT2DEC`, `HEX2DEC`, `BIN2OCT`, `BIN2HEX`, `OCT2BIN`, `OCT2HEX`, `HEX2BIN`, `HEX2OCT` |
| Engineering — comparison | `DELTA`, `GESTEP` |
| Engineering — unit conversion | `CONVERT` (mass, distance, time, pressure, force, energy, power, magnetism, temperature, volume, area, speed, information; SI + binary prefixes) |
| Engineering — complex | `COMPLEX`, `IMREAL`, `IMAGINARY`, `IMABS`, `IMARGUMENT`, `IMCONJUGATE`, `IMSUM`, `IMSUB`, `IMPRODUCT`, `IMDIV`, `IMPOWER`, `IMSQRT`, `IMEXP`, `IMLN`, `IMLOG10`, `IMLOG2`, `IMSIN`, `IMCOS`, `IMTAN`, `IMSINH`, `IMCOSH`, `IMSEC`, `IMCSC`, `IMCOT`, `IMSECH`, `IMCSCH` |
| Numeral conversion | `ROMAN` (classic form), `ARABIC`, `BASE`, `DECIMAL` |
| Lexical scope (Excel 365) | `LET`, `LAMBDA` (evaluator), `MAP`, `REDUCE`, `SCAN`, `BYROW`, `BYCOL`, `MAKEARRAY` |
| Excel 365 dynamic-array (1D-only) | `FILTER`, `SORT`, `UNIQUE`, `SEQUENCE`, `RANDARRAY`, `XLOOKUP`, `XMATCH` |

Dynamic-array results now **spill** into adjacent cells (EXCEL/HYBRID
mode): a multi-cell result fills a rectangle anchored at the formula
cell, a bare reference reads the anchor's top-left scalar, and the whole
array is reached with the `A1#` spill-range operator. A blocked
rectangle yields `#SPILL!`. See the "Spill" note below.

## Gaps — by tractability

### Mechanical (low risk, hours-to-days of effort)

The mechanical batches are effectively exhausted. What is left is either
out of scope or blocked on an architectural change (below).

| Group | Missing | Notes |
|---|---|---|
| Hyperlinks/external | `HYPERLINK`, `IMAGE`, `WEBSERVICE`, `FILTERXML`, `ENCODEURL`, `RTD` | Defer indefinitely — out of scope for a local TUI. |

### Architectural blockers

| Capability | Blocks | Notes |
|---|---|---|
| 2D-aware result type — DONE | `TRANSPOSE`, `HSTACK`/`VSTACK`, `LINEST`/`LOGEST`, multi-regressor `TREND`/`GROWTH`, `CHOOSEROWS`/`CHOOSECOLS`, `WRAPROWS`/`WRAPCOLS`, `TAKE`/`DROP`/`EXPAND`/`TOROW`/`TOCOL`, `FREQUENCY` all landed on the `Vec` `cols` machinery, and results now spill into neighbour cells. | Complete. |
| Spilled results — DONE | Excel spill semantics for `FILTER`/`SORT`/`UNIQUE`/`SEQUENCE`/`RANDARRAY`/`FREQUENCY`/the 2D-aware functions | Landed: results spill into neighbour cells (`SPILL` cell type), `A1#` spill-range operator, `#SPILL!` on blockage, bounded-fixpoint recalc, and the TUI (cyan spill tint, scalar anchor display, status-bar provenance). |
| Reference value type — DONE | `OFFSET`, `LOOKUP`, `AREAS`, `FORMULATEXT` | Landed: a `Reference` value (a location) flows through the evaluator and materialises (`_deref`) wherever a value is expected. `OFFSET` returns one; `ROW`/`COLUMN`/`ROWS`/`COLUMNS`/`ISREF` consume one via `Env.resolve_ref`. `INDIRECT` stays omitted — a string-built reference defeats static dep analysis. |
| Closures / let-binding — DONE | `LET`, `LAMBDA`, `MAP`, `REDUCE`, `SCAN`, `BYROW`, `BYCOL`, `MAKEARRAY` all shipped. `LambdaValue` closes over the `LET` scope stack; a new `Apply` node + parser postfix layer gives direct `LAMBDA(...)(...)` application. | Recursion is not supported (would need Name-Manager lambdas and a lazy `IF`; `IF` here is an eager builtin). Lambda results do not spill — consumed via `INDEX`/`SUM`. |
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
- **`ACCRINT` actual/actual quasi-coupon** — accrued interest is computed
  as `par * rate * YEARFRAC(start, settlement, basis)`, exact for the
  30/360 and actual/360-365 bases. Excel's basis-1 form sums over
  quasi-coupon periods of varying length; the difference is tiny (and
  bounded by this library's `YEARFRAC` basis-1 approximation). Fix
  together with a Excel-exact actual/actual `YEARFRAC`.
- **`YIELD`/`YIELDMAT` by bisection** — invert `PRICE`/`PRICEMAT` with a
  bracketing bisection (200 steps, 1e-10 in price). Round-trips to ~1e-8
  in yield. Excel uses Newton; the payoff over an already-cheap bisection
  is negligible for a coupon bond.
- **`PRICE` single final period** — when settlement is inside the last
  coupon period (`COUPNUM == 1`), the final stub discounts with simple
  interest, matching Excel; earlier periods use compound discounting.
- **`CONVERT` unit table** — covers all thirteen Excel categories (mass,
  distance, time, pressure, force, energy, power, magnetism, temperature,
  volume, area, speed, information) with SI decimal prefixes and binary
  prefixes for `bit`/`byte`. Prefixes on temperature units and the most
  exotic cubic/area variants (`ly3`, `Nmi3`, `Pica2`, ...) are omitted;
  add entries to `_CONVERT_UNITS` if a workbook needs them.
- **`LAMBDA` recursion** — a self-referential lambda cannot terminate:
  `IF` is an eager builtin that evaluates both branches, and gridcalc's
  named ranges model only cell references, so there is no global lambda
  name to recurse through. The evaluator already resolves a syntactic
  named `LAMBDA` dynamically per call, so recursion would work once a
  lazy `IF` and Name-Manager lambdas exist.
- **Spill** — the anchor keeps the whole array in `arr` and its own
  displayed value is the top-left scalar; the extra elements materialise
  as `SPILL` cells (a new cell type) owned by the anchor. Reads follow
  Excel: `A1` is the scalar, `A1#` is the array. `#SPILL!` on a blocked
  or off-sheet rectangle; a blocked anchor is re-attempted on any edit,
  since it has no dependency on what blocks it. Recalc is a bounded
  fixpoint because spill shape is only known post-evaluation — a spill
  can create/destroy cells whose consumers were not in the current pass.
  Not persisted (rebuilt from the anchor on load). The TUI paints the
  spill block in a subtle cyan tint, shows the anchor's scalar instead of
  the `[n]` array badge, and names a spilled cell's origin in the status
  bar. Spilling is EXCEL/HYBRID only; PYTHON mode keeps arrays in one
  cell (and keeps the badge).

## Summary

| Tier | Count | Effort | Priority |
|---|---|---|---|
| Implemented | ~415 | done | — |
| External I/O / cube, `INDIRECT` | many | — | out of scope / by design |

The mechanical batches are exhausted and **all four architectural lifts
have now landed**: the 2D-aware result type unblocked the
`LINEST`/`TRANSPOSE`/stacking families (and `FREQUENCY`); lexical scope
brought `LET`/`LAMBDA`/`MAP`/`REDUCE`/`SCAN`/`BYROW`/`BYCOL`/`MAKEARRAY`;
cell spill lets dynamic-array results write into neighbour cells with the
`A1#` operator and `#SPILL!` semantics (engine and TUI); and the
reference value type brought `OFFSET`/`FORMULATEXT`/`AREAS`/`LOOKUP` with
a `Reference` that materialises wherever a value is expected. What
remains is out of scope by design: external I/O (`WEBSERVICE`, `RTD`,
hyperlinks), cube/OLAP, and `INDIRECT` (a string-built reference defeats
the static dependency analysis the topological recalc depends on).
Coverage is now the overwhelming majority of Excel's function set; drive
any further additions by a concrete workbook need.
