import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const artifacts = process.env.PAIS_UI_EVIDENCE_DIR
  ? path.resolve(process.env.PAIS_UI_EVIDENCE_DIR)
  : path.join(root, "artifacts/ui-runs/fixture");
const fixturePath = path.join(artifacts, "operations-manual.pdf");
const question = "What is the maximum safe operating pressure?";
const headers = { Authorization: "Bearer fixture-admin" };

async function connect(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Open fixture workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence, before action." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New conversation" }).click();
}
async function ask(page: Page) {
  await page.getByLabel("Ask your workspace", { exact: true }).fill(question);
  await page.getByRole("button", { name: "Send question" }).click();
}
async function finished(page: Page) {
  await expect(
    page.locator(".message.assistant .message-text").last(),
  ).toContainText("8 bar");
  await expect(page.getByRole("button", { name: "Stop response" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: /Open source 1, page 2/ }).last(),
  ).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  fs.mkdirSync(artifacts, { recursive: true });
  const documents = await (
    await request.get("http://127.0.0.1:8000/api/documents", { headers })
  ).json();
  if (!documents.documents.length) {
    const response = await request.post("http://127.0.0.1:8000/api/documents", {
      headers,
      multipart: {
        file: {
          name: "operations-manual.pdf",
          mimeType: "application/pdf",
          buffer: fs.readFileSync(fixturePath),
        },
      },
    });
    expect(response.status()).toBe(201);
  }
});

test("PDF upload, first display, exact source page, keyboard return, actual screenshots", async ({
  page,
}, testInfo) => {
  await connect(page);
  await page.getByRole("button", { name: "New conversation" }).focus();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Ask workspace", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: /Source library/ }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Source library", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Evidence, before action." }),
  ).toBeVisible();
  await page
    .getByLabel("Upload PDF", { exact: true })
    .setInputFiles(fixturePath);
  await expect(
    page.getByRole("status").filter({ hasText: "is ready to ask about" }),
  ).toBeVisible();
  await ask(page);
  await expect(
    page.locator(".message.assistant .message-text").last(),
  ).toContainText("8 bar");
  await expect(page.getByTestId("first-display")).toBeVisible();
  const firstDisplay = await page.getByTestId("first-display").innerText();
  await finished(page);
  await expect(page.locator(".message.user")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(artifacts, `${testInfo.project.name}-conversation.png`),
    fullPage: true,
  });
  const citation = page
    .getByRole("button", { name: /Open source 1, page 2/ })
    .last();
  await citation.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByTestId("source-page")).toContainText("8 bar");
  const original = page.getByRole("link", { name: "Open original PDF" });
  await expect(original).toHaveAttribute("href", /^blob:.*#page=2$/);
  await expect(
    page.getByRole("button", { name: "Close source inspection" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(original).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Close source inspection" }),
  ).toBeFocused();
  await page.screenshot({
    path: path.join(artifacts, `${testInfo.project.name}-source.png`),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(citation).toBeFocused();
  await page.getByRole("button", { name: /Source library/ }).click();
  await expect(
    page.getByRole("heading", { name: "Source library", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(artifacts, `${testInfo.project.name}-library.png`),
    fullPage: true,
  });
  await testInfo.attach("browser-first-display", {
    body: JSON.stringify({
      firstDisplay,
      profile: "fixture",
      providerTTFT: null,
    }),
    contentType: "application/json",
  });
});

test("cancel partial delivery and retry without duplicate messages", async ({
  page,
}) => {
  const sent: { message_id: string; conversation_id: string }[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/chat/stream")) {
      sent.push(request.postDataJSON());
    }
  });
  await connect(page);
  await ask(page);
  // Observe partial API delivery and stop in the same browser turn. Separate
  // driver round trips can outlast the fixture's 180 ms frame interval.
  const stoppedMessage = await page.waitForFunction(() => {
    const assistant = [...document.querySelectorAll(".message.assistant")].at(
      -1,
    );
    const stop = document.querySelector<HTMLButtonElement>(".stop-button");
    const id = assistant?.getAttribute("data-message-id");
    if (
      !id ||
      !assistant
        ?.querySelector(".message-text")
        ?.textContent?.includes("8 bar") ||
      assistant.querySelector(".citations") ||
      !stop ||
      stop.disabled
    )
      return null;
    const style = getComputedStyle(stop);
    const bounds = stop.getBoundingClientRect();
    if (
      style.display === "none" ||
      style.visibility !== "visible" ||
      Number(style.opacity) <= 0 ||
      bounds.width <= 0 ||
      bounds.height <= 0 ||
      bounds.right <= 0 ||
      bounds.bottom <= 0 ||
      bounds.left >= window.innerWidth ||
      bounds.top >= window.innerHeight
    )
      return null;
    stop.click();
    return id;
  });
  const assistantId = await stoppedMessage.jsonValue();
  await expect(
    page.getByRole("status").filter({ hasText: "Delivery stopped" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry message" }).click();
  await finished(page);
  expect(sent).toHaveLength(2);
  expect(sent[0].message_id).toBe(sent[1].message_id);
  expect(sent[0].conversation_id).toBe(sent[1].conversation_id);
  await expect(page.locator(".message.user")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveAttribute(
    "data-message-id",
    assistantId!,
  );
});

test("real API forced failure recovers on same idempotent message", async ({
  page,
}, testInfo) => {
  await connect(page);
  const sent: { message_id: string; conversation_id: string }[] = [];
  await page.route("**/api/chat/stream", (route) => {
    sent.push(route.request().postDataJSON());
    return route.continue({
      headers: {
        ...route.request().headers(),
        "x-pais-test-fault": "fail-once",
      },
    });
  });
  await ask(page);
  await expect(page.locator(".composer-area").getByRole("alert")).toContainText(
    "could not finish",
  );
  await page.screenshot({
    path: path.join(artifacts, `${testInfo.project.name}-recovery.png`),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Retry message" }).click();
  await finished(page);
  expect(sent).toHaveLength(2);
  expect(sent[0].message_id).toBe(sent[1].message_id);
  await expect(page.locator(".message.user")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveCount(1);
  const history = await (
    await page.request.get(
      `/api/messages?conversation_id=${encodeURIComponent(sent[0].conversation_id)}`,
      { headers },
    )
  ).json();
  expect(history.messages).toHaveLength(2);
  expect(history.pending).toHaveLength(0);
  await expect(page.locator(".message.assistant")).toHaveAttribute(
    "data-message-id",
    history.messages[1].id,
  );
});

test("malformed stream fails visibly, then recovers through actual API", async ({
  page,
}) => {
  await connect(page);
  await page.route("**/api/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "x-vercel-ai-ui-message-stream": "v1",
      },
      body: 'data: {"type":"start","messageId":"adversarial-fixture"}\n\ndata: {"type":"text-delta","id":"bad","delta":42}\n\ndata: [DONE]\n\n',
    }),
  );
  await ask(page);
  await expect(page.locator(".composer-area").getByRole("alert")).toBeVisible();
  await page.unroute("**/api/chat/stream");
  await page.getByRole("button", { name: "Retry message" }).click();
  await finished(page);
  await expect(page.locator(".message.user")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveCount(1);
});

test("disconnect before generation recovers without an optimistic duplicate", async ({
  page,
}) => {
  await connect(page);
  await page.route("**/api/chat/stream", (route) =>
    route.abort("connectionreset"),
  );
  await ask(page);
  await expect(page.locator(".composer-area").getByRole("alert")).toBeVisible();
  await page.unroute("**/api/chat/stream");
  await page.getByRole("button", { name: "Retry message" }).click();
  await finished(page);
  await expect(page.locator(".message.user")).toHaveCount(1);
  await expect(page.locator(".message.assistant")).toHaveCount(1);
});

test("approval binds exact action and persists one local execution", async ({
  page,
}, testInfo) => {
  await connect(page);
  await page.getByRole("button", { name: /Approvals/ }).click();
  const enable = page.getByRole("button", { name: "Enable local execution" });
  if (await enable.isVisible()) await enable.click();
  await expect(
    page.getByRole("button", { name: "Pause execution" }),
  ).toBeVisible();
  const note = `Review pressure valve (${testInfo.project.name}).`;
  await page.getByLabel("Note to record").fill(note);
  await page
    .getByRole("button", { name: "Request approval", exact: true })
    .click();
  const card = page.locator(".approval-card").filter({ hasText: note });
  await expect(card).toContainText("pending");
  await card.getByRole("button", { name: "Approve exact action" }).click();
  await expect(card).toContainText("executed");
  await expect(
    card.getByRole("button", { name: "Approve exact action" }),
  ).toHaveCount(0);
  await expect(card).toHaveCount(1);
  await page.screenshot({
    path: path.join(artifacts, `${testInfo.project.name}-approvals.png`),
    fullPage: true,
  });
});

test("model-like HTML is rendered as inert text", async ({ page }) => {
  await connect(page);
  const hostile = '<img src=x onerror="window.__injected=true">';
  await page.route("**/api/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "x-vercel-ai-ui-message-stream": "v1",
      },
      body:
        [
          { type: "start", messageId: "untrusted-fixture" },
          { type: "text-start", id: "text" },
          { type: "text-delta", id: "text", delta: hostile },
          { type: "text-end", id: "text" },
          { type: "finish", finishReason: "stop" },
        ]
          .map((event) => `data: ${JSON.stringify(event)}\n\n`)
          .join("") + "data: [DONE]\n\n",
    }),
  );
  await ask(page);
  await expect(page.locator(".message.assistant .message-text")).toHaveText(
    hostile,
  );
  await expect(page.locator(".message.assistant img")).toHaveCount(0);
  expect(await page.evaluate(() => "__injected" in window)).toBe(false);
});
