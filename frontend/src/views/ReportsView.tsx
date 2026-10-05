import { useT } from "../i18n";
import { useState } from "react";
import type { ViewProps } from "../types";
import SalesTrend from "../components/SalesTrend";
import { Card, ErrorNote, money, useAction, useAsync } from "../ui";

type Row = {
  product_id: number;
  product_name: string;
  quantity_sold: string;
  revenue: string;
  cost: string | null;
  margin: string | null;
  food_cost_pct: string | null;
};

export default function ReportsView({ api, locations }: ViewProps) {
  const t = useT();
  const [locationId, setLocationId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const params = {
    location_id: locationId,
    date_from: from ? new Date(from).toISOString() : "",
    date_to: to ? new Date(new Date(to).getTime() + 86400000).toISOString() : "",
  };
  const report = useAsync(() => api.get<Row[]>("/reports/margins", params), [api, locationId, from, to]);
  const action = useAction();
  const rows = report.data ?? [];
  const totalRevenue = rows.reduce((sum, r) => sum + Number(r.revenue), 0);

  return (
    <>
    <Card title="Daily sales" subtitle="Net revenue per local day (each location's own time zone), net of refunds, last 14 days.">
      <SalesTrend api={api} locationId={locationId} title="Net revenue per day" />
    </Card>
    <Card
      title="Margins and food cost"
      subtitle="Revenue vs recipe cost per product over completed sales. Cost is blank when a recipe, an ingredient cost or a UOM conversion is missing — nothing is guessed."
      actions={<button type="button" className="secondary" onClick={() => void action.run(() => api.download("/reports/margins.csv", "margins.csv", params))}>{t("Export CSV")}</button>}
    >
      <div className="filters">
        <label>{t("Location")}<select value={locationId} onChange={(e) => setLocationId(e.target.value)}><option value="">{t("All")}</option>{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        <label>{t("From")}<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>{t("To")}<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      <ErrorNote message={report.error || action.error} />
      <p className="subtitle">Total revenue in range: <strong>{money(totalRevenue)}</strong></p>
      <div className="table-wrapper">
        <table>
          <thead><tr><th>{t("Product")}</th><th>{t("Qty sold")}</th><th>{t("Revenue")}</th><th>{t("Cost")}</th><th>{t("Margin")}</th><th>{t("Food cost %")}</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.product_id}>
                <td>{r.product_name}</td>
                <td>{money(r.quantity_sold, 2)}</td>
                <td>{money(r.revenue)}</td>
                <td>{money(r.cost)}</td>
                <td className={r.margin !== null && Number(r.margin) < 0 ? "negative" : ""}>{money(r.margin)}</td>
                <td>{r.food_cost_pct === null ? "—" : `${money(r.food_cost_pct, 1)}%`}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={6}>{t("No completed, mapped sales in this range.")}</td></tr>}
          </tbody>
        </table>
      </div>
    </Card>
    </>
  );
}
