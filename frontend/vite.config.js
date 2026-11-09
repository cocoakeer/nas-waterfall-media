import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  // outDir / emptyOutDir 属于 build 段；写在顶层会被静默忽略（这里取值
  // 恰好与默认值一致，所以一直「看起来能用」），改错时会踩空
  build: {
    outDir: 'dist',
    emptyOutDir: true
  },
  base: './',
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})
