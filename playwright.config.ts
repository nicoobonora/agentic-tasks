import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./frontend/tests",
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1440, height: 1000 },
  },
  webServer: [
    {
      command: "npm run dev -- --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run dev -- --port 4174 --strictPort",
      url: "http://127.0.0.1:4174",
      env: { VITE_DATA_SOURCE: "api", VITE_RUN_MODE: "mock" },
      reuseExistingServer: !process.env.CI,
    },
  ],
});
