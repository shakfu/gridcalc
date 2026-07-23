import * as Dialog from '@radix-ui/react-dialog'

// Introduces the Radix Dialog primitive (used by the feature dialogs in later
// phases) and verifies modal focus/escape behaviour in the real WebView early.
export function AboutDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title className="dialog-title">gridcalc</Dialog.Title>
          <Dialog.Description className="dialog-desc">
            A terminal-first spreadsheet with an Excel-compatible formula language and
            optimization built in. This is the experimental desktop web frontend.
          </Dialog.Description>
          <div className="dialog-actions">
            <Dialog.Close className="btn-primary">Close</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
