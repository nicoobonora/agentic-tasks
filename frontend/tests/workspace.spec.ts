import { test, expect } from "@playwright/test";
import { createMockClient } from "../mock";
import { tasks } from "../test-tasks";

test("drag, discussione, risposta umana e approvazione", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByText("Mock locale · nessuna chiamata AI"),
  ).toBeVisible();
  await page.locator('[data-task="guide"]').dragTo(page.locator("[data-drop]"));
  await expect(page.locator('.backlog [data-task="guide"]')).toHaveCount(0);
  await expect(page.locator(".question")).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".message")).toHaveCount(4);
  await page.getByRole("button", { name: "Rispondi" }).click();
  await expect(page.getByLabel("Scelta")).toBeFocused();
  await page.getByLabel("Scelta").selectOption("__custom");
  await page
    .getByLabel("Risposta libera")
    .fill("Inserire anche i contatti del coordinatore.");
  await page.getByRole("button", { name: "Invia risposta e riprendi" }).click();
  await expect(page.locator(".question")).toHaveCount(0);
  await expect(page.locator(".active-runs .proposal_ready")).toHaveCount(1, {
    timeout: 10000,
  });
  await page.getByRole("button", { name: "Cronologia", exact: true }).click();
  await expect(page.locator(".message.operator")).toContainText(
    "Inserire anche i contatti",
  );
  await page.getByRole("button", { name: "Chiudi dettagli" }).click();
  await page.getByRole("button", { name: "Rivedi e approva" }).click();
  await page.getByRole("button", { name: "Approva proposta" }).click();
  await expect(page.locator(".results .approved")).toHaveCount(1);
  await expect(page.locator(".approved-note")).toContainText(
    "nessuna azione eseguita",
  );
  expect(errors).toEqual([]);
  await page.screenshot({
    path: "test-results/workspace-approved.png",
    fullPage: true,
  });
});

test("retry esplicito dopo errore simulato e risposta libera", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('[data-task="review"]').getByRole("button").click();
  await expect(page.locator(".failure")).toContainText(
    "Errore di connessione simulato",
  );
  await page.getByRole("button", { name: "Riprova il turno" }).click();
  await expect(page.locator(".question")).toBeVisible({ timeout: 10000 });
  await page.getByRole("button", { name: "Invia risposta e riprendi" }).click();
  await expect(page.getByRole("alert")).toContainText("scegli un’opzione");
  await page.getByLabel("Scelta").selectOption("__custom");
  await page.getByLabel("Risposta libera").fill("Solo una pagina.");
  await page.getByRole("button", { name: "Invia risposta e riprendi" }).click();
  await expect(page.locator(".active-runs .proposal_ready")).toHaveCount(1, {
    timeout: 10000,
  });
});

test("run concorrenti preservano la risposta durante gli aggiornamenti", async ({
  page,
}) => {
  await page.goto("/");
  await page.locator('[data-start="guide"]').click();
  await expect(page.locator(".question")).toBeVisible({ timeout: 10000 });
  await page.locator('[data-start="meeting"]').click();
  await page
    .locator(".active-runs [data-select]")
    .filter({ hasText: "Accogliere" })
    .click();
  await page.getByLabel("Scelta").selectOption("__custom");
  await page.getByLabel("Risposta libera").fill("Testo ancora da inviare");
  await expect(page.locator(".active-runs .awaiting_input")).toHaveCount(2, {
    timeout: 10000,
  });
  await expect(page.getByLabel("Risposta libera")).toHaveValue(
    "Testo ancora da inviare",
  );
  await expect(page.locator(".active-runs .run-card")).toHaveCount(2);
});

test("simulatore: replay idempotente e versione superata", async () => {
  const api = createMockClient(5);
  const payload = {
    task: tasks[2].task,
    mode: "mock" as const,
    idempotency_key: "create-1",
  };
  const r = await api.createRun(payload);
  const replay = await api.createRun(payload);
  expect(replay.id).toBe(r.id);
  expect(r.state).toBe("failed");
  const command = {
    proposal_version: r.proposal_version!,
    idempotency_key: "retry-1",
  };
  const retried = await api.retry(r.id, command);
  expect((await api.retry(r.id, command)).proposal_version).toBe(
    retried.proposal_version,
  );
  await expect(
    api.retry(r.id, { ...command, idempotency_key: "retry-2" }),
  ).rejects.toMatchObject({ status: 409, payload: { code: "stale_version" } });
});

test("client API: retry di rete con stessa chiave e 409 senza retry automatico", async ({
  page,
}) => {
  const simulator = createMockClient();
  const run = await simulator.createRun({
    task: tasks[2].task,
    mode: "mock",
    idempotency_key: "fixture",
  });
  const createKeys: string[] = [];
  let retryCalls = 0;
  await page.route("**/api/v2/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v2/runs") {
      createKeys.push(request.postDataJSON().idempotency_key);
      expect(request.postDataJSON().mode).toBe("mock");
      if (createKeys.length === 1) {
        await route.abort("failed");
        return;
      }
      await route.fulfill({ status: 202, json: run });
      return;
    }
    if (path.endsWith("/events")) {
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: snapshot\nid: 1\ndata: ${JSON.stringify({ sequence: 1, data: run })}\n\n`,
      });
      return;
    }
    if (path.endsWith("/retry")) {
      retryCalls++;
      expect(request.postDataJSON().proposal_version).toBe(0);
      run.proposal_version = 2;
      run.updated_at = new Date(Date.now() + 1000).toISOString();
      await route.fulfill({
        status: 409,
        json: { code: "stale_version", message: "Versione superata." },
      });
      return;
    }
    await route.fulfill({ json: run });
  });
  await page.goto("http://127.0.0.1:4174");
  await page.locator('[data-start="review"]').click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.locator('[data-start="review"]').click();
  await expect(page.locator(".failure")).toBeVisible();
  expect(createKeys).toHaveLength(2);
  expect(createKeys[0]).toBe(createKeys[1]);
  await page.getByRole("button", { name: "Riprova il turno" }).click();
  await expect(page.getByRole("alert")).toContainText("Versione superata");
  await expect(page.getByRole("alert")).toContainText("controlla e conferma");
  expect(retryCalls).toBe(1);
  await page.reload();
  // A refresh starts clean: the ticket is available again and nothing is restored.
  await expect(page.locator(".failure")).toHaveCount(0);
  await expect(page.locator('[data-start="review"]')).toBeVisible();
  expect(createKeys).toHaveLength(2);
});

for (const viewport of [
  { width: 1366, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`single viewport, concurrent role panels and minimal question ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await page.locator('[data-start="guide"]').click();
    await expect(page.locator(".question")).toBeVisible({ timeout: 10000 });
    for (const role of ["critic", "analyst", "operations", "finance"]) {
      await expect(page.locator(`.agent-panel.${role}`)).toBeVisible();
      await expect(
        page.locator(`.agent-panel.${role} .public-explanation`),
      ).not.toBeEmpty();
    }
    const boxes = await page
      .locator(".model-grid .agent-panel")
      .evaluateAll((els) =>
        els.map((el) => {
          const b = el.getBoundingClientRect();
          return { x: b.x, y: b.y, bottom: b.bottom };
        }),
      );
    expect(boxes[0].y).toBe(boxes[1].y);
    expect(boxes[1].y).toBe(boxes[2].y);
    expect(boxes[0].x).toBeLessThan(boxes[1].x);
    expect(boxes[1].x).toBeLessThan(boxes[2].x);
    const critic = await page.locator(".agent-panel.critic").boundingBox();
    expect(critic!.y + critic!.height).toBeLessThanOrEqual(boxes[0].y);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollHeight <= innerHeight &&
          document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const question = await page.locator(".question").boundingBox();
    expect(question!.y + question!.height).toBeLessThan(viewport.height);
    await expect(page.locator(".question textarea")).toHaveCount(0);
    await page.screenshot({
      path: `test-results/viewport-${viewport.width}.png`,
    });
    await page.getByRole("button", { name: "Cronologia", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
}
