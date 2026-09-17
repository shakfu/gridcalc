import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmDialog } from './ConfirmDialog'

test('answers true on confirm and false on cancel', async () => {
  const onAnswer = vi.fn()
  const q = { title: 'Delete sheet Data?', message: 'This cannot be undone.', action: 'Delete' }
  const { rerender } = render(<ConfirmDialog request={q} onAnswer={onAnswer} />)
  const user = userEvent.setup()
  expect(screen.getByText('This cannot be undone.')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Delete' }))
  expect(onAnswer).toHaveBeenLastCalledWith(true)

  rerender(<ConfirmDialog request={{ ...q }} onAnswer={onAnswer} />)
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(onAnswer).toHaveBeenLastCalledWith(false)
})

test('renders nothing without a request', () => {
  render(<ConfirmDialog request={null} onAnswer={() => {}} />)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
