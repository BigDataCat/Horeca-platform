import { useT } from "../i18n";
import type { ViewProps } from "../types";
import { Card, ErrorNote, useAsync } from "../ui";

type Alert = { type: string; severity: "critical" | "warning" | "info"; message: string };

export default function AlertsView({ api }: ViewProps) {
  const t = useT();
  const alerts = useAsync(() => api.get<Alert[]>("/alerts"), [api]);
  return (
    <Card
      title="Alerts"
      subtitle="Things that need attention: stock, synchronisation health, mapping and cost gaps."
      actions={<button type="button" className="secondary" onClick={() => void alerts.reload()}>{t("Refresh")}</button>}
    >
      <ErrorNote message={alerts.error} />
      {alerts.data?.length === 0 && <p className="notice">{t("Everything looks fine \u2014 no active alerts.")}</p>}
      <ul className="alert-list">
        {(alerts.data ?? []).map((alert, index) => (
          <li key={index} className={`alert ${alert.severity}`}>
            <span className={`badge ${alert.severity}`}>{t(alert.severity)}</span> {alert.message}
          </li>
        ))}
      </ul>
    </Card>
  );
}
