import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Destino del proxy según el modo de backend:
//   VITE_API_TARGET=https://localhost:8443  →  runhttps (HTTPS local con certificado)
//   sin variable                            →  runserver HTTP (DJANGO_DEV=1)
const apiTarget = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        // Necesario cuando el target usa un certificado autofirmado (runhttps)
        secure: !apiTarget.startsWith('https://localhost'),
      },
    },
  },
})
