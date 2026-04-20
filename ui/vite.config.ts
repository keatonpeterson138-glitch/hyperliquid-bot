import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri recommends a fixed port for HMR so the Rust shell can connect reliably.
const TAURI_DEV_PORT = 5177;

export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: TAURI_DEV_PORT,
    strictPort: true,
    host: "127.0.0.1",
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  build: {
    target: "esnext",
    minify: "esbuild",
    sourcemap: true,
  },
});
