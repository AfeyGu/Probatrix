import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 构建产物直接落到包内 src/calcbook/web，使 pip 安装的 wheel 自带界面
// （同事使用无需 Node；界面改动后需 npm run build 再提交）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8317' },
  },
  build: {
    outDir: '../src/calcbook/web',
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
  },
})
