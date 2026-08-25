/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// The pywebview window loads a single self-contained document (no server, no
// asset requests), so the build inlines everything into one index.html and
// emits it into the Python package's `static/` dir, where `run()` reads it.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./test/setup.ts'],
  },
})
