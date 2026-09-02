import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Port 5173 is allow-listed (with credentials) in every backend's CORS
// configuration — keep it pinned and fail loudly if it is taken.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  preview: {
    port: 5173,
    strictPort: true,
  },
});
