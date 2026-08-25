import '@testing-library/jest-dom'
import { installMockBridge } from '../src/bridge/mock'

// happy-dom implements the pointer-capture, scrollIntoView and ResizeObserver
// APIs the Radix primitives (Menubar, Select) reach for, so the stubs jsdom
// needed here are gone. It still does no layout -- every rect measures 0 --
// which is why the Playwright suite exists alongside this one.

// vitest runs in a DEV env, so this installs the same mock bridge the browser
// dev server uses -- the component tests exercise the real bridge-call paths
// against it, only the transport is faked.
installMockBridge()
