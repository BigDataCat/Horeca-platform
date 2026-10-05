import { useT } from "../i18n";
import { useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { Product, ViewProps } from "../types";
import { Card, ErrorNote, Pager, fmtDate, money, nameOf, useAction, useAsync } from "../ui";

type Stock = { id: number; location_id: number; product_id: number; quantity: string; uom: string };
type Movement = { id: number; location_id: number; product_id: number; movement_type: string; quantity: string; uom: string; occurred_at: string; note: string | null };
type Supplier = { id: number; name: string; active: boolean };

const PAGE = 25;
type Tab = "stock" | "movements" | "receive" | "count" | "transfer" | "production" | "suppliers";

function ProductSelect({ products, value, onChange }: { products: Product[]; value: string; onChange: (v: string) => void }) {
  const t = useT();
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} required>
      <option value="">{t("Product")}</option>
      {products.filter((p) => p.active).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.base_uom})</option>)}
    </select>
  );
}

function LocationSelect({ locations, value, onChange, label }: { locations: ViewProps["locations"]; value: string; onChange: (v: string) => void; label: string }) {
  const t = useT();
  return (
    <label>{label}
      <select value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">{t("Select")}</option>
        {locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </label>
  );
}

type Line = { product_id: string; quantity: string; uom: string; extra: string };
const blankLine = (): Line => ({ product_id: "", quantity: "", uom: "", extra: "" });

function LinesEditor({ products, lines, setLines, extraLabel }: { products: Product[]; lines: Line[]; setLines: (l: Line[]) => void; extraLabel?: string }) {
  const t = useT();
  const update = (index: number, patch: Partial<Line>) => setLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  return (
    <div className="lines">
      {lines.map((line, index) => {
        const product = products.find((p) => String(p.id) === line.product_id);
        return (
          <div className="line-row" key={index}>
            <ProductSelect products={products} value={line.product_id} onChange={(v) => update(index, { product_id: v, uom: products.find((p) => String(p.id) === v)?.base_uom ?? "" })} />
            <input type="number" step="any" min="0" placeholder={t("Quantity")} value={line.quantity} onChange={(e) => update(index, { quantity: e.target.value })} required />
            <input placeholder={product?.base_uom ?? "UOM"} value={line.uom} onChange={(e) => update(index, { uom: e.target.value.toUpperCase() })} required />
            {extraLabel && <input type="number" step="any" min="0" placeholder={extraLabel} value={line.extra} onChange={(e) => update(index, { extra: e.target.value })} required />}
            <button type="button" className="secondary" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, i) => i !== index))}>{t("Remove")}</button>
          </div>
        );
      })}
      <button type="button" className="secondary" onClick={() => setLines([...lines, blankLine()])}>{t("Add line")}</button>
    </div>
  );
}

export default function InventoryView(props: ViewProps) {
  const t = useT();
  const { api, role, locations, products } = props;
  const [tab, setTab] = useState<Tab>("stock");
  const manage = canManage(role);
  const tabs: [Tab, string][] = [["stock", "Stock"], ["movements", "Movements"]];
  if (manage) tabs.push(["receive", "Receive goods"], ["count", "Stock count"], ["transfer", "Transfer"], ["production", "Production"], ["suppliers", "Suppliers"]);

  return (
    <>
      <nav className="subtabs">
        {tabs.map(([key, label]) => <button key={key} type="button" className={tab === key ? "active" : "secondary"} onClick={() => setTab(key)}>{t(label)}</button>)}
      </nav>
      {tab === "stock" && <StockPanel {...props} />}
      {tab === "movements" && <MovementsPanel api={api} locations={locations} products={products} />}
      {tab === "receive" && <ReceivePanel {...props} />}
      {tab === "count" && <CountPanel {...props} />}
      {tab === "transfer" && <TransferPanel {...props} />}
      {tab === "production" && <ProductionPanel {...props} />}
      {tab === "suppliers" && <SuppliersPanel api={api} />}
    </>
  );
}

function StockPanel({ api, role, locations, products }: ViewProps) {
  const t = useT();
  const [locationId, setLocationId] = useState("");
  const stock = useAsync(() => api.page<Stock>("/inventory/stock", { location_id: locationId, limit: 1000 }), [api, locationId]);
  const action = useAction();
  const [adj, setAdj] = useState({ location_id: "", product_id: "", quantity: "", uom: "", note: "" });

  async function adjust(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/inventory/adjustments", {
        location_id: Number(adj.location_id),
        product_id: Number(adj.product_id),
        quantity: adj.quantity,
        uom: adj.uom,
        note: adj.note || null,
      });
      await stock.reload();
    }, "Adjustment saved.");
    if (ok) setAdj({ ...adj, quantity: "", note: "" });
  }

  return (
    <>
      <Card title="Current stock" subtitle="Quantities are kept in each product's base unit.">
        <div className="filters">
          <label>{t("Location")}<select value={locationId} onChange={(e) => setLocationId(e.target.value)}><option value="">{t("All")}</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        </div>
        <ErrorNote message={stock.error} />
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("Product")}</th><th>{t("Location")}</th><th>{t("Quantity")}</th><th>{t("Reorder level")}</th></tr></thead>
            <tbody>
              {(stock.data?.items ?? []).map((row) => {
                const product = products.find((p) => p.id === row.product_id);
                const low = product?.reorder_level != null && Number(row.quantity) <= Number(product.reorder_level);
                return (
                  <tr key={row.id}>
                    <td>{product?.name ?? row.product_id}</td>
                    <td>{nameOf(locations, row.location_id)}</td>
                    <td className={Number(row.quantity) < 0 ? "negative" : low ? "warn" : ""}>{money(row.quantity, 3)} {row.uom}</td>
                    <td>{product?.reorder_level != null ? money(product.reorder_level, 3) : "—"}</td>
                  </tr>
                );
              })}
              {stock.data?.items.length === 0 && <tr><td colSpan={4}>{t("No stock recorded yet. Receive goods or add an adjustment.")}</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
      {canManage(role) && (
        <Card title="Manual adjustment" subtitle="Positive adds stock, negative removes it. The unit must be the product base unit or have a defined conversion.">
          <form className="form adjust-form" onSubmit={adjust}>
            <LocationSelect locations={locations} value={adj.location_id} onChange={(v) => setAdj({ ...adj, location_id: v })} label="Location" />
            <label>{t("Product")}<ProductSelect products={products} value={adj.product_id} onChange={(v) => setAdj({ ...adj, product_id: v, uom: products.find((p) => String(p.id) === v)?.base_uom ?? "" })} /></label>
            <label>{t("Quantity")}<input type="number" step="any" value={adj.quantity} onChange={(e) => setAdj({ ...adj, quantity: e.target.value })} required /></label>
            <label>{t("Unit")}<input value={adj.uom} onChange={(e) => setAdj({ ...adj, uom: e.target.value.toUpperCase() })} required /></label>
            <label>{t("Note")}<input value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.target.value })} /></label>
            <button type="submit" disabled={action.busy}>{t("Save adjustment")}</button>
          </form>
          <ErrorNote message={action.error} />
          {action.notice && <p className="notice">{action.notice}</p>}
        </Card>
      )}
    </>
  );
}

function MovementsPanel({ api, locations, products }: Pick<ViewProps, "api" | "locations" | "products">) {
  const t = useT();
  const [locationId, setLocationId] = useState("");
  const [productId, setProductId] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(0);
  const filters = { location_id: locationId, product_id: productId, movement_type: type };
  const moves = useAsync(() => api.page<Movement>("/inventory/movements", { ...filters, limit: PAGE, offset: page * PAGE }), [api, locationId, productId, type, page]);
  const action = useAction();
  const types = ["adjustment", "receipt", "recipe_consumption", "sale_reversal", "count_adjustment", "transfer_in", "transfer_out", "production_consume", "production_output"];
  return (
    <Card
      title="Stock movements"
      subtitle="Every change to stock, newest first."
      actions={<button type="button" className="secondary" onClick={() => void action.run(() => api.download("/inventory/movements/export.csv", "stock-movements.csv", filters))}>{t("Export CSV")}</button>}
    >
      <div className="filters">
        <label>{t("Location")}<select value={locationId} onChange={(e) => { setLocationId(e.target.value); setPage(0); }}><option value="">{t("All")}</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        <label>{t("Product")}<select value={productId} onChange={(e) => { setProductId(e.target.value); setPage(0); }}><option value="">{t("All")}</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>{t("Type")}<select value={type} onChange={(e) => { setType(e.target.value); setPage(0); }}><option value="">{t("All")}</option>{types.map((type_) => <option key={type_} value={type_}>{t(type_)}</option>)}</select></label>
      </div>
      <ErrorNote message={moves.error || action.error} />
      <div className="table-wrapper">
        <table>
          <thead><tr><th>{t("When")}</th><th>{t("Product")}</th><th>{t("Location")}</th><th>{t("Type")}</th><th>{t("Quantity")}</th><th>{t("Note")}</th></tr></thead>
          <tbody>
            {(moves.data?.items ?? []).map((m) => (
              <tr key={m.id}>
                <td>{fmtDate(m.occurred_at)}</td>
                <td>{nameOf(products, m.product_id)}</td>
                <td>{nameOf(locations, m.location_id)}</td>
                <td>{t(m.movement_type)}</td>
                <td className={Number(m.quantity) < 0 ? "negative" : ""}>{money(m.quantity, 3)} {m.uom}</td>
                <td>{m.note ?? ""}</td>
              </tr>
            ))}
            {moves.data?.items.length === 0 && <tr><td colSpan={6}>{t("No movements match these filters.")}</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager page={page} size={PAGE} total={moves.data?.total ?? 0} onChange={setPage} />
    </Card>
  );
}

function ReceivePanel({ api, locations, products }: ViewProps) {
  const t = useT();
  const suppliers = useAsync(() => api.get<Supplier[]>("/suppliers"), [api]);
  const [form, setForm] = useState({ location_id: "", supplier_id: "", document_number: "" });
  const [lines, setLines] = useState<Line[]>([blankLine()]);
  const action = useAction();
  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(
      () =>
        api.post("/inventory/receipts", {
          location_id: Number(form.location_id),
          supplier_id: form.supplier_id ? Number(form.supplier_id) : null,
          document_number: form.document_number || null,
          lines: lines.map((l) => ({ product_id: Number(l.product_id), quantity: l.quantity, uom: l.uom, unit_cost: l.extra })),
        }),
      "Goods received. Stock and product costs were updated.",
    );
    if (ok) setLines([blankLine()]);
  }
  return (
    <Card title="Receive goods" subtitle="Posts stock and records the purchase price as the latest cost for the receiving location (cost per unit entered).">
      <form onSubmit={submit}>
        <div className="filters">
          <LocationSelect locations={locations} value={form.location_id} onChange={(v) => setForm({ ...form, location_id: v })} label="Location" />
          <label>{t("Supplier")}<select value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}><option value="">{t("None")}</option>{(suppliers.data ?? []).filter((s) => s.active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <label>{t("Document number")}<input value={form.document_number} onChange={(e) => setForm({ ...form, document_number: e.target.value })} placeholder={t("NIR / invoice no.")} /></label>
        </div>
        <LinesEditor products={products} lines={lines} setLines={setLines} extraLabel="Unit cost" />
        <div className="actions"><button type="submit" disabled={action.busy}>{t("Post receipt")}</button></div>
      </form>
      <ErrorNote message={action.error} />
      {action.notice && <p className="notice">{action.notice}</p>}
    </Card>
  );
}

function CountPanel({ api, locations, products }: ViewProps) {
  const t = useT();
  const [locationId, setLocationId] = useState("");
  const [lines, setLines] = useState<Line[]>([blankLine()]);
  const [result, setResult] = useState<{ product_id: number; expected_quantity: string; counted_quantity: string; difference: string; uom: string }[]>([]);
  const action = useAction();
  async function submit(event: FormEvent) {
    event.preventDefault();
    await action.run(async () => {
      const count = await api.post<{ lines: typeof result }>("/inventory/counts", {
        location_id: Number(locationId),
        lines: lines.map((l) => ({ product_id: Number(l.product_id), counted_quantity: l.quantity, uom: l.uom })),
      });
      setResult(count.lines);
    }, "Count posted. Book stock now equals the counted quantities.");
  }
  return (
    <Card title="Physical stock count" subtitle="Enter what you counted. Differences against the book quantity are recorded as adjustments.">
      <form onSubmit={submit}>
        <div className="filters"><LocationSelect locations={locations} value={locationId} onChange={setLocationId} label="Location" /></div>
        <LinesEditor products={products} lines={lines} setLines={setLines} />
        <div className="actions"><button type="submit" disabled={action.busy}>{t("Post count")}</button></div>
      </form>
      <ErrorNote message={action.error} />
      {action.notice && <p className="notice">{action.notice}</p>}
      {result.length > 0 && (
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("Product")}</th><th>{t("Expected")}</th><th>{t("Counted")}</th><th>{t("Difference")}</th></tr></thead>
            <tbody>{result.map((r) => <tr key={r.product_id}><td>{nameOf(products, r.product_id)}</td><td>{money(r.expected_quantity, 3)} {r.uom}</td><td>{money(r.counted_quantity, 3)}</td><td className={Number(r.difference) < 0 ? "negative" : ""}>{money(r.difference, 3)}</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function TransferPanel({ api, locations, products }: ViewProps) {
  const t = useT();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [lines, setLines] = useState<Line[]>([blankLine()]);
  const action = useAction();
  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(
      () =>
        api.post("/inventory/transfers", {
          from_location_id: Number(from),
          to_location_id: Number(to),
          lines: lines.map((l) => ({ product_id: Number(l.product_id), quantity: l.quantity, uom: l.uom })),
        }),
      "Transfer posted.",
    );
    if (ok) setLines([blankLine()]);
  }
  return (
    <Card title="Transfer between locations" subtitle="The source location must hold enough stock.">
      <form onSubmit={submit}>
        <div className="filters">
          <LocationSelect locations={locations} value={from} onChange={setFrom} label="From" />
          <LocationSelect locations={locations} value={to} onChange={setTo} label="To" />
        </div>
        <LinesEditor products={products} lines={lines} setLines={setLines} />
        <div className="actions"><button type="submit" disabled={action.busy}>{t("Post transfer")}</button></div>
      </form>
      <ErrorNote message={action.error} />
      {action.notice && <p className="notice">{action.notice}</p>}
    </Card>
  );
}

function SuppliersPanel({ api }: { api: ViewProps["api"] }) {
  const t = useT();
  const suppliers = useAsync(() => api.get<Supplier[]>("/suppliers"), [api]);
  const [name, setName] = useState("");
  const action = useAction();
  async function create(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/suppliers", { name });
      await suppliers.reload();
    });
    if (ok) setName("");
  }
  return (
    <Card title="Suppliers">
      <form className="form csv-form" onSubmit={create}>
        <label>{t("Name")}<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <span />
        <button type="submit" disabled={action.busy}>{t("Add supplier")}</button>
      </form>
      <ErrorNote message={action.error || suppliers.error} />
      <div className="table-wrapper">
        <table>
          <thead><tr><th>{t("Name")}</th><th>{t("Status")}</th><th /></tr></thead>
          <tbody>
            {(suppliers.data ?? []).map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td>
                <td>{s.active ? "active" : "inactive"}</td>
                <td><button type="button" className="secondary" onClick={() => void action.run(async () => { await api.patch(`/suppliers/${s.id}`, { active: !s.active }); await suppliers.reload(); })}>{s.active ? "Deactivate" : "Activate"}</button></td>
              </tr>
            ))}
            {suppliers.data?.length === 0 && <tr><td colSpan={3}>{t("No suppliers yet.")}</td></tr>}
          </tbody>
        </table>
      </div>
    </Card>
  );
}


type Batch = { id: number; product_id: number; location_id: number; quantity: string; uom: string; unit_cost: string | null; produced_at: string };

function ProductionPanel({ api, locations, products }: ViewProps) {
  const t = useT();
  const batches = useAsync(() => api.get<Batch[]>("/inventory/production"), [api]);
  const [form, setForm] = useState({ location_id: "", product_id: "", quantity: "", uom: "" });
  const action = useAction();
  async function submit(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      await api.post("/inventory/production", { location_id: Number(form.location_id), product_id: Number(form.product_id), quantity: form.quantity, uom: form.uom });
      await batches.reload();
    }, "Batch produced. Ingredients were consumed and the product added to stock.");
    if (ok) setForm({ ...form, quantity: "" });
  }
  return (
    <>
      <Card title="Produce a semi-finished product" subtitle="Uses the product's recipe (quantities are per one unit of the product). Needs enough ingredient stock; if all ingredient costs are known, the batch cost becomes the product's cost.">
        <form className="form adjust-form" onSubmit={submit}>
          <LocationSelect locations={locations} value={form.location_id} onChange={(v) => setForm({ ...form, location_id: v })} label="Location" />
          <label>{t("Product")}<ProductSelect products={products} value={form.product_id} onChange={(v) => setForm({ ...form, product_id: v, uom: products.find((p) => String(p.id) === v)?.base_uom ?? "" })} /></label>
          <label>{t("Quantity")}<input type="number" step="any" min="0" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} required /></label>
          <label>{t("Unit")}<input value={form.uom} onChange={(e) => setForm({ ...form, uom: e.target.value.toUpperCase() })} required /></label>
          <span />
          <button type="submit" disabled={action.busy}>{t("Produce")}</button>
        </form>
        <ErrorNote message={action.error || batches.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
      </Card>
      <Card title="Production history">
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("When")}</th><th>{t("Product")}</th><th>{t("Location")}</th><th>{t("Quantity")}</th><th>{t("Unit cost")}</th></tr></thead>
            <tbody>
              {(batches.data ?? []).map((b) => (
                <tr key={b.id}><td>{fmtDate(b.produced_at)}</td><td>{nameOf(products, b.product_id)}</td><td>{nameOf(locations, b.location_id)}</td><td>{money(b.quantity, 3)} {b.uom}</td><td>{b.unit_cost ? money(b.unit_cost, 4) : "unknown"}</td></tr>
              ))}
              {batches.data?.length === 0 && <tr><td colSpan={5}>{t("No batches yet.")}</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
