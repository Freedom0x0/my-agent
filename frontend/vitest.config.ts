import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // antd-x ships ESM with .js that imports many submodules — ensure dedup + pre-bundle.
    dedupe: ["react", "react-dom", "antd", "@ant-design/x"],
  },
  optimizeDeps: {
    include: ["@ant-design/x", "antd", "@ant-design/icons"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    server: {
      deps: {
        // Pre-bundle antd-x through Vite so its default-export-of-default dance resolves.
        inline: [/@ant-design\/x/, /^antd/],
      },
    },
  },
});