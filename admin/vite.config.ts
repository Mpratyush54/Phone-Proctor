import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../server/public", emptyOutDir: true },
  // Proxy target must match the TS api port. 8090 while the legacy relay
  // occupies 8080; use 8080 (API_PORT) when the api runs on its default port.
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8090", "/health": "http://127.0.0.1:8090" } },
});
