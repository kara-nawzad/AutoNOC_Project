import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../autonoc/web/dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          map: ["leaflet", "react-leaflet"],
          motion: ["framer-motion"],
        },
      },
    },
  },
  server: {
    host: "0.0.0.0",
    // Arena's preview domains are reverse-proxied to this server.
    allowedHosts: [".e2b.app", "localhost"],
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  preview: { host: "0.0.0.0", allowedHosts: [".e2b.app", "localhost"] },
});
