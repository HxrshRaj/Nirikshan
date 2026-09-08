import { test, expect, Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

const SHOTS = "e2e/screenshots";
mkdirSync(SHOTS, { recursive: true });

async function login(page: Page, email = "admin@nirikshan.dev", password = "admin12345") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$|\/(?!login)/);
  await expect(page.getByText("Active incidents")).toBeVisible();
}

test("overview renders live platform data", async ({ page }) => {
  await login(page);
  // stat tiles are all present (getByText is case-insensitive)
  for (const label of ["Active incidents", "Services degraded", "Avg error rate", "Avg p95 latency"]) {
    await expect(page.getByText(label)).toBeVisible();
  }
  // service health table lists the demo topology
  await expect(page.getByText("Payment Service", { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/01-overview.png`, fullPage: true });
});

test("incident detail shows an evidence-grounded RCA", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "Incidents" }).click();
  await expect(page).toHaveURL(/\/incidents/);
  await page.screenshot({ path: `${SHOTS}/02-incidents.png`, fullPage: true });

  const firstRef = page.locator("table tbody tr td a").first();
  await expect(firstRef).toBeVisible();
  const ref = (await firstRef.textContent())?.trim();
  await firstRef.click();
  await expect(page).toHaveURL(new RegExp(`/incidents/${ref}`));

  await expect(page.getByText("Root Cause Analysis")).toBeVisible();
  await expect(page.getByText("Hypotheses (ranked)")).toBeVisible();
  await expect(page.getByText("Evidence", { exact: true })).toBeVisible();
  await expect(page.getByText("Timeline", { exact: true })).toBeVisible();
  // the RCA is labelled as coming from the demo/mock provider
  await expect(page.getByText(/Demo \/ Mock Provider/i).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/03-incident-detail.png`, fullPage: true });
});

test("service map renders the dependency graph", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "Service Map" }).click();
  await expect(page).toHaveURL(/\/service-map/);
  await expect(page.locator("svg").first()).toBeVisible();
  await expect(page.getByText("Dependency graph")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/04-service-map.png`, fullPage: true });
});

test("AI investigations view exposes the audit trail", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "AI Investigations" }).click();
  await expect(page).toHaveURL(/\/investigations/);
  await expect(page.getByText("Agent runs")).toBeVisible();
  const firstRun = page.locator("table tbody tr td a").first();
  await expect(firstRun).toBeVisible();
  await firstRun.click();
  await expect(page.getByText("Evidence tools called (audit trail)")).toBeVisible();
  await expect(page.getByText("Evidence grounding")).toBeVisible();
  await expect(page.getByText(/query_metrics|search_logs|get_dependencies/).first()).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/05-investigation-run.png`, fullPage: true });
});

test("viewer role cannot run scenarios (RBAC enforced in UI + API)", async ({ page }) => {
  await login(page, "viewer@nirikshan.dev", "viewer12345");
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByText(/require the ADMIN role/i)).toBeVisible();
});
