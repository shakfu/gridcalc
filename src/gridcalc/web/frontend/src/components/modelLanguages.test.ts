import { expect, test } from 'vitest'
import type { StreamLanguage } from '@codemirror/language'
import { gmpl, minizinc } from './modelLanguages'

// `[token type, text]` for each highlighted span, from the parser's tree.
function tokens(lang: StreamLanguage<unknown>, text: string): [string, string][] {
  const out: [string, string][] = []
  lang.parser.parse(text).iterate({
    enter: (n) => {
      if (n.from < n.to && n.name !== 'Document' && n.name !== '⚠') {
        out.push([n.name, text.slice(n.from, n.to)])
      }
    },
  })
  return out
}

test('MiniZinc tokens', () => {
  const got = tokens(
    minizinc as StreamLanguage<unknown>,
    'include "globals.mzn"; % note\narray[W] of var 0..9: x :: output;\n/* a\nb */ solve satisfy;',
  )
  expect(got).toEqual([
    ['keyword', 'include'],
    ['string', '"globals.mzn"'],
    ['comment', '% note'],
    ['keyword', 'array'],
    ['variableName', 'W'],
    ['keyword', 'of'],
    ['keyword', 'var'],
    ['number', '0'],
    ['operator', '..'],
    ['number', '9'],
    ['operator', ':'],
    ['variableName', 'x'],
    ['operator', '::'],
    ['keyword', 'output'],
    ['comment', '/* a'],
    ['comment', 'b */'],
    ['keyword', 'solve'],
    ['keyword', 'satisfy'],
  ])
})

test('GMPL tokens', () => {
  const got = tokens(
    gmpl as StreamLanguage<unknown>,
    "s.t. sup{w in W}: sum{b in B} x[w,'New York'] <= cap; # c\nparam s default Infinity;",
  )
  expect(got.filter(([t]) => t !== 'variableName' && t !== 'operator')).toEqual([
    ['keyword', 's.t.'],
    ['keyword', 'in'],
    ['variableName.standard', 'sum'],
    ['keyword', 'in'],
    ['string', "'New York'"],
    ['comment', '# c'],
    ['keyword', 'param'],
    ['keyword', 'default'],
    ['atom', 'Infinity'],
  ])
  expect(got).toContainEqual(['variableName', 's']) // a param named s is not a keyword
})
