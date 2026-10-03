import { useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { ViewProps } from "../types";
import { Card, ErrorNote, Pager, fmtDate, useAction, useAsync } from "../ui";

type Subscription = { plan: string; limits: Record<string, number | null>; usage: Record<string, number> };
type AuditEntry = { id: number; user_id: number | null; action: string; entity_type: string; entity_id: number | null; details: Record<string, unknown> | null; created_at: string };

const PAGE = 25;

export default function SettingsView({ api, role, onSignedOutEverywhere, onPasswordChanged }: ViewProps & { onSignedOutEverywhere: () => void; onPasswordChanged: (token: string) => void }) {
  const subscription = useAsync(() => api.get<Subscription>("/subscription"), [api]);
  const action = useAction();
  const [passwords, setPasswords] = useState({ current: "", next: "" });
  const [entity, setEntity] = useState("");
  const [page, setPage] = useState(0);
  const audit = useAsync(
    () => (canManage(role) ? api.page<AuditEntry>("/audit-log", { entity_type: entity, limit: PAGE, offset: page * PAGE }) : Promise.resolve({ items: [] as AuditEntry[], total: 0 })),
    [api, role, entity, page],
  );

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    const ok = await action.run(async () => {
      const result = await api.post<{ access_token: string }>("/auth/change-password", { current_password: passwords.current, new_password: passwords.next });
      onPasswordChanged(result.access_token);
    }, "Password changed. Other devices were signed out.");
    if (ok) setPasswords({ current: "", next: "" });
  }

  const sub = subscription.data;
  return (
    <>
      {sub && (
        <Card title="Subscription" subtitle={`Current plan: ${sub.plan}`}>
          <div className="dashboard-grid">
            {["locations", "users", "integrations"].map((key) => (
              <div className="metric" key={key}>
                <span>Active {key}</span>
                <strong>{sub.usage[key]} / {sub.limits[key] ?? "∞"}</strong>
              </div>
            ))}
            <div className="metric"><span>Sales imported</span><strong>{sub.usage.sales}</strong></div>
          </div>
        </Card>
      )}

      <Card title="Account security">
        <form className="form csv-form" onSubmit={changePassword}>
          <label>Current password<input type="password" value={passwords.current} onChange={(e) => setPasswords({ ...passwords, current: e.target.value })} required /></label>
          <label>New password (8+ characters)<input type="password" minLength={8} value={passwords.next} onChange={(e) => setPasswords({ ...passwords, next: e.target.value })} required /></label>
          <button type="submit" disabled={action.busy}>Change password</button>
        </form>
        <ErrorNote message={action.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
        <div className="actions">
          <button type="button" className="secondary" onClick={() => void action.run(async () => { await api.post("/auth/logout"); onSignedOutEverywhere(); })}>Sign out on all devices</button>
        </div>
      </Card>

      {canManage(role) && (
        <Card title="Audit log" subtitle="Who changed what. Secrets are never recorded.">
          <div className="filters">
            <label>Entity<select value={entity} onChange={(e) => { setEntity(e.target.value); setPage(0); }}><option value="">All</option>{["product", "product_cost", "recipe", "product_mapping", "uom_conversion", "user", "location", "pos_integration", "supplier", "goods_receipt", "stock_count", "stock_transfer", "sale", "company"].map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
          </div>
          <ErrorNote message={audit.error} />
          <div className="table-wrapper">
            <table>
              <thead><tr><th>When</th><th>User</th><th>Action</th><th>Entity</th><th>Details</th></tr></thead>
              <tbody>
                {(audit.data?.items ?? []).map((e) => (
                  <tr key={e.id}><td>{fmtDate(e.created_at)}</td><td>{e.user_id ?? "—"}</td><td>{e.action}</td><td>{e.entity_type} #{e.entity_id}</td><td><code>{JSON.stringify(e.details)}</code></td></tr>
                ))}
                {audit.data?.items.length === 0 && <tr><td colSpan={5}>No entries.</td></tr>}
              </tbody>
            </table>
          </div>
          <Pager page={page} size={PAGE} total={audit.data?.total ?? 0} onChange={setPage} />
        </Card>
      )}
    </>
  );
}
