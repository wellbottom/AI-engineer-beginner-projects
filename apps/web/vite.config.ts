/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    // Vite only exposes import.meta.env variables matching this prefix. The six
    // backend base URLs MUST therefore be VITE_*-prefixed (Requirement 2.9 / the
    // design's "Vite envPrefix correctness note"). Non-VITE_-prefixed names
    // (e.g. NEXT_PUBLIC_*) are intentionally NOT exposed and resolve to empty.
    envPrefix: 'VITE_',
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      hmr: process.env.DISABLE_HMR !== 'true',
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
    test: {
      // Frontend tests run under Vitest + React Testing Library (jsdom).
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./vitest.setup.ts'],
      css: false,
      include: ['src/**/*.{test,spec}.{ts,tsx}'],
    },
  };
});
