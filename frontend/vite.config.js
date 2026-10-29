import react from '@vitejs/plugin-react'
import { configDefaults, defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    // Times on screen ("retrieved 15:12") are checked in the venue's timezone on every laptop.
    env: { TZ: 'Asia/Kolkata' },
    // UI tests for components built on Friday live in *.friday.test.jsx: they fail until
    // the UI exists, so `npm test` skips them and `npm run test:friday` runs them.
    exclude: process.env.FRIDAY
      ? configDefaults.exclude
      : [...configDefaults.exclude, '**/*.friday.test.*'],
  },
})
