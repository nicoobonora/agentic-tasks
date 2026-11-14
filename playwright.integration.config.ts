import { defineConfig } from "@playwright/test";
export default defineConfig({
  outputDir: "test-results/integration",
  testDir: "./frontend/integration",
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4175",
    viewport: { width: 1440, height: 1000 },
  },
  webServer: [
    {
      gracefulShutdown: { signal: "SIGTERM", timeout: 10000 },
      command: ".venv/bin/python -m tests.e2e_server",
      url: "http://127.0.0.1:8015/api/v2/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 4175 --strictPort",
      url: "http://127.0.0.1:4175",
      reuseExistingServer: false,
      env: {
        VITE_DATA_SOURCE: "api",
        VITE_RUN_MODE: "mock",
        VITE_API_BASE_URL: "http://127.0.0.1:8015",
        VITE_TEST_CATALOG: "",
      },
    },
  ],
});
