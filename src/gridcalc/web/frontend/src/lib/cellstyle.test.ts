import { cellCss } from './cellstyle'

describe('cellCss', () => {
  it('maps fill, font and borders', () => {
    const css = cellCss({
      fill: 'FFFF00',
      font: 'Arial',
      size: 14,
      left: { style: 'thick', color: 'FF0000' },
      bottom: { style: 'double', color: null },
    })
    expect(css.background).toBe('#FFFF00')
    expect(css.color).toBe('#000')
    expect(css.fontFamily).toBe('"Arial", sans-serif')
    expect(css.fontSize).toBe('14pt')
    expect(css.borderLeft).toBe('3px solid #FF0000')
    expect(css.borderBottom).toBe('3px double #000')
  })

  it('lets a number-format colour override the font colour', () => {
    expect(cellCss({ color: '0000FF' }, 'red').color).toBe('red')
  })

  it('aligns and wraps', () => {
    const css = cellCss({ halign: 'center', valign: 'top', wrap: true })
    expect(css.textAlign).toBe('center')
    expect(css.alignItems).toBe('flex-start')
    expect(css.justifyContent).toBe('center')
    expect(css.whiteSpace).toBe('normal')
  })

  it('is empty without a style', () => {
    expect(cellCss(undefined)).toEqual({})
  })
})
