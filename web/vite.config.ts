import { createHtmlPlugin } from 'vite-plugin-html'
import viteCompression from 'vite-plugin-compression'
import { visualizer } from 'rollup-plugin-visualizer'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig, loadEnv, type UserConfig } from 'vite'

export default defineConfig(({ mode }): UserConfig => {
  const isProd = mode === 'production'
  const analyze = process.env.ANALYZE === 'true'
  const env = loadEnv(mode, process.cwd(), '')

  const xqtraderTarget = env.VITE_XQTRADER_PROXY_TARGET || 'http://localhost:8096'
  const aiGatewayTarget = env.VITE_AI_GATEWAY_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [
      react(),
      createHtmlPlugin({
        minify: isProd,
        inject: {
          data: {
            title: 'XQTrader',
          },
        },
      }),
      isProd &&
        viteCompression({
          algorithm: 'gzip',
          ext: '.gz',
          threshold: 1024,
        }),
      isProd &&
        viteCompression({
          algorithm: 'brotliCompress',
          ext: '.br',
          threshold: 1024,
        }),
      analyze &&
        visualizer({
          open: false,
          filename: 'dist/stats.html',
          gzipSize: true,
          brotliSize: true,
        }),
    ].filter(Boolean),
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      host: true,
      proxy: {
        '/ws': {
          target: xqtraderTarget,
          changeOrigin: true,
          ws: true,
        },
        // AI 代理网关：模型管理 / OpenAI 兼容接口（优先匹配）
        '/api/v1/ai': {
          target: aiGatewayTarget,
          changeOrigin: true,
        },
        '/v1': {
          target: aiGatewayTarget,
          changeOrigin: true,
        },
        // XQTrader 平台 API
        '/api': {
          target: xqtraderTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      target: 'es2022',
      sourcemap: false,
      cssCodeSplit: true,
      chunkSizeWarningLimit: 800,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return
            if (/react-router|react-dom|\/react\//.test(id)) return 'vendor-react'
            if (id.includes('antd')) return 'vendor-antd'
            if (id.includes('i18next')) return 'vendor-i18n'
            if (id.includes('zustand')) return 'vendor-state'
          },
          chunkFileNames: 'assets/[name]-[hash].js',
          entryFileNames: 'assets/[name]-[hash].js',
          assetFileNames: 'assets/[name]-[hash][extname]',
        },
      },
    },
  }
})
