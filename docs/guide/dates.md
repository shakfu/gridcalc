# Dates

A date is a number wearing a number format. `2024-01-01` is stored as
`45292`, and what makes it a date rather than forty-five thousand is the
format attached to the cell. gridcalc uses the same model Excel does, which is
what lets date arithmetic work without a separate date type:

```text
        A            B
1  2024-01-01   =A2-A1        -> 74.5   (days, not a date)
2  2024-03-15
```

Subtracting two dates gives a plain number because that is what the answer is.
Only cells you actually format as dates display as dates.

## Reading dates from Excel

`gridcalc book.xlsx` reads each cell's number format and keeps it, so a column
that looked like dates in Excel looks like dates here. A workbook that spells
its dates `d-mmm-yy` keeps that spelling; nothing is normalised on the way in.

Cells with no date format arrive as ordinary numbers, which is deliberate. The
classification is conservative — a format has to contain a real date token to
count — because misreading a price format as a date would turn `1974.00` into
a day in 1975, and a date shown as a serial is a much smaller problem than a
number shown as a date.

## Formatting a cell as a date

`:f` takes an Excel date format alongside the formats it already accepted:

```text
:f yyyy-mm-dd            2024-01-01
:f d-mmm-yy              1-Jan-24
:f mmmm d, yyyy          January 1, 2024
:f dddd                  Monday
:f yyyy-mm-dd h:mm       2024-03-15 12:00
:f h:mm AM/PM            12:00 PM
```

The supported tokens are `yyyy`/`yy`, `mmmm`/`mmm`/`mm`/`m`,
`dddd`/`ddd`/`dd`/`d`, `hh`/`h`, `ss`/`s`, `AM/PM`, and text in double quotes.
Anything else in the code is printed as written, so `yyyy" (Q1)"` works.

As everywhere `m` appears, it means months before an hour token and minutes
after one — `mm` is January, `h:mm` is half past.

The same command works in the desktop app; both frontends format through one
implementation, so a sheet renders identically in either.

## Writing dates back

`:xlsx save` writes the format along with the serial, so a workbook edited
here and reopened in Excel still shows dates. Distinct formats stay distinct —
a column of days and a column of timestamps do not collapse into each other.

Only date formats round-trip. Fonts, fills, borders and non-date number
formats are not read or written; see [Limitations](../reference/limitations.md).

## Dates in criteria

`COUNTIF` and its relatives understand a date on the right-hand side, so the
obvious thing works:

```text
=COUNTIF(A1:A100, ">1/1/2020")
=COUNTIF(A1:A100, "<2020-01-01")
=SUMIF(A1:A100, ">=2024-01-01", B1:B100)
```

The operand is converted to a serial before comparing. Without that it would
be a string comparison, where `"9/1/2020"` sorts *after* `"10/1/2020"` and the
count comes back quietly wrong rather than as an error.

Accepted spellings are `2020-01-01`, `2020/01/01`, `1/1/2020` (month first,
as Excel reads it), `15-Jun-2020`, `Jun 15, 2020`, and `15 June 2020`. ISO is
worth preferring
in a file other people will read: `03/04/2026` is the third of April to half
the world and the fourth of March to the other half.

## Date functions

The usual set is available and works on serials: `TODAY`, `NOW`, `DATE`,
`TIME`, `DATEVALUE`, `TIMEVALUE`, `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`,
`SECOND`, `WEEKDAY`, `EDATE`, `EOMONTH`, `DATEDIF`, `DAYS`, `NETWORKDAYS`,
`WORKDAY`, `YEARFRAC`. See the
[function coverage audit](../function_coverage.md) for the full list.

```text
=DATE(2026, 5, 5)          the serial for 2026-05-05
=YEAR(A1)                  2026
=EOMONTH(A1, 0)            the last day of that month
```

A formula that returns a date returns a serial, so give the cell a date format
to see it as one:

```text
:f yyyy-mm-dd
```

## The 1900 leap-year bug

Excel believes 1900 was a leap year and reserves serial 60 for a
29 February 1900 that never happened. gridcalc uses an epoch of
1899-12-30, which makes every serial above 60 agree with Excel exactly — the
range every real workbook lives in. Below that the two differ by a day, since
matching the bug would mean producing a date that does not exist.
