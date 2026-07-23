import '@testing-library/jest-dom'
import { installMockBridge } from '../src/bridge/mock'

// Radix primitives (Menubar, Select) touch a few DOM APIs jsdom does not
// implement. Stub them so the components mount and interact under vitest.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {}
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {}
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}
const g = globalThis as { ResizeObserver?: typeof ResizeObserver }
g.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver

// vitest runs in a DEV env, so this installs the same mock bridge the browser
// dev server uses -- the component tests exercise the real bridge-call paths
// against it, only the transport is faked.
installMockBridge()
