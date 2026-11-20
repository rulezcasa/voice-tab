import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // reachable from your phone on the same network
    allowedHosts: ['.ngrok-free.app', '.ngrok.app', '.ngrok.io'], // HTTPS tunnel for the mic on phones
    proxy: { '/api': 'http://localhost:8000' }, // FastAPI backend, once the UI is wired to it
  },
})
