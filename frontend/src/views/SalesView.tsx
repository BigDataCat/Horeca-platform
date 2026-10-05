import { useT } from "../i18n";
import { Fragment, useRef, useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { ViewProps } from "../types";
import { Card, ErrorNote, Pager, fmtDate, money, nameOf, useAction, useAsync } from "../ui";

type SaleLine = { id: number; product_name: string; product_id: number | null; quantity: string; uom: string; net_value: string; refunded_quantity: string };
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
  refunded_net_value: string;
  lines: SaleLine[];
};

const PAGE = 25;

export default function SalesView({ api, role, locations, integrations }: ViewProps) {
  const t = useT();
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

  async function refundLine(sale: Sale, line: SaleLine) {
    const remaining = Number(line.quantity) - Number(line.refunded_quantity);
    const answer = window.prompt(`Quantity of "${line.product_name}" to refund (up to ${remaining}):`, String(remaining));
    if (answer === null || !answer.trim()) return;
    const reason = window.prompt("Reason (optional)") ?? null;
    await action.run(async () => {
      await api.post(`/sales/${sale.id}/refund-lines`, { lines: [{ line_id: line.id, quantity: answer.trim() }], reason: reason || null });
      await sales.reload();
    }, "Refund recorded. Revenue and ingredient stock were adjusted.");
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
        actions={<button type="button" className="secondary" onClick={() => void action.run(() => api.download("/sales/export.csv", "sales.csv", filters))}>{t("Export CSV")}</button>}
      >
        <div className="filters">
          <label>{t("Location")}<select value={locationId} onChange={(e) => { setLocationId(e.target.value); setPage(0); }}><option value="">{t("All")}</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
          <label>{t("Status")}<select value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}><option value="">{t("All")}</option><option value="completed">{t("Completed")}</option><option value="cancelled">{t("Cancelled")}</option><option value="partially_refunded">{t("Partially refunded")}</option><option value="refunded">{t("Refunded")}</option></select></label>
          <label>{t("From")}<input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPage(0); }} /></label>
          <label>{t("To")}<input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPage(0); }} /></label>
        </div>
        <ErrorNote message={sales.error || action.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("Sale")}</th><th>{t("When")}</th><th>{t("Location")}</th><th>{t("Net")}</th><th>{t("Gross")}</th><th>{t("Status")}</th><th /></tr></thead>
            <tbody>
              {(sales.data?.items ?? []).map((sale) => (
                <Fragment key={sale.id}>
                  <tr onClick={() => setOpen(open === sale.id ? null : sale.id)}>
                    <td>{sale.external_id}</td>
                    <td>{fmtDate(sale.occurred_at)}</td>
                    <td>{nameOf(locations, sale.location_id)}</td>
                    <td>{money(sale.net_value)} {sale.currency}</td>
                    <td>{money(sale.gross_value)} {sale.currency}</td>
                    <td><span className={`badge ${sale.status}`}>{t(sale.status)}</span></td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      {canManage(role) && (sale.status === "completed" || sale.status === "partially_refunded") && (
                        <>
                          <button type="button" className="secondary" disabled={action.busy} onClick={() => void changeStatus(sale, "cancelled")}>{t("Cancel")}</button>
                          <button type="button" className="secondary" disabled={action.busy} onClick={() => void changeStatus(sale, "refunded")}>{t("Refund")}</button>
                        </>
                      )}
                    </td>
                  </tr>
                  {open === sale.id && (
                    <tr>
                      <td colSpan={7}>
                        {sale.status_reason && <p className="subtitle">Reason: {sale.status_reason}</p>}
                        {Number(sale.refunded_net_value) > 0 && <p className="subtitle">Refunded so far: {money(sale.refunded_net_value)} {sale.currency} net</p>}
                        <table>
                          <thead><tr><th>{t("Product")}</th><th>{t("Qty")}</th><th>{t("Refunded")}</th><th>{t("Net")}</th><th>{t("Mapped")}</th><th /></tr></thead>
                          <tbody>
                            {sale.lines.map((l) => (
                              <tr key={l.id}><td>{l.product_name}</td><td>{Number(l.quantity)} {l.uom}</td><td>{Number(l.refunded_quantity) || "—"}</td><td>{money(l.net_value)}</td><td>{l.product_id ? "yes" : <strong>{t("no")}</strong>}</td><td>{canManage(role) && sale.status !== "cancelled" && sale.status !== "refunded" && Number(l.refunded_quantity) < Number(l.quantity) && <button type="button" className="secondary" disabled={action.busy} onClick={() => void refundLine(sale, l)}>{t("Refund")}</button>}</td></tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {sales.data?.items.length === 0 && <tr><td colSpan={7}>{t("No sales match these filters.")}</td></tr>}
            </tbody>
          </table>
        </div>
        <Pager page={page} size={PAGE} total={sales.data?.total ?? 0} onChange={setPage} />
      </Card>

      {canManage(role) && (
        <Card title="Import sales from CSV" subtitle="For POS systems without an API. One row per sale line: sale_id, occurred_at, product_name, quantity, unit_price (optional: currency, external_product_id, uom, net_value, tax_value). Re-uploading is safe.">
          {csvIntegrations.length === 0 ? (
            <p className="subtitle">{t("Create an integration with provider \u201ccsv\u201d (Integrations tab) to enable CSV import.")}</p>
          ) : (
            <form className="form csv-form" onSubmit={importCsv}>
              <label>{t("Integration")}<select value={csvIntegration} onChange={(e) => setCsvIntegration(e.target.value)} required><option value="">{t("Select")}</option>{csvIntegrations.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></label>
              <label>{t("CSV file")}<input ref={fileInput} type="file" accept=".csv,text/csv" required /></label>
              <button type="submit" disabled={action.busy}>{t("Import")}</button>
            </form>
          )}
        </Card>
      )}
    </>
  );
}
