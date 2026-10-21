import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Vite configuration for the ElderLife AI frontend.
//
// Two plugins do the real work:
//   * react      — compiles JSX and enables fast refresh during development
//   * tailwindcss — Tailwind v4 is a Vite plugin, not a PostCSS step, so there
//                   is no tailwind.config.js any more. Styling is configured
//                   in src/index.css instead.
export default defineConfig({
  plugins: [react(), tailwindcss()],

  server: {
    // The backend's CORS setting allows http://localhost:5173, which is the
    // port Vite uses by default. Keep them in sync.
    port: 5173,

    // A proxy is provided as a convenience so the app also works if you set
    // VITE_API_BASE_URL to '/api-proxy'. By default the app talks to the API
    // directly using VITE_API_BASE_URL, which is easier to reason about.
    proxy: {
      '/api-proxy': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api-proxy/, ''),
      },
    },
  },

  // Vitest shares this file. Tests run in a simulated browser (jsdom) so that
  // React components can be rendered without a real browser.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
