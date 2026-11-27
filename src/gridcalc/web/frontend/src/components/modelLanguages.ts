import { StreamLanguage, type StringStream } from '@codemirror/language'

// Highlighting for the model languages that are not Python. Tokens only: no
// parse tree, so no folding or indentation beyond CodeMirror's defaults.

interface Spec {
  name: string
  lineComment: string
  quotes: string
  keywords: string[]
  builtins: string[]
  atoms: string[]
  // A keyword that is not one word, such as GMPL's `s.t.`.
  phrase?: RegExp
}

interface State {
  inComment: boolean
}

function define(spec: Spec) {
  const keywords = new Set(spec.keywords)
  const builtins = new Set(spec.builtins)
  const atoms = new Set(spec.atoms)
  function token(stream: StringStream, state: State): string | null {
    if (state.inComment) {
      state.inComment = !stream.skipTo('*/')
      if (state.inComment) stream.skipToEnd()
      else stream.match('*/')
      return 'comment'
    }
    if (stream.eatSpace()) return null
    if (stream.match('/*')) {
      state.inComment = true
      return token(stream, state)
    }
    if (stream.match(spec.lineComment)) {
      stream.skipToEnd()
      return 'comment'
    }
    const ch = stream.peek()!
    if (spec.quotes.includes(ch)) {
      stream.next()
      // A backslash escapes in MiniZinc. GMPL doubles a quote: two strings, both highlighted.
      while (!stream.eol()) {
        const c = stream.next()
        if (c === '\\') stream.next()
        else if (c === ch) break
      }
      return 'string'
    }
    if (spec.phrase && stream.match(spec.phrase)) return 'keyword'
    if (stream.match(/^\d+(\.\d+)?([eE][+-]?\d+)?/)) return 'number'
    if (stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)) {
      const w = stream.current()
      if (keywords.has(w)) return 'keyword'
      if (builtins.has(w)) return 'builtin'
      if (atoms.has(w)) return 'atom'
      return 'variableName'
    }
    if (stream.match(/^(::|:=|\.\.|<=|>=|==|!=|<>|->|<-|\/\\|\\\/|[-+*/^<>=!|&:])/)) return 'operator'
    stream.next()
    return null
  }
  return StreamLanguage.define<State>({
    name: spec.name,
    startState: () => ({ inComment: false }),
    token,
    languageData: { commentTokens: { line: spec.lineComment, block: { open: '/*', close: '*/' } } },
  })
}

export const gmpl = define({
  name: 'gmpl',
  lineComment: '#',
  quotes: '\'"',
  keywords: [
    'set', 'param', 'var', 'minimize', 'maximize', 'subject', 'subj', 'to',
    'solve', 'data', 'end', 'display', 'printf', 'print', 'for', 'check', 'table',
    'in', 'within', 'cross', 'union', 'inter', 'diff', 'symdiff', 'setof', 'by',
    'if', 'then', 'else', 'and', 'or', 'not', 'mod', 'div', 'less', 'default', 'dimen',
    'integer', 'binary', 'symbolic', 'logical',
  ],
  builtins: [
    'sum', 'prod', 'min', 'max', 'forall', 'exists', 'abs', 'ceil', 'floor', 'round',
    'trunc', 'exp', 'log', 'log10', 'sqrt', 'sin', 'cos', 'atan', 'card', 'length',
    'substr', 'str2time', 'time2str', 'gmtime', 'Uniform', 'Uniform01', 'Normal', 'Normal01',
    'Irand224',
  ],
  atoms: ['Infinity'],
  phrase: /^s\.t\./,
})

export const minizinc = define({
  name: 'minizinc',
  lineComment: '%',
  quotes: '"',
  keywords: [
    'annotation', 'any', 'array', 'bool', 'case', 'constraint', 'diff', 'div', 'else',
    'elseif', 'endif', 'enum', 'float', 'function', 'if', 'in', 'include', 'int',
    'intersect', 'let', 'list', 'maximize', 'minimize', 'mod', 'not', 'of', 'op', 'opt',
    'output', 'par', 'predicate', 'record', 'satisfy', 'set', 'solve', 'string', 'subset',
    'superset', 'symdiff', 'test', 'then', 'tuple', 'type', 'union', 'var', 'where', 'xor',
  ],
  builtins: [
    'sum', 'product', 'min', 'max', 'forall', 'exists', 'abs', 'card', 'index_set',
    'length', 'show', 'trace', 'assert', 'fix', 'bool2int', 'int2float', 'ceil', 'floor',
    'round', 'sqrt', 'pow', 'exp', 'ln', 'log', 'alldifferent', 'all_different',
    'cumulative', 'circuit', 'element', 'count', 'global_cardinality', 'table',
    'lex_lesseq', 'inverse', 'regular', 'among', 'increasing', 'decreasing',
  ],
  atoms: ['true', 'false'],
})
