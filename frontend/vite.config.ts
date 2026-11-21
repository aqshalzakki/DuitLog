import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    strictPort: true,
    proxy: { '/api': process.env.DUIT_DEV_API ?? 'http://127.0.0.1:3000' },
  },
})
