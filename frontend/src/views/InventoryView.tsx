import { useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { Product, ViewProps } from "../types";
import { Card, ErrorNote, Pager, fmtDate, money, nameOf, useAction, useAsync } from "../ui";

type Stock = { id: number; location_id: number; product_id: number; quantity: string; uom: string };
type Movement = { id: number; location_id: number; product_id: number; movement_type: string; quantity: string; uom: string; occurred_at: string; note: string | null };
type Supplier = { id: number; name: string; active: boolean };

const PAGE = 25;
type Tab = "stock" | "movements" | "receive" | "count" | "transfer" | "suppliers";

function ProductSelect({ products, value, onChange }: { products: Product[]; value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} required>
      <option value="">Product</option>
      {products.filter((p) => p.active).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.base_uom})</option>)}
    </select>
  );
}

function LocationSelect({ locations, value, onChange, label }: { locations: ViewProps["locations"]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <label>{label}
      <select value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">Select</option>
        {locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </label>
  );
}

type Line = { product_id: string; quantity: string; uom: string; extra: string };
const blankLine = (): Line => ({ product_id: "", quantity: "", uom: "", extra: "" });

function LinesEditor({ products, lines, setLines, extraLabel }: { products: Product[]; lines: Line[]; setLines: (l: Line[]) => void; extraLabel?: string }) {
  const update = (index: number, patch: Partial<Line>) => setLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  return (
    <div className="lines">
      {lines.map((line, index) => {
        const product = products.find((p) => String(p.id) === line.product_id);
        return (
          <div className="line-row" key={index}>
            <ProductSelect products={products} value={line.product_id} onChange={(v) => update(index, { product_id: v, uom: products.find((p) => String(p.id) === v)?.base_uom ?? "" })} />
            <input type="number" step="any" min="0" placeholder="Quantity" value={line.quantity} onChange={(e) => update(index, { quantity: e.target.value })} required />
            <input placeholder={product?.base_uom ?? "UOM"} value={line.uom} onChange={(e) => update(index, { uom: e.target.value.toUpperCase() })} required />
            {extraLabel && <input type="number" step="any" min="0" placeholder={extraLabel} value={line.extra} onChange={(e) => update(index, { extra: e.target.value })} required />}
            <button type="button" className="secondary" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, i) => i !== index))}>Remove</button>
          </div>
        );
      })}
      <button type="button" className="secondary" onClick={() => setLines([...lines, blankLine()])}>Add line</button>
    </div>
  );
}

export default function InventoryView(props: ViewProps) {
  const { api, role, locations, products } = props;
  const [tab, setTab] = useState<Tab>("stock");
  const manage = canManage(role);
  const tabs: [Tab, string][] = [["stock", "Stock"], ["movements", "Movements"]];
  if (manage) tabs.push(["receive", "Receive goods"], ["count", "Stock count"], ["transfer", "Transfer"], ["suppliers", "Suppliers"]);

  return (
    <>
      <nav className="subtabs">
        {tabs.map(([key, label]) => <button key={key} type="button" className={tab === key ? "active" : "secondary"} onClick={() => setTab(key)}>{label}</button>)}
      </nav>
      {tab === "stock" && <StockPanel {...props} />}
      {tab === "movements" && <MovementsPanel api={api} locations={locations} products={products} />}
      {tab === "receive" && <ReceivePanel {...props} />}
      {tab === "count" && <CountPanel {...props} />}
      {tab === "transfer" && <TransferPanel {...props} />}
      {tab === "suppliers" && <SuppliersPanel api={api} />}
    </>
  );
}

function StockPanel({ api, role, locations, products }: ViewProps) {
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
          <label>Location<select value={locationId} onChange={(e) => setLocationId(e.target.value)}><option value="">All</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        </div>
        <ErrorNote message={stock.error} />
        <div className="table-wrapper">
          <table>
            <thead><tr><th>Product</th><th>Location</th><th>Quantity</th><th>Reorder level</th></tr></thead>
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
              {stock.data?.items.length === 0 && <tr><td colSpan={4}>No stock recorded yet. Receive goods or add an adjustment.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
      {canManage(role) && (
        <Card title="Manual adjustment" subtitle="Positive adds stock, negative removes it. The unit must be the product base unit or have a defined conversion.">
          <form className="form adjust-form" onSubmit={adjust}>
            <LocationSelect locations={locations} value={adj.location_id} onChange={(v) => setAdj({ ...adj, location_id: v })} label="Location" />
            <label>Product<ProductSelect products={products} value={adj.product_id} onChange={(v) => setAdj({ ...adj, product_id: v, uom: products.find((p) => String(p.id) === v)?.base_uom ?? "" })} /></label>
            <label>Quantity<input type="number" step="any" value={adj.quantity} onChange={(e) => setAdj({ ...adj, quantity: e.target.value })} required /></label>
            <label>Unit<input value={adj.uom} onChange={(e) => setAdj({ ...adj, uom: e.target.value.toUpperCase() })} required /></label>
            <label>Note<input value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.target.value })} /></label>
            <button type="submit" disabled={action.busy}>Save adjustment</button>
          </form>
          <ErrorNote message={action.error} />
          {action.notice && <p className="notice">{action.notice}</p>}
        </Card>
      )}
    </>
  );
}

function MovementsPanel({ api, locations, products }: Pick<ViewProps, "api" | "locations" | "products">) {
  const [locationId, setLocationId] = useState("");
  const [productId, setProductId] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(0);
  const filters = { location_id: locationId, product_id: productId, movement_type: type };
  const moves = useAsync(() => api.page<Movement>("/inventory/movements", { ...filters, limit: PAGE, offset: page * PAGE }), [api, locationId, productId, type, page]);
  const action = useAction();
  const types = ["adjustment", "receipt", "recipe_consumption", "sale_reversal", "count_adjustment", "transfer_in", "transfer_out"];
  return (
    <Card
      title="Stock movements"
      subtitle="Every change to stock, newest first."
      actions={<button type="button" className="secondary" onClick={() => void action.run(() => api.download("/inventory/movements/export.csv", "stock-movements.csv", filters))}>Export CSV</button>}
    >
      <div className="filters">
        <label>Location<select value={locationId} onChange={(e) => { setLocationId(e.target.value); setPage(0); }}><option value="">All</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        <label>Product<select value={productId} onChange={(e) => { setProductId(e.target.value); setPage(0); }}><option value="">All</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Type<select value={type} onChange={(e) => { setType(e.target.value); setPage(0); }}><option value="">All</option>{types.map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
      </div>
      <ErrorNote message={moves.error || action.error} />
      <div className="table-wrapper">
        <table>
          <thead><tr><th>When</th><th>Product</th><th>Location</th><th>Type</th><th>Quantity</th><th>Note</th></tr></thead>
          <tbody>
            {(moves.data?.items ?? []).map((m) => (
              <tr key={m.id}>
                <td>{fmtDate(m.occurred_at)}</td>
                <td>{nameOf(products, m.product_id)}</td>
                <td>{nameOf(locations, m.location_id)}</td>
                <td>{m.movement_type}</td>
                <td className={Number(m.quantity) < 0 ? "negative" : ""}>{money(m.quantity, 3)} {m.uom}</td>
                <td>{m.note ?? ""}</td>
              </tr>
            ))}
            {moves.data?.items.length === 0 && <tr><td colSpan={6}>No movements match these filters.</td></tr>}
          </tbody>
        </table>
      </div>
      <Pager page={page} size={PAGE} total={moves.data?.total ?? 0} onChange={setPage} />
    </Card>
  );
}

function ReceivePanel({ api, locations, products }: ViewProps) {
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
          <label>Supplier<select value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}><option value="">None</option>{(suppliers.data ?? []).filter((s) => s.active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <label>Document number<input value={form.document_number} onChange={(e) => setForm({ ...form, document_number: e.target.value })} placeholder="NIR / invoice no." /></label>
        </div>
        <LinesEditor products={products} lines={lines} setLines={setLines} extraLabel="Unit cost" />
        <div className="actions"><button type="submit" disabled={action.busy}>Post receipt</button></div>
      </form>
      <ErrorNote message={action.error} />
      {action.notice && <p className="notice">{action.notice}</p>}
    </Card>
  );
}

function CountPanel({ api, locations, products }: ViewProps) {
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
        <div className="actions"><button type="submit" disabled={action.busy}>Post count</button></div>
      </form>
      <ErrorNote message={action.error} />
      {action.notice && <p className="notice">{action.notice}</p>}
      {result.length > 0 && (
        <div className="table-wrapper">
          <table>
            <thead><tr><th>Product</th><th>Expected</th><th>Counted</th><th>Difference</th></tr></thead>
            <tbody>{result.map((r) => <tr key={r.product_id}><td>{nameOf(products, r.product_id)}</td><td>{money(r.expected_quantity, 3)} {r.uom}</td><td>{money(r.counted_quantity, 3)}</td><td className={Number(r.difference) < 0 ? "negative" : ""}>{money(r.difference, 3)}</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function TransferPanel({ api, locations, products }: ViewProps) {
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
        <div className="actions"><button type="submit" disabled={action.busy}>Post transfer</button></div>
      </form>
      <ErrorNote message={action.error} />
      {action.notice && <p className="notice">{action.notice}</p>}
    </Card>
  );
}

function SuppliersPanel({ api }: { api: ViewProps["api"] }) {
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
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <span />
        <button type="submit" disabled={action.busy}>Add supplier</button>
      </form>
      <ErrorNote message={action.error || suppliers.error} />
      <div className="table-wrapper">
        <table>
          <thead><tr><th>Name</th><th>Status</th><th /></tr></thead>
          <tbody>
            {(suppliers.data ?? []).map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td>
                <td>{s.active ? "active" : "inactive"}</td>
                <td><button type="button" className="secondary" onClick={() => void action.run(async () => { await api.patch(`/suppliers/${s.id}`, { active: !s.active }); await suppliers.reload(); })}>{s.active ? "Deactivate" : "Activate"}</button></td>
              </tr>
            ))}
            {suppliers.data?.length === 0 && <tr><td colSpan={3}>No suppliers yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
