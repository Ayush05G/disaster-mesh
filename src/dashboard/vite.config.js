import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // The ledger service is same-machine only (D2/D3). Proxying /api lets
    // the dashboard use relative URLs, so the built app carries no absolute
    // http:// origin inside its bundle for the offline audit to trip on.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8700",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8700",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    // Keep sourcemaps out of dist so the offline audit only scans shipped bytes.
    sourcemap: false,
  },
});
