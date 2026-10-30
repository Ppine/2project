import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // 같은 Wi-Fi 의 폰에서 http://<PC IP>:5173 으로 접속
    fs: { allow: ['..'] }, // "데모 명세서로 해보기"가 ../data/demo_card_2026.csv 를 읽는다
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
