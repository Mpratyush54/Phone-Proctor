import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../server/public", emptyOutDir: true },
  // Proxy target must match the API port (see server/.env API_PORT).
  // host:true listens on IPv4+IPv6 so both localhost and 127.0.0.1 work.
  server: { port: 5173, host: true, proxy: { "/api": "http://127.0.0.1:8090", "/health": "http://127.0.0.1:8090" } },
});
