import { useEffect, useRef } from 'react'
import { EditorView, basicSetup } from 'codemirror'
import { Annotation, EditorState } from '@codemirror/state'
import { python } from '@codemirror/lang-python'
import { oneDark } from '@codemirror/theme-one-dark'

// Marks a document replaced from `value`, which is not the user's edit.
const external = Annotation.define<boolean>()

interface CodeEditorProps {
  value: string
  onChange: (text: string) => void
  // 1-based line to put the cursor on, e.g. where a model failed.
  gotoLine?: number | null
  ariaLabel?: string
}

// A CodeMirror 6 Python editor. The view is created once; a `value` that
// differs from the document (a sheet switch, an undo) replaces it, while the
// user's own edits flow out through `onChange` without a round trip.
export function CodeEditor({ value, onChange, gotoLine, ariaLabel }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
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
          python(),
          oneDark,
          EditorView.lineWrapping,
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
    const v = view.current
    if (!v || !gotoLine || gotoLine > v.state.doc.lines) return
    const line = v.state.doc.line(gotoLine)
    v.dispatch({ selection: { anchor: line.from, head: line.to }, scrollIntoView: true })
    v.focus()
  }, [gotoLine])

  return <div className="code-editor" ref={host} />
}
