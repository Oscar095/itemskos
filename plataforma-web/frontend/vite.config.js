import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// El backend (FastAPI) corre en :8000. Este proxy evita CORS en desarrollo:
// el frontend llama /api/* como si fuera same-origin, Vite lo reenvia al
// backend quitando el prefijo /api (backend expone /health, no /api/health).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
