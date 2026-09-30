import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the build works when loaded from disk by pywebview.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 1500,
  },
});
