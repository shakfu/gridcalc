import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { installMockBridge } from './bridge/mock'
import { App } from './App'
import './styles.css'

// No-op in the real pywebview window (the bridge is injected there); installs a
// mock only for `npm run dev` / tests. See installMockBridge.
installMockBridge()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
