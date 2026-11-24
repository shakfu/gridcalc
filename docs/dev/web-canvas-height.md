# Web grid canvas height

Status: fixed 2026-11-24.

## Symptom

`gridcalc-web` took about 20 s to show the trust dialog, and a cursor move took 1-5 s. Python answered every bridge call in under 1 ms.

## Cause

The grid's scroll canvas was the whole sheet: 1,048,576 rows x 22 px, about 23 million px tall, and 1.5 million px wide. In WKWebView (macOS 26.7.3, WebKit 21624.5.1.11.3) a page loaded with such a canvas blocks its main thread for about 8.2 s, repeatedly, even when idle; the page process runs at 65-75% CPU meanwhile. Bridge results queue behind each block, so startup waited on two blocks and a cursor move that landed in one waited for it to end. Chromium runs the same bundle without blocking.

Measured with a head script that timestamps bridge calls and logs any gap over 200 ms between 50 ms ticks, the driver silent meanwhile (polling with `evaluate_js` itself stalls the bridge and gave false readings):

| Canvas height | Block |
|-|-|
| 3,000 px | none |
| 1,000,000 px | 0.43 s |
| 4,000,000 px | 1.5 s |
| 8,000,000 px | 3.0 s |
| 16,000,000 px | 6.0 s |
| 23,000,000 px (the sheet) | 8.2 s, repeating |

Hiding the column lines or the overlay layers changed nothing. A blank page with the same bridge never blocked. The bundle at c60c573, before the cross-tab model work, blocked the same way, but painted the grid before the first block.

## Fix

The canvas spans the used cells, the cursor, the selection and the scrolled-to region, plus 200 rows and 26 columns of slack (`span` in `Grid.tsx`). Scrolling to its end grows it; it never shrinks, so the scrollbar does not jump. `ensureVisible` grows it before scrolling, so a jump to a far cell lands. `Api.dims` reports `used_rows`/`used_cols` per sheet.

After: the grid paints and the trust dialog shows about 150 ms after load; a cursor move takes 5-10 ms.

## Not explained

A canvas grown to 19.8 million px by a jump to A900000 after load did not block, including after jumping back to A1. The blocking seems tied to a canvas that size at page load, not to the size alone. Not characterised further.
