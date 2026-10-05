import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useT } from "../i18n";
import { canManage } from "../types";
import type { Product, ViewProps } from "../types";
import { Card, ErrorNote, Pager, fmtDate, money, nameOf, useAction, useAsync } from "../ui";

type Line = {
  description: string;
  product_code: string | null;
  quantity: string;
  unit: string | null;
  unit_price: string | null;
  line_net: string | null;
  product_id: number | null;
  match: string | null;
  skip: boolean;
};
type Invoice = {
  id: number;
  location_id: number | null;
  supplier_id: number | null;
  source: string;
  source_type: string;
  filename: string | null;
  status: string;
  extracted: { header: Record<string, string | null>; lines: Line[] } | null;
  warnings: string[] | null;
  error: string | null;
  receipt_id: number | null;
  created_at: string;
  blocking: string[];
};
type Inbox = { address: string | null; configured: boolean; auto_post: boolean; default_location_id: number | null; note: string };

const PAGE = 15;

export default function InvoicesView({ api, role, locations, products }: ViewProps) {
  const t = useT();
  const manage = canManage(role);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [openId, setOpenId] = useState<number | null>(null);
  const list = useAsync(() => api.page<Invoice>("/invoices", { status, limit: PAGE, offset: page * PAGE }), [api, status, page]);
  const inbox = useAsync(() => api.get<Inbox>("/invoices/inbox"), [api]);
  const action = useAction();
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploadLocation, setUploadLocation] = useState("");

  async function upload(event: FormEvent) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    await action.run(async () => {
      const invoice = await api.uploadBinary<Invoice>(`/invoices/upload${api.query({ filename: file.name, location_id: uploadLocation })}`, file);
      await list.reload();
      setOpenId(invoice.id);
      if (fileInput.current) fileInput.current.value = "";
    }, "Invoice read. Review it below, then post the receipt.");
  }

  const reading = list.data?.items.some((i) => i.status === "reading") ?? false;
  useEffect(() => {
    if (!reading) return;
    const timer = window.setInterval(() => void list.reload(), 5000);
    return () => window.clearInterval(timer);
  }, [reading, list]);

  const open = list.data?.items.find((i) => i.id === openId) ?? null;

  return (
    <>
      <Card title="Invoices and NIR" subtitle="Upload a supplier invoice (e-Factura XML/ZIP, PDF or a photo) or let suppliers e-mail it. Posting creates the goods receipt: stock and purchase costs update automatically.">
        <ErrorNote message={action.error || list.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
        {manage && (
          <form className="form csv-form" onSubmit={upload}>
            <label>{t("Invoice file")}<input ref={fileInput} type="file" accept=".xml,.zip,.pdf,.png,.jpg,.jpeg,.webp,application/xml,text/xml,application/zip,application/pdf,image/*" required /></label>
            <label>{t("Receiving location")}
              <select value={uploadLocation} onChange={(e) => setUploadLocation(e.target.value)}>
                <option value="">{t("Choose later")}</option>
                {locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
            <button type="submit" disabled={action.busy}>{action.busy ? t("Reading...") : t("Upload")}</button>
          </form>
        )}
        <div className="filters">
          <label>{t("Status")}
            <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
              <option value="">{t("All")}</option>
              <option value="draft">{t("draft")}</option>
              <option value="posted">{t("posted")}</option>
              <option value="failed">{t("failed")}</option>
              <option value="rejected">{t("rejected")}</option>
            </select>
          </label>
        </div>
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("Received")}</th><th>{t("File")}</th><th>{t("Source")}</th><th>{t("Supplier")}</th><th>{t("Document")}</th><th>{t("Status")}</th><th>{t("To do")}</th></tr></thead>
            <tbody>
              {(list.data?.items ?? []).map((inv) => (
                <tr key={inv.id} className={openId === inv.id ? "selected-row" : ""} onClick={() => setOpenId(inv.id)}>
                  <td>{fmtDate(inv.created_at)}</td>
                  <td>{inv.filename ?? `#${inv.id}`}</td>
                  <td>{t(inv.source)} · {inv.source_type}</td>
                  <td>{inv.extracted?.header.supplier_name ?? "—"}</td>
                  <td>{inv.extracted?.header.document_number ?? "—"}</td>
                  <td><span className={`badge ${inv.status === "posted" ? "completed" : inv.status === "failed" ? "critical" : "warning"}`}>{t(inv.status)}</span></td>
                  <td>{inv.status === "draft" ? (inv.blocking.length ? `${inv.blocking.length} ${t("to fix")}` : t("ready")) : inv.status === "failed" ? inv.error : inv.status === "reading" ? t("being read…") : ""}</td>
                </tr>
              ))}
              {list.data?.items.length === 0 && <tr><td colSpan={7}>{t("No invoices yet.")}</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} size={PAGE} total={list.data?.total ?? 0} onChange={setPage} />
      </Card>

      {open && <InvoiceEditor key={open.id} invoice={open} api={api} manage={manage} locations={locations} products={products} onChanged={async () => { await list.reload(); }} />}

      <InboxCard inbox={inbox.data} reload={inbox.reload} api={api} role={role} locations={locations} />
    </>
  );
}

function InvoiceEditor({ invoice, api, manage, locations, products, onChanged }: { invoice: Invoice; api: ViewProps["api"]; manage: boolean; locations: ViewProps["locations"]; products: Product[]; onChanged: () => Promise<void> }) {
  const t = useT();
  const action = useAction();
  const [lines, setLines] = useState<Line[]>(invoice.extracted?.lines ?? []);
  const [locationId, setLocationId] = useState(invoice.location_id ? String(invoice.location_id) : "");
  useEffect(() => {
    setLines(invoice.extracted?.lines ?? []);
    setLocationId(invoice.location_id ? String(invoice.location_id) : "");
  }, [invoice]);

  const editable = manage && invoice.status === "draft";
  const header = invoice.extracted?.header ?? {};
  const update = (index: number, patch: Partial<Line>) => setLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));

  const body = () => ({
    location_id: locationId ? Number(locationId) : null,
    lines: lines.map((l, index) => ({
      index,
      product_id: l.product_id,
      skip: l.skip,
      quantity: l.quantity,
      unit: l.unit || undefined,
      unit_price: l.unit_price ?? undefined,
    })),
  });

  async function save() {
    await action.run(async () => { await api.patch(`/invoices/${invoice.id}`, body()); await onChanged(); }, "Changes saved.");
  }
  async function postReceipt() {
    await action.run(async () => {
      await api.patch(`/invoices/${invoice.id}`, body());
      await api.post(`/invoices/${invoice.id}/post`, { location_id: locationId ? Number(locationId) : null });
      await onChanged();
    }, "Receipt posted. Stock and costs were updated, and the supplier's product names were remembered.");
  }
  async function reject() {
    if (!window.confirm(t("Reject this document? It will not update stock."))) return;
    await action.run(async () => { await api.post(`/invoices/${invoice.id}/reject`); await onChanged(); });
  }

  return (
    <Card title="Review invoice" subtitle={`${header.supplier_name ?? t("Unknown supplier")} · ${header.document_number ?? "—"} · ${header.issue_date ?? "—"}`}
      actions={<button type="button" className="secondary" onClick={() => void action.run(() => api.download(`/invoices/${invoice.id}/file`, invoice.filename ?? `invoice-${invoice.id}`))}>{t("Download original")}</button>}>
      <ErrorNote message={action.error} />
      {action.notice && <p className="notice">{action.notice}</p>}
      {invoice.status === "failed" && <p className="error">{invoice.error}</p>}
      {invoice.status === "posted" && <p className="notice">{t("Posted")} {invoice.receipt_id ? `(${t("receipt")} #${invoice.receipt_id})` : ""}</p>}
      {(invoice.warnings ?? []).map((w) => <p key={w} className="warn-box">⚠ {w}</p>)}
      {invoice.status === "draft" && invoice.blocking.length > 0 && (
        <ul className="blocking">{invoice.blocking.map((b) => <li key={b}>{b}</li>)}</ul>
      )}
      {invoice.source_type !== "ubl_xml" && invoice.status === "draft" && <p className="subtitle">{t("This document was read automatically (PDF text or OCR). Check every line against the original before posting.")}</p>}

      {editable && (
        <div className="filters">
          <label>{t("Receiving location")}
            <select value={locationId} onChange={(e) => setLocationId(e.target.value)} required>
              <option value="">{t("Select")}</option>
              {locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </label>
        </div>
      )}
      {!editable && invoice.location_id && <p className="subtitle">{t("Location")}: {nameOf(locations, invoice.location_id)}</p>}

      <div className="table-wrapper">
        <table>
          <thead><tr><th>{t("On the invoice")}</th><th>{t("Quantity")}</th><th>{t("Unit")}</th><th>{t("Unit price (net)")}</th><th>{t("Product")}</th><th>{t("Skip")}</th></tr></thead>
          <tbody>
            {lines.map((line, index) => (
              <tr key={index} className={line.skip ? "skipped" : ""}>
                <td>{line.description}{line.product_code && <span className="subtitle"> · {line.product_code}</span>}</td>
                <td>{editable ? <input className="narrow" type="number" step="any" min="0" value={line.quantity} onChange={(e) => update(index, { quantity: e.target.value })} /> : money(line.quantity, 3)}</td>
                <td>{editable ? <input className="narrow" value={line.unit ?? ""} onChange={(e) => update(index, { unit: e.target.value.toUpperCase() })} /> : line.unit}</td>
                <td>{editable ? <input className="narrow" type="number" step="any" min="0" value={line.unit_price ?? ""} onChange={(e) => update(index, { unit_price: e.target.value })} /> : money(line.unit_price, 4)}</td>
                <td>
                  {editable ? (
                    <select value={line.product_id ?? ""} onChange={(e) => update(index, { product_id: e.target.value ? Number(e.target.value) : null, match: e.target.value ? "manual" : null })} disabled={line.skip}>
                      <option value="">{t("Choose product")}</option>
                      {products.filter((p) => p.active).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.base_uom})</option>)}
                    </select>
                  ) : nameOf(products, line.product_id)}
                  {line.match && <span className="badge info">{t(line.match)}</span>}
                </td>
                <td>{editable && <input type="checkbox" checked={line.skip} onChange={(e) => update(index, { skip: e.target.checked })} aria-label={t("Skip")} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editable && (
        <div className="actions">
          <button type="button" className="secondary" disabled={action.busy} onClick={() => void save()}>{t("Save changes")}</button>
          <button type="button" disabled={action.busy} onClick={() => void postReceipt()}>{t("Post receipt")}</button>
          <button type="button" className="danger" disabled={action.busy} onClick={() => void reject()}>{t("Reject")}</button>
        </div>
      )}
      {manage && invoice.status === "failed" && <div className="actions"><button type="button" className="danger" onClick={() => void reject()}>{t("Dismiss")}</button></div>}
    </Card>
  );
}

function InboxCard({ inbox, reload, api, role, locations }: { inbox: Inbox | null; reload: () => Promise<void>; api: ViewProps["api"]; role: ViewProps["role"]; locations: ViewProps["locations"] }) {
  const t = useT();
  const action = useAction();
  if (!inbox) return null;
  return (
    <Card title="E-mail intake" subtitle="Suppliers send invoices to your company's own address; they show up above automatically.">
      <ErrorNote message={action.error} />
      {inbox.address ? (
        <p>{t("Your invoice address")}: <code>{inbox.address}</code> <button type="button" className="secondary" onClick={() => void navigator.clipboard?.writeText(inbox.address ?? "")}>{t("Copy")}</button></p>
      ) : (
        <p className="subtitle">{inbox.note}</p>
      )}
      {role === "owner" && (
        <>
          <div className="actions">
            <button type="button" className="secondary" disabled={action.busy || !inbox.configured} onClick={() => void action.run(async () => { await api.post("/invoices/inbox/token"); await reload(); })}>{inbox.address ? t("Generate a new address") : t("Generate address")}</button>
          </div>
          <div className="filters">
            <label>{t("Default receiving location")}
              <select value={inbox.default_location_id ?? ""} onChange={(e) => void action.run(async () => { await api.patch("/invoices/inbox", { default_location_id: e.target.value ? Number(e.target.value) : null }); await reload(); })}>
                <option value="">{t("Choose per invoice")}</option>
                {locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </label>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={inbox.auto_post} onChange={(e) => void action.run(async () => { await api.patch("/invoices/inbox", { auto_post: e.target.checked }); await reload(); })} />
            {t("Post e-Factura XML invoices automatically when every line is matched and the totals add up (PDF and photos always need review)")}
          </label>
        </>
      )}
    </Card>
  );
}
