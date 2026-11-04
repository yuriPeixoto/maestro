import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the dev server proxies /api. Docker Compose sets it to the api service;
// outside Docker the API runs on the host.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000'

// The dashboard's version, compared with the API's on the About screen.
const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

export default defineConfig({
  plugins: [react()],
  define: { __APP_VERSION__: JSON.stringify(version) },
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
