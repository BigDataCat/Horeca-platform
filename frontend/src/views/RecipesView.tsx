import { useT } from "../i18n";
import { useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { ViewProps } from "../types";
import { Card, ErrorNote, fmtDate, money, nameOf, useAction, useAsync } from "../ui";

type RecipeLine = { id: number; ingredient_product_id: number; quantity: string; uom: string; waste_factor: string };
type Recipe = { id: number; product_id: number; location_id: number | null; name: string; active: boolean; lines: RecipeLine[] };
type RecipeCost = { total_cost: string | null; currency: string; lines: { ingredient_product_id: number; unit_cost: string | null; line_cost: string | null }[] };
type Cost = { id: number; product_id: number; location_id: number | null; unit_cost: string; currency: string; effective_from: string };

type NewLine = { ingredient: string; quantity: string; uom: string; waste: string };
const blank = (): NewLine => ({ ingredient: "", quantity: "", uom: "", waste: "0" });

export default function RecipesView({ api, role, locations, products, refreshProducts }: ViewProps) {
  const t = useT();
  const manage = canManage(role);
  const recipes = useAsync(() => api.get<Recipe[]>("/recipes"), [api]);
  const costs = useAsync(() => api.get<Cost[]>("/costs/products"), [api]);
  const [costView, setCostView] = useState<Record<number, RecipeCost>>({});
  const action = useAction();

  const [form, setForm] = useState({ product_id: "", location_id: "", name: "" });
  const [lines, setLines] = useState<NewLine[]>([blank()]);
  const [cost, setCost] = useState({ product_id: "", location_id: "", unit_cost: "", effective_from: new Date().toISOString().slice(0, 10) });
  const [level, setLevel] = useState({ product_id: "", reorder_level: "" });

  const update = (index: number, patch: Partial<NewLine>) => setLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  async function createRecipe(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/recipes", {
        product_id: Number(form.product_id),
        location_id: form.location_id ? Number(form.location_id) : null,
        name: form.name,
        lines: lines.map((l) => ({ ingredient_product_id: Number(l.ingredient), quantity: l.quantity, uom: l.uom, waste_factor: String(Number(l.waste) / 100) })),
      });
      await recipes.reload();
    }, "Recipe created.");
    if (ok) {
      setForm({ product_id: "", location_id: "", name: "" });
      setLines([blank()]);
    }
  }

  async function showCost(recipe: Recipe) {
    await action.run(async () => {
      const result = await api.get<RecipeCost>(`/costs/recipes/${recipe.id}`, { location_id: recipe.location_id ?? "" });
      setCostView((previous) => ({ ...previous, [recipe.id]: result }));
    });
  }

  async function addCost(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/costs/products", {
        product_id: Number(cost.product_id),
        location_id: cost.location_id ? Number(cost.location_id) : null,
        unit_cost: cost.unit_cost,
        effective_from: new Date(cost.effective_from).toISOString(),
      });
      await costs.reload();
    }, "Cost saved.");
    if (ok) setCost({ ...cost, unit_cost: "" });
  }

  async function saveLevel(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      await api.patch(`/products/${level.product_id}`, { reorder_level: level.reorder_level === "" ? null : level.reorder_level });
      await refreshProducts();
    }, "Reorder level saved.");
  }

  return (
    <>
      <Card title="Recipes" subtitle="Selling a mapped product consumes its ingredients (including waste). A location recipe overrides the company-wide one.">
        <ErrorNote message={action.error || recipes.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("Recipe")}</th><th>{t("Product")}</th><th>{t("Scope")}</th><th>{t("Ingredients")}</th><th>{t("Cost")}</th><th /></tr></thead>
            <tbody>
              {(recipes.data ?? []).filter((r) => r.active).map((recipe) => {
                const view = costView[recipe.id];
                return (
                  <tr key={recipe.id}>
                    <td>{recipe.name}</td>
                    <td>{nameOf(products, recipe.product_id)}</td>
                    <td>{recipe.location_id ? nameOf(locations, recipe.location_id) : "All locations"}</td>
                    <td>{recipe.lines.map((l) => `${nameOf(products, l.ingredient_product_id)} ${Number(l.quantity)} ${l.uom}${Number(l.waste_factor) ? ` (+${Math.round(Number(l.waste_factor) * 10000) / 100}% waste)` : ""}`).join(", ")}</td>
                    <td>{view ? (view.total_cost === null ? <span className="warn">{t("Missing ingredient cost")}</span> : `${money(view.total_cost)} ${view.currency}`) : <button type="button" className="secondary" onClick={() => void showCost(recipe)}>{t("Calculate")}</button>}</td>
                    <td>{manage && <button type="button" className="secondary" onClick={() => void action.run(async () => { await api.del(`/recipes/${recipe.id}`); await recipes.reload(); })}>{t("Deactivate")}</button>}</td>
                  </tr>
                );
              })}
              {recipes.data?.filter((r) => r.active).length === 0 && <tr><td colSpan={6}>{t("No recipes yet.")}</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      {manage && (
        <Card title="New recipe">
          <form onSubmit={createRecipe}>
            <div className="filters">
              <label>{t("Finished product")}<select value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })} required><option value="">{t("Select")}</option>{products.filter((p) => p.active).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
              <label>{t("Location (optional)")}<select value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })}><option value="">{t("All locations")}</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
              <label>{t("Name")}<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
            </div>
            <div className="lines">
              {lines.map((line, index) => (
                <div className="line-row" key={index}>
                  <select value={line.ingredient} onChange={(e) => update(index, { ingredient: e.target.value, uom: products.find((p) => String(p.id) === e.target.value)?.base_uom ?? "" })} required>
                    <option value="">{t("Ingredient")}</option>{products.filter((p) => p.active).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.base_uom})</option>)}
                  </select>
                  <input type="number" step="any" min="0" placeholder={t("Quantity")} value={line.quantity} onChange={(e) => update(index, { quantity: e.target.value })} required />
                  <input placeholder={t("UOM")} value={line.uom} onChange={(e) => update(index, { uom: e.target.value.toUpperCase() })} required />
                  <input type="number" step="any" min="0" max="100" placeholder={t("Waste %")} value={line.waste} onChange={(e) => update(index, { waste: e.target.value })} />
                  <button type="button" className="secondary" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, i) => i !== index))}>{t("Remove")}</button>
                </div>
              ))}
              <button type="button" className="secondary" onClick={() => setLines([...lines, blank()])}>{t("Add ingredient")}</button>
            </div>
            <div className="actions"><button type="submit" disabled={action.busy}>{t("Create recipe")}</button></div>
          </form>
        </Card>
      )}

      <Card title="Ingredient costs" subtitle="The latest cost effective today is used (a location cost overrides the company-wide one). Receiving goods adds costs automatically.">
        {manage && (
          <form className="form cost-form" onSubmit={addCost}>
            <label>{t("Product")}<select value={cost.product_id} onChange={(e) => setCost({ ...cost, product_id: e.target.value })} required><option value="">{t("Select")}</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.base_uom})</option>)}</select></label>
            <label>{t("Location")}<select value={cost.location_id} onChange={(e) => setCost({ ...cost, location_id: e.target.value })}><option value="">{t("All")}</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
            <label>{t("Cost per base unit")}<input type="number" step="any" min="0" value={cost.unit_cost} onChange={(e) => setCost({ ...cost, unit_cost: e.target.value })} required /></label>
            <label>{t("Effective from")}<input type="date" value={cost.effective_from} onChange={(e) => setCost({ ...cost, effective_from: e.target.value })} required /></label>
            <button type="submit" disabled={action.busy}>{t("Add cost")}</button>
          </form>
        )}
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("Product")}</th><th>{t("Location")}</th><th>{t("Unit cost")}</th><th>{t("Effective from")}</th></tr></thead>
            <tbody>
              {(costs.data ?? []).slice().sort((a, b) => b.effective_from.localeCompare(a.effective_from)).slice(0, 50).map((c) => (
                <tr key={c.id}><td>{nameOf(products, c.product_id)}</td><td>{c.location_id ? nameOf(locations, c.location_id) : "All"}</td><td>{money(c.unit_cost, 4)} {c.currency}</td><td>{fmtDate(c.effective_from)}</td></tr>
              ))}
              {costs.data?.length === 0 && <tr><td colSpan={4}>{t("No costs yet.")}</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      {manage && (
        <Card title="Reorder levels" subtitle="Raise a low-stock alert when stock falls to this quantity (in the base unit).">
          <form className="form csv-form" onSubmit={saveLevel}>
            <label>{t("Product")}<select value={level.product_id} onChange={(e) => setLevel({ product_id: e.target.value, reorder_level: products.find((p) => String(p.id) === e.target.value)?.reorder_level ?? "" })} required><option value="">{t("Select")}</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.base_uom})</option>)}</select></label>
            <label>{t("Reorder level")}<input type="number" step="any" min="0" value={level.reorder_level} onChange={(e) => setLevel({ ...level, reorder_level: e.target.value })} placeholder={t("none")} /></label>
            <button type="submit" disabled={action.busy}>{t("Save")}</button>
          </form>
        </Card>
      )}
    </>
  );
}
