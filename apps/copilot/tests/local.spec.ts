/** Actual configured Ollama + embeddings + CrossEncoder + API + Next browser smoke.
 * Run only with PAIS_E2E_PROFILE=local; no fixture model or synthetic stream responses.
 */
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../../..");
const artifacts = path.join(root, "artifacts/ui/local");

test("actual local inference reaches the browser with a working page citation", async ({
  page,
}, testInfo) => {
  fs.mkdirSync(artifacts, { recursive: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Open local test workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Evidence, before action." }),
  ).toBeVisible();
  await expect(page.locator(".profile-badge")).toContainText(
    "local environment",
  );
  await page.getByRole("button", { name: "New conversation" }).click();
  await page
    .getByLabel("Upload PDF", { exact: true })
    .setInputFiles(path.join(artifacts, "operations-manual.pdf"));
  await expect(
    page.getByRole("status").filter({ hasText: "is ready to ask about" }),
  ).toBeVisible();
  const requestStarted = Date.now();
  const responsePromise = page.waitForResponse((response) =>
    response.url().endsWith("/api/chat/stream"),
  );
  await page
    .getByLabel("Ask your workspace", { exact: true })
    .fill("What is the maximum safe operating pressure?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.locator(".message.assistant .message-text")).toContainText(
    "8 bar",
  );
  await expect(page.getByRole("button", { name: "Stop response" })).toHaveCount(
    0,
  );
  await expect(page.locator(".message-footer")).toContainText("local output");
  const response = await responsePromise;
  const events = (await response.text())
    .split("\n")
    .filter((line) => line.startsWith("data: ") && line !== "data: [DONE]")
    .map((line) => JSON.parse(line.slice(6)));
  const metadata = events.find(
    (event) => event.type === "finish",
  ).messageMetadata;
  expect(metadata.profile).toBe("local");
  expect(metadata.model).not.toContain("fixture");
  expect(metadata.providerTTFTMs).toBeNull();
  expect(metadata.buffered).toBe(true);
  const elapsedMs = Date.now() - requestStarted;
  await page.screenshot({
    path: path.join(artifacts, "desktop-local-conversation.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: /Open source 1, page 2/ }).click();
  await expect(page.getByTestId("source-page")).toContainText("8 bar");
  await expect(
    page.getByRole("link", { name: "Open original PDF" }),
  ).toHaveAttribute("href", /^blob:.*#page=2$/);
  await page.screenshot({
    path: path.join(artifacts, "desktop-local-source.png"),
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  const evidence = {
    profile: "local",
    model: metadata.model,
    metadata,
    elapsedMs,
    browserFirstDisplay: await page.getByTestId("first-display").innerText(),
    mockedResponses: false,
    externalDelivery: false,
    boundary:
      "Actual local inference, protected buffered output, Next proxy, AI SDK browser, original PDF page",
  };
  fs.writeFileSync(
    path.join(artifacts, "local-smoke-measurements.json"),
    JSON.stringify(evidence, null, 2) + "\n",
  );
  await testInfo.attach("local-smoke-measurements", {
    body: JSON.stringify(evidence),
    contentType: "application/json",
  });
});
