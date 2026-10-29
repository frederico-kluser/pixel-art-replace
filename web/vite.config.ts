import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      // o backend Python do studio (python -m par studio) serve a API
      '/api': 'http://127.0.0.1:8770',
      '/sprite': 'http://127.0.0.1:8770',
      '/ficheiros': 'http://127.0.0.1:8770',
    },
  },
})
