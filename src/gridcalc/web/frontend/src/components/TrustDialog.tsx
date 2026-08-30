import { useEffect, useState } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import type { TrustInfo, TrustPolicy } from '../bridge/types'

// The web frontend's answer to the curses trust prompt: a workbook's code block
// does not run until someone says so. The file is already parsed -- never
// executed -- to fill this in, and until a decision arrives the workbook is
// loaded formulas-only, so dismissing the dialog is the safe outcome rather
// than an unanswered question.
//
// Two answers, not one, where modules are unclassified: approving the file
// vouches for what the lists know about, and `allow_unknown` is a separate
// statement about modules no list has reviewed. That is the `[a]` / `[u]` split
// the curses prompt makes, for the same reason -- "not blocked" was never the
// same claim as "safe".
export function TrustDialog({
  info,
  onDecide,
}: {
  // Null when there is nothing to decide; the dialog is open exactly when a
  // file is waiting on an answer.
  info: TrustInfo | null
  // `null` cancels: nothing is loaded, and a workbook already open stays as it
  // is -- formulas only.
  onDecide: (policy: TrustPolicy | null) => void
}) {
  const [allowUnknown, setAllowUnknown] = useState(false)

  // Each file gets its own answer. Carrying the checkbox across would approve
  // one file's unclassified modules on the strength of a decision made about
  // another's.
  useEffect(() => {
    setAllowUnknown(false)
  }, [info?.path])

  if (!info) return null

  const known = info.requires.filter(
    (m) => !info.blocked.includes(m) && !info.side_effect.includes(m) && !info.unknown.includes(m),
  )

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onDecide(null)}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content wide" aria-label="Trust this workbook">
          <Dialog.Title className="dialog-title">Run code from {info.name}?</Dialog.Title>
          <p className="trust-lede">
            This workbook carries Python that runs in this application&rsquo;s process. Until you
            approve it the sheet loads formulas only, and cells that call into the code report an
            error.
          </p>

          <div className="trust-facts">
            <div className="trust-row">
              <span className="trust-key">Cells</span>
              <span>
                {info.cells} ({info.formulas} formulas)
              </span>
            </div>
            {info.has_code && (
              <div className="trust-row">
                <span className="trust-key">Code</span>
                <span>{info.code_lines} lines</span>
              </div>
            )}
            {known.length > 0 && (
              <div className="trust-row">
                <span className="trust-key">Imports</span>
                <span>{known.join(', ')}</span>
              </div>
            )}
            {info.side_effect.length > 0 && (
              <div className="trust-row">
                <span className="trust-key">I/O</span>
                <span className="trust-warn">{info.side_effect.join(', ')}</span>
              </div>
            )}
            {info.unknown.length > 0 && (
              <div className="trust-row">
                <span className="trust-key">Unknown</span>
                <span className="trust-warn">{info.unknown.join(', ')}</span>
              </div>
            )}
            {info.blocked.length > 0 && (
              <div className="trust-row">
                <span className="trust-key">Blocked</span>
                <span className="trust-danger">{info.blocked.join(', ')} &mdash; never imported</span>
              </div>
            )}
          </div>

          {info.has_code && (
            <pre className="trust-code" aria-label="Code block">
              {info.code}
            </pre>
          )}

          {info.unknown.length > 0 && (
            <label className="trust-check">
              <input
                type="checkbox"
                checked={allowUnknown}
                onChange={(e) => setAllowUnknown(e.target.checked)}
              />
              Also import {info.unknown.join(', ')} &mdash; on no list, so unreviewed
            </label>
          )}

          <div className="dialog-actions">
            <button className="btn" onClick={() => onDecide(null)}>
              Cancel
            </button>
            <button className="btn" onClick={() => onDecide({ load_code: false })}>
              Formulas only
            </button>
            <button
              className="btn-primary"
              onClick={() => onDecide({ load_code: true, allow_unknown: allowUnknown })}
            >
              Run code
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
