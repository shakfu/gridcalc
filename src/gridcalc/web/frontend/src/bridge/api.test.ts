import { bridge } from './api'
import { installMockBridge } from './mock'

beforeEach(() => {
  window.pywebview = undefined
  installMockBridge()
})

// Each bridge call runs on its own Python thread, so two undos sent together
// raced each other; auto-repeat on a held Ctrl+Z sends a burst of them.
test('mutating calls run one at a time, in the order they were made', async () => {
  const api = window.pywebview!.api
  let inflight = 0
  let most = 0
  const order: number[] = []
  let n = 0
  api.undo = async () => {
    const id = n++
    inflight++
    most = Math.max(most, inflight)
    await new Promise((r) => setTimeout(r, 10 - id * 3))
    order.push(id)
    inflight--
    return { ok: true, dirty: true }
  }
  await Promise.all([bridge.undo(), bridge.undo(), bridge.undo()])
  expect(most).toBe(1)
  expect(order).toEqual([0, 1, 2])
})

test('a rejected mutation does not stall the ones behind it', async () => {
  const api = window.pywebview!.api
  api.undo = () => Promise.reject(new Error('boom'))
  await expect(bridge.undo()).rejects.toThrow('boom')
  await expect(bridge.redo()).resolves.toMatchObject({ ok: true })
})
