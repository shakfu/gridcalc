import type { CSSProperties } from 'react'
import type { CellStyle } from '../bridge/types'

// Excel border styles as CSS borders. Excel draws its dash patterns more
// finely than CSS can; these keep the weight and the solid/broken look.
const BORDER: Record<string, string> = {
  thin: '1px solid',
  medium: '2px solid',
  thick: '3px solid',
  hair: '1px dotted',
  dotted: '1px dotted',
  dashed: '1px dashed',
  dashDot: '1px dashed',
  dashDotDot: '1px dashed',
  mediumDashed: '2px dashed',
  mediumDashDot: '2px dashed',
  mediumDashDotDot: '2px dashed',
  slantDashDot: '2px dashed',
  double: '3px double',
}

const HALIGN: Record<string, CSSProperties['textAlign']> = {
  left: 'left',
  right: 'right',
  center: 'center',
  centerContinuous: 'center',
  justify: 'justify',
  distributed: 'justify',
  fill: 'left',
}

const VALIGN: Record<string, CSSProperties['alignItems']> = {
  top: 'flex-start',
  center: 'center',
  justify: 'center',
  distributed: 'center',
}

/** Inline CSS for a cell's xlsx style and number-format colour. */
export function cellCss(
  style: CellStyle | undefined,
  formatColor?: string,
  underline = false,
): CSSProperties {
  const css: CSSProperties = {}
  if (style?.fill) {
    css.background = '#' + style.fill
    css.color = '#000' // Excel's automatic text colour on a fill, in either theme
  }
  if (style?.color) css.color = '#' + style.color
  if (formatColor) css.color = formatColor // `[Red]` overrides the font colour
  if (style?.font) css.fontFamily = `"${style.font}", sans-serif`
  if (style?.size) css.fontSize = `${style.size}pt`
  if (style?.strike) css.textDecorationLine = underline ? 'underline line-through' : 'line-through'
  for (const side of ['left', 'right', 'top', 'bottom'] as const) {
    const s = style?.[side]
    if (!s) continue
    const key = ('border' + side[0].toUpperCase() + side.slice(1)) as
      | 'borderLeft'
      | 'borderRight'
      | 'borderTop'
      | 'borderBottom'
    css[key] = `${BORDER[s.style] ?? '1px solid'} ${s.color ? '#' + s.color : '#000'}`
    css.boxSizing = 'border-box'
  }
  if (style?.halign) css.textAlign = HALIGN[style.halign]
  if (style?.indent) css.paddingLeft = `${5 + 9 * style.indent}px`
  if (style?.valign || style?.wrap) {
    css.display = 'flex'
    css.alignItems = VALIGN[style.valign ?? ''] ?? 'flex-end'
    css.lineHeight = 'normal'
    css.justifyContent = { center: 'center', right: 'flex-end' }[css.textAlign as string] ?? 'flex-start'
  }
  if (style?.wrap) css.whiteSpace = 'normal'
  return css
}
