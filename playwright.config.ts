import { defineConfig } from "@playwright/test";
export default defineConfig({
  outputDir: "test-results/local",
  testDir: "./frontend/tests",
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1440, height: 1000 },
  },
  webServer: [
    {
      command: "npm run dev -- --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      env: {
        VITE_TEST_CATALOG: "generic",
        VITE_DATA_SOURCE: "mock",
        VITE_RUN_MODE: "mock",
        VITE_API_BASE_URL: "",
      },
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 4174 --strictPort",
      url: "http://127.0.0.1:4174",
      env: {
        VITE_TEST_CATALOG: "generic",
        VITE_DATA_SOURCE: "api",
        VITE_RUN_MODE: "mock",
      },
      reuseExistingServer: false,
    },
  ],
});
