import type { Api } from "../api";
import { useAsync } from "../ui";
import TrendChart from "./TrendChart";

type Row = { date: string; location_id: number; sales: number; net_revenue: string };

export const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Net revenue per local day over the last `days` days, summed across the chosen locations. */
export default function SalesTrend({ api, days = 14, locationId = "", title }: { api: Api; days?: number; locationId?: string; title: string }) {
  const from = new Date();
  from.setDate(from.getDate() - (days - 1));
  const fromIso = isoDay(from);
  const rows = useAsync(
    () => api.get<Row[]>("/reports/daily-sales", { date_from: fromIso, location_id: locationId }),
    [api, fromIso, locationId],
  );
  if (!rows.data) return null;

  const totals = new Map<string, number>();
  for (let i = 0; i < days; i++) {
    const d = new Date(from);
    d.setDate(from.getDate() + i);
    totals.set(isoDay(d), 0);
  }
  rows.data.forEach((r) => totals.set(r.date, (totals.get(r.date) ?? 0) + Number(r.net_revenue)));
  const points = [...totals.entries()].map(([label, value]) => ({ label, value }));
  if (points.every((p) => p.value === 0)) return null;
  return <TrendChart points={points} title={title} unit="RON" format={(n) => n.toLocaleString(undefined, { maximumFractionDigits: 0 })} />;
}
