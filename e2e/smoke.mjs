import { chromium } from "playwright-core";
import fs from "fs";

const BASE = process.env.BASE_URL ?? "http://localhost:4173";
const API = process.env.API_URL ?? "http://localhost:8000/api";
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const problems = [];
page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
page.on("dialog", (d) => d.accept("test reason"));

const step = async (name, fn) => { try { await fn(); console.log("OK  ", name); } catch (e) { console.log("FAIL", name, "-", e.message.split("\n")[0]); problems.push(name); await page.screenshot({ path: `fail-${name.replace(/\W+/g, "_")}.png`, fullPage: true }); } };
const tab = (label) => page.getByRole("button", { name: label, exact: true }).first().click();
const api = (path, method = "GET", body) => page.evaluate(async ([API, path, method, body]) => {
  const token = localStorage.getItem("horeca_access_token");
  const r = await fetch(API + path, { method, headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: body ? JSON.stringify(body) : undefined });
  return r.json();
}, [API, path, method, body]);

await page.goto(BASE);
await step("bootstrap", async () => {
  await page.getByRole("button", { name: /First user/ }).click();
  const labels = { "Company name": "E2E Bistro", "First name": "Ana", "Last name": "Pop", Email: `ana${Date.now()}@e2e.dev`, Password: "password123" };
  for (const [l, v] of Object.entries(labels)) await page.getByLabel(l).fill(v);
  await page.getByRole("button", { name: "Create owner account" }).click();
  await page.getByText("Signed in as Ana Pop").waitFor();
});

let location, beef, burger;
await step("seed via api", async () => {
  const me = await api("/auth/me");
  location = await api("/locations", "POST", { company_id: me.company_id, name: "Main" });
  beef = await api("/products", "POST", { name: "Beef", base_uom: "KG", sku: "BEEF", reorder_level: "5" });
  burger = await api("/products", "POST", { name: "Burger", sku: "BURGER" });
  await api("/recipes", "POST", { product_id: burger.id, name: "Burger", lines: [{ ingredient_product_id: beef.id, quantity: "0.2", uom: "KG", waste_factor: "0.1" }] });
  await page.reload();
  await page.getByText("Signed in as Ana Pop").waitFor();
});

await step("receive goods", async () => {
  await tab("Inventory");
  await tab("Receive goods");
  await page.getByLabel("Location").selectOption({ label: "Main" });
  await page.locator(".line-row select").selectOption({ label: "Beef (KG)" });
  await page.getByPlaceholder("Quantity").fill("3");
  await page.getByPlaceholder("Unit cost").fill("50");
  await page.getByRole("button", { name: "Post receipt" }).click();
  await page.getByText("Goods received").waitFor();
});

await step("stock shows quantity and low-stock highlight", async () => {
  await tab("Stock");
  await page.getByRole("cell", { name: /3\.000 KG/ }).waitFor();
  const cls = await page.getByRole("cell", { name: /3\.000 KG/ }).getAttribute("class");
  if (!cls?.includes("warn")) throw new Error("expected warn class, got " + cls);
});

await step("manual adjustment rejects foreign unit", async () => {
  await page.getByLabel("Location").last().selectOption({ label: "Main" });
  await page.locator(".adjust-form select").nth(1).selectOption({ label: "Beef (KG)" });
  await page.locator(".adjust-form input").nth(0).fill("500");
  await page.locator(".adjust-form input").nth(1).fill("G");
  await page.getByRole("button", { name: "Save adjustment" }).click();
  await page.getByText(/No UOM conversion/).waitFor();
});

await step("create csv integration", async () => {
  await tab("Integrations");
  await page.locator(".integration-form select").nth(0).selectOption({ label: "Main" });
  await page.locator(".integration-form select").nth(1).selectOption({ label: "CSV file import" });
  await page.locator(".integration-form input").first().fill("Export import");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page.getByText("Integration created.").waitFor();
});

await step("import csv and see sale", async () => {
  await tab("Sales");
  const csv = "sale_id,occurred_at,external_product_id,product_name,quantity,unit_price,tax_value\nT1,2026-10-01T10:00:00Z,BURGER,Burger,10,10,1.9\nT2,2026-10-01T11:00:00Z,XYZ,Mystery,1,5,0\n";
  fs.writeFileSync("sales.csv", csv);
  await page.locator(".csv-form select").selectOption({ label: "Export import" });
  await page.locator('input[type=file]').setInputFiles("sales.csv");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByRole("cell", { name: "T1", exact: true }).waitFor();
});

await step("stock consumed by recipe", async () => {
  const stock = await api("/inventory/stock");
  const q = Number(stock.find((s) => s.product_id === beef.id).quantity);
  if (Math.abs(q - 0.8) > 1e-6) throw new Error("expected 0.8 got " + q);
});

await step("cancel sale restores stock", async () => {
  await page.getByRole("row", { name: /T1/ }).getByRole("button", { name: "Cancel" }).click();
  await page.getByText(/marked cancelled/).waitFor();
  const stock = await api("/inventory/stock");
  const q = Number(stock.find((s) => s.product_id === beef.id).quantity);
  if (Math.abs(q - 3) > 1e-6) throw new Error("expected 3 got " + q);
});

await step("filter sales by status", async () => {
  await page.locator(".filters select").nth(1).selectOption("cancelled");
  await page.getByRole("cell", { name: "T2", exact: true }).waitFor({ state: "detached" });
  await page.getByRole("cell", { name: "T1", exact: true }).waitFor();
  if (await page.getByRole("cell", { name: "T2", exact: true }).count()) throw new Error("T2 should be filtered out");
});

await step("alerts tab", async () => {
  await tab("Alerts");
  await page.getByText(/not mapped to a product/).waitFor();
  await page.getByText(/reorder level/).waitFor();
});

await step("recipes: cost calculation", async () => {
  await tab("Recipes & costs");
  await page.getByRole("button", { name: "Calculate" }).click();
  await page.getByText(/11\.00 RON/).waitFor();
});

await step("reports", async () => {
  await page.evaluate(async ([API]) => {
    const token = localStorage.getItem("horeca_access_token");
    const h = { "Content-Type": "application/json", Authorization: "Bearer " + token };
    const ints = await (await fetch(API + "/integrations/pos", { headers: h })).json();
    await fetch(API + "/sales/import-csv?integration_id=" + ints[0].id, { method: "POST", headers: { ...h, "Content-Type": "text/csv" },
      body: "sale_id,occurred_at,external_product_id,product_name,quantity,unit_price\nT3,2026-10-02T10:00:00Z,BURGER,Burger,10,10\n" });
  }, [API]);
  await tab("Reports");
  await page.getByRole("cell", { name: "Burger" }).waitFor();
});

await step("settings: subscription + audit + password", async () => {
  await tab("Settings");
  await page.getByText("Current plan: business").waitFor();
  await page.getByRole("cell", { name: /product #/ }).first().waitFor();
  await page.getByLabel("Current password").fill("password123");
  await page.getByLabel(/New password/).fill("password456");
  await page.getByRole("button", { name: "Change password" }).click();
  await page.getByText(/Password changed/).waitFor();
});

await step("sign out everywhere", async () => {
  await page.getByRole("button", { name: "Sign out on all devices" }).click();
  await page.getByRole("heading", { name: "Sign in" }).waitFor();
});

await page.screenshot({ path: "final.png" });
await browser.close();
console.log(problems.length ? "PROBLEMS:\n" + problems.join("\n") : "ALL GOOD");
