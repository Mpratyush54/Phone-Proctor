import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Must match the TS api port (see server/.env API_PORT; 8090 while the legacy relay holds 8080).
  server: { port: 5174, proxy: { "/api": "http://127.0.0.1:8090" } },
});
