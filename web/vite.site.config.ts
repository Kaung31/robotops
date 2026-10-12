import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// No operational entry, proxy, public directory or recording import.
export default defineConfig({
  publicDir: false,
  plugins: [react()],
  define: { __ROBOTOPS_SITE__: "true" },
  build: { outDir: "dist/site", rollupOptions: { input: ["portfolio.html", "replay.html"] } },
});
