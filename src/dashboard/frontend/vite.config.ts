import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("react-dom") || id.includes("/react/")) return "react-vendor";
          if (id.includes("@radix-ui")) return "radix-vendor";
          if (id.includes("framer-motion")) return "motion-vendor";
          if (id.includes("react-markdown") || id.includes("remark-gfm")) return "markdown-vendor";
          if (id.includes("sonner")) return "toast-vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    allowedHosts: ["host.docker.internal", "localhost", "127.0.0.1"],
  },
});
