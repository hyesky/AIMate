import { defineConfig } from 'vite';
import { resolve } from 'node:path';

export default defineConfig({
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5199,
    proxy: {
      // 开发时 API 转发到 AIMate console
      '/api': 'http://127.0.0.1:8905',
    },
  },
});
