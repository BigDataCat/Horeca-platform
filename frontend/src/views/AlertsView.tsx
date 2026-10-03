import type { ViewProps } from "../types";
import { Card, ErrorNote, useAsync } from "../ui";

type Alert = { type: string; severity: "critical" | "warning" | "info"; message: string };

export default function AlertsView({ api }: ViewProps) {
  const alerts = useAsync(() => api.get<Alert[]>("/alerts"), [api]);
  return (
    <Card
      title="Alerts"
      subtitle="Things that need attention: stock, synchronisation health, mapping and cost gaps."
      actions={<button type="button" className="secondary" onClick={() => void alerts.reload()}>Refresh</button>}
    >
      <ErrorNote message={alerts.error} />
      {alerts.data?.length === 0 && <p className="notice">Everything looks fine — no active alerts.</p>}
      <ul className="alert-list">
        {(alerts.data ?? []).map((alert, index) => (
          <li key={index} className={`alert ${alert.severity}`}>
            <span className={`badge ${alert.severity}`}>{alert.severity}</span> {alert.message}
          </li>
        ))}
      </ul>
    </Card>
  );
}
