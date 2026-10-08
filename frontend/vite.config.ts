/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  return {
    plugins: [react()],
    define: {
      // Release reported with browser errors, so they can be matched to a deploy.
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(env.VITE_APP_VERSION || env.npm_package_version || 'dev'),
    },
    // Production bundles carry no console output or debugger statements.
    esbuild: mode === 'production' ? { drop: ['console', 'debugger'], legalComments: 'none' } : undefined,
    build: {
      // Source maps are not published: stack traces reported by browsers are minified (see docs).
      sourcemap: false,
      // Modern evergreen browsers (Chrome/Edge/Firefox/Safari from the last ~3 years).
      target: ['es2022', 'chrome111', 'edge111', 'firefox111', 'safari16'],
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            mui: ['@mui/material', '@emotion/react', '@emotion/styled'],
            charts: ['recharts'],
            data: ['@tanstack/react-query', 'axios', 'react-hook-form', 'zod', '@hookform/resolvers'],
          },
        },
      },
    },
    server: {
      port: 5173,
      // In development the browser calls /api/... on the Vite server, which forwards to FastAPI
      // (uvicorn listens on 127.0.0.1 by default). `npm run preview` uses the same proxy.
      proxy: {
        '/api': { target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      coverage: {
        provider: 'v8',
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/main.tsx', 'src/**/*.test.{ts,tsx}', 'src/test/**', 'src/vite-env.d.ts'],
        reporter: ['text-summary', 'text'],
      },
    },
  };
});
