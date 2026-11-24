import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataItemsDialog } from './DataItemsDialog'
import { bridge } from '../bridge/api'
import { installMockBridge } from '../bridge/mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

afterEach(() => {
  vi.restoreAllMocks()
})

const SEL = { r0: 8, c0: 2, r1: 9, c1: 6, ref: 'C9:G10', active: 'C9' }

function renderDialog(over: Partial<Parameters<typeof DataItemsDialog>[0]> = {}) {
  const props = {
    open: true,
    onOpenChange: vi.fn(),
    selection: SEL,
    runCommand: vi.fn(async (name: string, args: string[]) => {
      await bridge.run_command(name, args, SEL)
    }),
    onGoto: vi.fn(),
    revision: '0',
    ...over,
  }
  render(<DataItemsDialog {...props} />)
  return props
}

test('lists items with their range and indexes', async () => {
  renderDialog()
  const table = await screen.findByRole('table', { name: 'Data items' })
  const costs = within(table).getByText('costs').closest('tr') as HTMLElement
  expect(costs).toHaveTextContent('Data!C4:G5')
  expect(costs).toHaveTextContent('Warehouses, Bars')
  expect(costs).toHaveTextContent('error') // missing key policy
})

test('adds the selection as an indexed item', async () => {
  const props = renderDialog()
  const user = userEvent.setup()
  await screen.findByRole('table', { name: 'Data items' })
  await user.type(screen.getByLabelText('Item name'), 'flow')
  await user.selectOptions(screen.getByLabelText('Row index'), 'Bars')
  await user.type(screen.getByLabelText('Missing value'), '0')
  await user.click(screen.getByRole('button', { name: 'Add from selection' }))
  expect(props.runCommand).toHaveBeenCalledWith('item', ['flow', 'Bars', 'missing=0'])
  const row = (await screen.findByText('flow')).closest('tr') as HTMLElement
  expect(row).toHaveTextContent('Sheet1!C9:G10')
})

test('only sets are offered as indexes', async () => {
  renderDialog()
  await screen.findByRole('table', { name: 'Data items' })
  const options = within(screen.getByLabelText('Row index')).getAllByRole('option')
  expect(options.map((o) => o.textContent)).toEqual(['(none)', 'Bars'])
})

test('a name is required', async () => {
  const props = renderDialog()
  await userEvent.setup().click(screen.getByRole('button', { name: 'Add from selection' }))
  expect(screen.getByText('give the item a name')).toBeInTheDocument()
  expect(props.runCommand).not.toHaveBeenCalled()
})

test('delete removes an item', async () => {
  const props = renderDialog()
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Delete costs' }))
  expect(props.runCommand).toHaveBeenCalledWith('unitem', ['costs'])
  await waitFor(() => expect(screen.queryByText('costs')).toBeNull())
})

test('clicking a range goes to it and closes', async () => {
  const props = renderDialog()
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Data!C4:G5' }))
  expect(props.onGoto).toHaveBeenCalledWith('Data', 'C4:G5')
  expect(props.onOpenChange).toHaveBeenCalledWith(false)
})


test('an item can be made an output', async () => {
  const props = renderDialog()
  const user = userEvent.setup()
  await screen.findByRole('table', { name: 'Data items' })
  await user.type(screen.getByLabelText('Item name'), 'flow')
  await user.selectOptions(screen.getByLabelText('Row index'), 'Bars')
  await user.click(screen.getByLabelText('Output item'))
  await user.click(screen.getByRole('button', { name: 'Add from selection' }))
  expect(props.runCommand).toHaveBeenCalledWith('item', ['flow', 'Bars', 'output'])
  const row = (await screen.findByText('flow')).closest('tr') as HTMLElement
  expect(within(row).getByText('yes')).toBeInTheDocument()
  expect(screen.getByLabelText('Output item')).not.toBeChecked()
})

test('a table item gets its table, keys and value column', async () => {
  const props = renderDialog()
  const user = userEvent.setup()
  await screen.findByRole('table', { name: 'Data items' })
  await user.selectOptions(screen.getByLabelText('Source'), 'table')
  await user.selectOptions(screen.getByLabelText('Table'), 'Routes')
  expect(screen.getByLabelText('Value column')).toHaveValue('cost') // the last column
  await user.type(screen.getByLabelText('Item name'), 'cost')
  await user.click(screen.getByRole('button', { name: 'Add from selection' }))
  expect(props.runCommand).toHaveBeenCalledWith('item', [
    'cost',
    'table=Routes',
    'keys=Warehouse,Bar',
    'value=cost',
  ])
  const row = (await screen.findAllByText('cost'))[0].closest('tr') as HTMLElement
  expect(row).toHaveTextContent('table Routes')
})

test('a set from a table column', async () => {
  const props = renderDialog()
  const user = userEvent.setup()
  await screen.findByRole('table', { name: 'Data items' })
  await user.selectOptions(screen.getByLabelText('Source'), 'table')
  await user.selectOptions(screen.getByLabelText('Table'), 'Routes')
  await user.selectOptions(screen.getByLabelText('Value column'), 'Warehouse')
  await user.click(screen.getByLabelText('Set of column values'))
  await user.type(screen.getByLabelText('Item name'), 'Warehouses')
  await user.click(screen.getByRole('button', { name: 'Add from selection' }))
  expect(props.runCommand).toHaveBeenCalledWith('item', ['Warehouses', 'table=Routes', 'column=Warehouse'])
})

test('names with spaces are quoted for the command', async () => {
  vi.spyOn(bridge, 'tables').mockResolvedValue({
    tables: [{ name: 'Routes', sheet: 'Sheet1', columns: ['From WH', 'To Bar', 'unit cost'] }],
  })
  const props = renderDialog()
  const user = userEvent.setup()
  await screen.findByRole('table', { name: 'Data items' })
  await user.selectOptions(screen.getByLabelText('Source'), 'table')
  await user.selectOptions(screen.getByLabelText('Table'), 'Routes')
  await user.type(screen.getByLabelText('Item name'), 'c')
  await user.click(screen.getByRole('button', { name: 'Add from selection' }))
  expect(props.runCommand).toHaveBeenCalledWith('item', [
    'c',
    'table=Routes',
    'keys="From WH,To Bar"',
    'value="unit cost"',
  ])
})
