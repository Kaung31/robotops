import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Separate code-only build. Private recordings are never Vite imports/public files.
export default defineConfig({
  publicDir: false,
  plugins: [react()],
  build: { outDir: "dist/replay", rollupOptions: { input: "replay.html" } },
});
