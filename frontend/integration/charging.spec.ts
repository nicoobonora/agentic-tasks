import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";
for (const task of ["expansion", "maintenance"]) {
  test(`actual HTTP/SSE: ${task}`, async ({ page, request }) => {
    const payloads: any[] = [];
    let runId = "";
    page.on("response", async (r) => {
      if (
        r.request().method() === "POST" &&
        new URL(r.url()).pathname === "/api/v2/runs" &&
        r.status() === 202
      )
        runId = (await r.json()).id;
    });
    page.on("request", (r) => {
      if (r.method() === "POST" && new URL(r.url()).pathname === "/api/v2/runs")
        payloads.push(r.postDataJSON());
    });
    if (task === "expansion")
      await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.locator(`[data-start="${task}"]`).focus();
    await page.keyboard.press("Enter");
    // The critic escalates after the full first round (all four roles).
    await expect(page.locator(".question")).toBeVisible({ timeout: 30000 });
    expect(payloads).toHaveLength(1);
    expect(payloads[0].capability_profile).toBe("charging");
    expect(payloads[0].task.attachments).toBeUndefined();
    await page.getByLabel("Choice").selectOption("points");
    await page.getByRole("button", { name: "Send answer and resume" }).click();
    await page.locator(".agent-panel [data-evidence]").first().click();
    await expect(page.locator(".investigation")).toContainText(
      "charging.discover_sites",
    );
    if (task === "maintenance") {
      await expect(page.locator(".investigation")).toContainText(
        "charging.request_forecast",
      );
      process.kill(
        Number(readFileSync("test-results/e2e-supervisor.pid", "utf8")),
        "SIGUSR1",
      );
      await expect
        .poll(async () => {
          try {
            return (
              await request.get("http://127.0.0.1:8015/api/v2/health")
            ).status();
          } catch {
            return 0;
          }
        })
        .toBe(200);
    }
    // No reload: the page keeps no run registry, it reconnects via SSE/polling.
    await page.getByRole("button", { name: "Close details" }).click();
    // With one round per cycle the critic's revision request goes to the operator.
    await expect(page.locator(".question")).toContainText("Round limit", {
      timeout: 45000,
    });
    await page.getByLabel("Choice").selectOption("retain_uncertainty");
    await page.getByRole("button", { name: "Send answer and resume" }).click();
    await expect(
      page.getByRole("button", { name: "Review and approve" }),
    ).toBeVisible({ timeout: 45000 });
    expect(payloads).toHaveLength(1);
    await page.locator(".agent-panel [data-evidence]").first().click();
    await page.locator(".investigation details summary").first().click();
    const evidence = page.locator(".investigation [data-evidence]").first();
    await evidence.click();
    await expect(page.locator('[data-disclosure^="artifact-"]')).toBeVisible();
    await expect(page.locator(".investigation")).toContainText(
      task === "maintenance"
        ? "charging.request_forecast"
        : "charging.assess_expansion",
    );
    const current = await (
      await request.get(`http://127.0.0.1:8015/api/v2/runs/${runId}`)
    ).json();
    const stale = await request.post(
      `http://127.0.0.1:8015/api/v2/runs/${runId}/approve`,
      {
        data: {
          proposal_version: current.proposal_version - 1,
          actor: "test",
          idempotency_key: "stale",
        },
      },
    );
    expect(stale.status()).toBe(409);
    if (task === "maintenance") {
      const call = current.tool_activity.find(
        (c: any) => c.request.name === "charging.request_forecast",
      );
      const result = await (
        await request.get(
          `http://127.0.0.1:8015/api/v2/runs/${runId}/artifacts/${call.artifact_id}`,
        )
      ).json();
      expect(result.outcome.status).toBe("available");
      expect(
        result.outcome.data.parameters.model_inference_calls,
      ).toBeGreaterThan(0);
      expect(result.outcome.data.sites[0].selected_method).toBe(
        "seasonal_naive",
      );
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/charging-${task}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Close details" }).click();
    await page.getByRole("button", { name: "Review and approve" }).click();
    await page.getByRole("button", { name: "Approve proposal" }).click();
    await expect(page.locator(".approved-note")).toContainText(
      "no action executed",
    );
  });
}
