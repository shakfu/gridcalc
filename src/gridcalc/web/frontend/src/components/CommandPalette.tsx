import { useEffect, useMemo, useRef, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { rank, type Command } from '../lib/commands'

// Ctrl-K over the whole command set. Two steps: pick a command, and -- only
// for the commands that declare one -- supply an argument. The second step
// reuses the same input rather than opening a dialog per command, which is
// what makes registering `:width` or `:name` cost one registry entry.
export function CommandPalette({
  open,
  onOpenChange,
  commands,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  commands: Command[]
}) {
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  // Non-null once a command needing an argument has been chosen.
  const [pending, setPending] = useState<Command | null>(null)
  const [argValue, setArgValue] = useState('')
  const listEl = useRef<HTMLUListElement>(null)

  const matches = useMemo(() => (open ? rank(commands, query) : []), [commands, query, open])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setIndex(0)
    setPending(null)
    setArgValue('')
  }, [open])

  // Clamp rather than reset: narrowing the query should keep the highlight on
  // a real row, and resetting to 0 on every keystroke would fight the arrows.
  useEffect(() => {
    setIndex((i) => Math.min(i, Math.max(0, matches.length - 1)))
  }, [matches.length])

  // Keep the highlighted row in view when arrowing past the visible window.
  useEffect(() => {
    listEl.current?.children[index]?.scrollIntoView({ block: 'nearest' })
  }, [index])

  const choose = (cmd: Command) => {
    if (cmd.arg) {
      setPending(cmd)
      setArgValue(cmd.arg.initial?.() ?? '')
      return
    }
    cmd.run('')
    onOpenChange(false)
  }

  const submitArg = () => {
    if (!pending) return
    pending.run(argValue)
    onOpenChange(false)
  }

  const onListKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setIndex((i) => (matches.length ? (i + 1) % matches.length : 0))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setIndex((i) => (matches.length ? (i - 1 + matches.length) % matches.length : 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const cmd = matches[index]
      if (cmd) choose(cmd)
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="palette"
          aria-label="Command palette"
          // Escape out of the argument step goes back to the list, not out of
          // the palette -- picking the wrong command should cost one keystroke.
          // It has to be handled here rather than on the input: Radix listens
          // for Escape on the document, so stopping React's synthetic event
          // never reaches it and the dialog closed anyway.
          onEscapeKeyDown={(e) => {
            if (pending) {
              e.preventDefault()
              setPending(null)
            }
          }}
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          {pending ? (
            <div className="palette-arg">
              <label className="field-label" htmlFor="palette-arg">
                {pending.arg?.label}
              </label>
              <input
                id="palette-arg"
                autoFocus
                className="palette-input"
                value={argValue}
                placeholder={pending.arg?.placeholder}
                onChange={(e) => setArgValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    submitArg()
                  }
                  // Escape is handled by the content's onEscapeKeyDown above.
                }}
              />
            </div>
          ) : (
            <>
              <input
                autoFocus
                className="palette-input"
                value={query}
                placeholder="Type a command"
                aria-label="Command"
                role="combobox"
                aria-expanded
                aria-controls="palette-list"
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onListKey}
              />
              <ul className="palette-list" id="palette-list" role="listbox" ref={listEl}>
                {matches.map((cmd, i) => (
                  <li
                    key={cmd.id}
                    role="option"
                    aria-selected={i === index}
                    className={'palette-item' + (i === index ? ' is-active' : '')}
                    onMouseEnter={() => setIndex(i)}
                    onClick={() => choose(cmd)}
                  >
                    <span className="palette-group">{cmd.group}</span>
                    <span className="palette-title">{cmd.title}</span>
                    {cmd.hint && <span className="palette-hint">{cmd.hint}</span>}
                  </li>
                ))}
                {!matches.length && <li className="palette-empty">No matching command</li>}
              </ul>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
