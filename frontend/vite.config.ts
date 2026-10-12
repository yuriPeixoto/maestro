import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Where the dev server proxies /api. Docker Compose sets it to the api service;
// outside Docker the API runs on the host.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
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
