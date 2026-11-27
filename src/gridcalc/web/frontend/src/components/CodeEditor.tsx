import { useEffect, useRef } from 'react'
import { EditorView, basicSetup } from 'codemirror'
import { Annotation, Compartment, EditorState, type Extension } from '@codemirror/state'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'
import { gmpl, minizinc } from './modelLanguages'

// Marks a document replaced from `value`, which is not the user's edit.
const external = Annotation.define<boolean>()

interface CodeEditorProps {
  value: string
  onChange: (text: string) => void
  // 1-based line to put the cursor on, e.g. where a model failed.
  gotoLine?: number | null
  ariaLabel?: string
  // Highlighting: the model's language, or none.
  language?: CodeLanguage
  // Shown, not edited: the trust dialog's preview of a file's code.
  readOnly?: boolean
}

export type CodeLanguage = 'python' | 'gmpl' | 'minizinc' | 'plain'

// The editor mode for a sheet's model language; every other language is Python text.
export function languageOf(lang: string): CodeLanguage {
  return lang === 'gmpl' || lang === 'minizinc' ? lang : 'python'
}

function highlighting(language: CodeLanguage): Extension {
  return { python: python(), gmpl, minizinc, plain: [] }[language]
}

// A CodeMirror 6 code editor. The view is created once; a `value` that
// differs from the document (a sheet switch, an undo) replaces it, while the
// user's own edits flow out through `onChange` without a round trip.
export function CodeEditor({
  value,
  onChange,
  gotoLine,
  ariaLabel,
  language = 'python',
  readOnly = false,
}: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const lang = useRef(new Compartment())
  const change = useRef(onChange)
  change.current = onChange

  useEffect(() => {
    if (!host.current) return
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          lang.current.of(highlighting(language)),
          oneDark,
          EditorView.lineWrapping,
          ...(readOnly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : []),
          EditorView.contentAttributes.of({ 'aria-label': ariaLabel ?? 'model text' }),
          EditorView.updateListener.of((u) => {
            if (u.docChanged && !u.transactions.some((t) => t.annotation(external))) {
              change.current(u.state.doc.toString())
            }
          }),
        ],
      }),
    })
    view.current = v
    return () => {
      v.destroy()
      view.current = null
    }
    // Created once; later `value`s arrive through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const v = view.current
    if (!v || v.state.doc.toString() === value) return
    v.dispatch({
      changes: { from: 0, to: v.state.doc.length, insert: value },
      annotations: external.of(true),
    })
  }, [value])

  useEffect(() => {
    view.current?.dispatch({
      effects: lang.current.reconfigure(highlighting(language)),
    })
  }, [language])

  useEffect(() => {
    const v = view.current
    if (!v || !gotoLine || gotoLine > v.state.doc.lines) return
    const line = v.state.doc.line(gotoLine)
    v.dispatch({ selection: { anchor: line.from, head: line.to }, scrollIntoView: true })
    v.focus()
  }, [gotoLine])

  return <div className="code-editor" ref={host} />
}
