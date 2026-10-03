import { Fragment, useRef, useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { ViewProps } from "../types";
import { Card, ErrorNote, Pager, fmtDate, money, nameOf, useAction, useAsync } from "../ui";

type SaleLine = { id: number; product_name: string; product_id: number | null; quantity: string; uom: string; net_value: string };
type Sale = {
  id: number;
  external_id: string;
  location_id: number;
  integration_id: number | null;
  occurred_at: string;
  currency: string;
  net_value: string;
  gross_value: string;
  status: string;
  status_reason: string | null;
  lines: SaleLine[];
};

const PAGE = 25;

export default function SalesView({ api, role, locations, integrations }: ViewProps) {
  const [locationId, setLocationId] = useState("");
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const filters = {
    location_id: locationId,
    status,
    date_from: from ? new Date(from).toISOString() : "",
    date_to: to ? new Date(new Date(to).getTime() + 86400000).toISOString() : "",
  };
  const sales = useAsync(
    () => api.page<Sale>("/sales", { ...filters, limit: PAGE, offset: page * PAGE }),
    [api, locationId, status, from, to, page],
  );
  const action = useAction();
  const fileInput = useRef<HTMLInputElement>(null);
  const [csvIntegration, setCsvIntegration] = useState("");
  const csvIntegrations = integrations.filter((i) => i.provider === "csv" && i.active);

  async function changeStatus(sale: Sale, next: "cancelled" | "refunded") {
    const reason = window.prompt(`Reason for marking sale ${sale.external_id} as ${next} (optional)`) ?? null;
    if (reason === null) return;
    await action.run(async () => {
      await api.post(`/sales/${sale.id}/status`, { status: next, reason: reason || null });
      await sales.reload();
    }, `Sale ${sale.external_id} marked ${next}. Ingredient stock was restored.`);
  }

  async function importCsv(event: FormEvent) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file || !csvIntegration) return;
    await action.run(async () => {
      const result = await api.uploadCsv<{ imported: number; skipped_duplicates: number }>(
        `/sales/import-csv?integration_id=${csvIntegration}`,
        await file.text(),
      );
      await sales.reload();
      action.setError("");
      return result;
    }, "CSV imported.");
  }

  return (
    <>
      <Card
        title="Sales"
        subtitle="Imported transactions. Cancelled and refunded sales are excluded from revenue."
        actions={<button type="button" className="secondary" onClick={() => void action.run(() => api.download("/sales/export.csv", "sales.csv", filters))}>Export CSV</button>}
      >
        <div className="filters">
          <label>Location<select value={locationId} onChange={(e) => { setLocationId(e.target.value); setPage(0); }}><option value="">All</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
          <label>Status<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}><option value="">All</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option><option value="refunded">Refunded</option></select></label>
          <label>From<input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(0); }} /></label>
          <label>To<input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(0); }} /></label>
        </div>
        <ErrorNote message={sales.error || action.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
        <div className="table-wrapper">
          <table>
            <thead><tr><th>Sale</th><th>When</th><th>Location</th><th>Net</th><th>Gross</th><th>Status</th><th /></tr></thead>
            <tbody>
              {(sales.data?.items ?? []).map((sale) => (
                <Fragment key={sale.id}>
                  <tr onClick={() => setOpen(open === sale.id ? null : sale.id)}>
                    <td>{sale.external_id}</td>
                    <td>{fmtDate(sale.occurred_at)}</td>
                    <td>{nameOf(locations, sale.location_id)}</td>
                    <td>{money(sale.net_value)} {sale.currency}</td>
                    <td>{money(sale.gross_value)} {sale.currency}</td>
                    <td><span className={`badge ${sale.status}`}>{sale.status}</span></td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      {canManage(role) && sale.status === "completed" && (
                        <>
                          <button type="button" className="secondary" disabled={action.busy} onClick={() => void changeStatus(sale, "cancelled")}>Cancel</button>
                          <button type="button" className="secondary" disabled={action.busy} onClick={() => void changeStatus(sale, "refunded")}>Refund</button>
                        </>
                      )}
                    </td>
                  </tr>
                  {open === sale.id && (
                    <tr>
                      <td colSpan={7}>
                        {sale.status_reason && <p className="subtitle">Reason: {sale.status_reason}</p>}
                        <table>
                          <thead><tr><th>Product</th><th>Qty</th><th>Net</th><th>Mapped</th></tr></thead>
                          <tbody>
                            {sale.lines.map((l) => (
                              <tr key={l.id}><td>{l.product_name}</td><td>{l.quantity} {l.uom}</td><td>{money(l.net_value)}</td><td>{l.product_id ? "yes" : <strong>no</strong>}</td></tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {sales.data?.items.length === 0 && <tr><td colSpan={7}>No sales match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} size={PAGE} total={sales.data?.total ?? 0} onChange={setPage} />
      </Card>

      {canManage(role) && (
        <Card title="Import sales from CSV" subtitle="For POS systems without an API. One row per sale line: sale_id, occurred_at, product_name, quantity, unit_price (optional: currency, external_product_id, uom, net_value, tax_value). Re-uploading is safe.">
          {csvIntegrations.length === 0 ? (
            <p className="subtitle">Create an integration with provider “csv” (Integrations tab) to enable CSV import.</p>
          ) : (
            <form className="form csv-form" onSubmit={importCsv}>
              <label>Integration<select value={csvIntegration} onChange={(e) => setCsvIntegration(e.target.value)} required><option value="">Select</option>{csvIntegrations.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></label>
              <label>CSV file<input ref={fileInput} type="file" accept=".csv,text/csv" required /></label>
              <button type="submit" disabled={action.busy}>Import</button>
            </form>
          )}
        </Card>
      )}
    </>
  );
}
