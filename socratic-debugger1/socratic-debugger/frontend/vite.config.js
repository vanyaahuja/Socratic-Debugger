import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Cloud IDEs (Codespaces, Gitpod) proxy the dev server from outside the
    // container -- bind to all interfaces, not just 127.0.0.1, or the
    // forwarded URL will fail to connect. Harmless for local dev too.
    host: true,
  },
})
