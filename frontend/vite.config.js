import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  // studio/server.py 的静态路由是 /static/<file> -> studio/web/<file>。
  // 构建时把资源 URL 固定到 /static/assets/...，服务端剥掉前缀后正好命中 web/assets/...。
  // 直接用 './' 会解析成 /assets/...，后端没有这个路由。
  base: command === 'build' ? '/static/' : '/',
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
}))
