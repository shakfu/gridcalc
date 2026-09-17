import * as Dialog from '@radix-ui/react-dialog'

export interface ConfirmRequest {
  title: string
  message: string
  // Label of the button that goes ahead, naming what it does ("Delete").
  action: string
}

// A yes/no question before an action that loses work. Dismissing it any way
// other than the action button answers no.
export function ConfirmDialog({
  request,
  onAnswer,
}: {
  request: ConfirmRequest | null
  onAnswer: (yes: boolean) => void
}) {
  if (!request) return null
  return (
    <Dialog.Root open onOpenChange={(open) => !open && onAnswer(false)}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content">
          <Dialog.Title className="dialog-title">{request.title}</Dialog.Title>
          <Dialog.Description>{request.message}</Dialog.Description>
          <div className="dialog-actions">
            <button className="btn" onClick={() => onAnswer(false)}>
              Cancel
            </button>
            <button className="btn-primary" onClick={() => onAnswer(true)}>
              {request.action}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
