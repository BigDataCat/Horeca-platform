import { useT } from "../i18n";
import { useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { ViewProps } from "../types";
import { Card, ErrorNote, Pager, fmtDate, useAction, useAsync } from "../ui";

type Subscription = { plan: string; limits: Record<string, number | null>; usage: Record<string, number> };
type AuditEntry = { id: number; user_id: number | null; action: string; entity_type: string; entity_id: number | null; details: Record<string, unknown> | null; created_at: string };

const PAGE = 25;

export default function SettingsView({ api, role, locations, onSignedOutEverywhere, onPasswordChanged, reloadLocations }: ViewProps & { onSignedOutEverywhere: () => void; onPasswordChanged: (token: string) => void; reloadLocations: () => Promise<void> }) {
  const t = useT();
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

  const company = useAsync(() => api.get<{ id: number; alert_digest_enabled: boolean }[]>("/companies"), [api]);
  const [invite, setInvite] = useState({ email: "", first_name: "", last_name: "", role: "employee" });
  const inviteAction = useAction();
  const locationAction = useAction();
  const zones = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone") ?? ["Europe/Bucharest", "Europe/London", "UTC"];

  async function sendInvite(event: FormEvent) {
    event.preventDefault();
    const ok = await inviteAction.run(() => api.post("/users/invite", invite), `Invitation sent to ${invite.email}.`);
    if (ok) setInvite({ ...invite, email: "", first_name: "", last_name: "" });
  }

  async function toggleDigest(enabled: boolean) {
    const id = company.data?.[0]?.id;
    if (id === undefined) return;
    await inviteAction.run(async () => { await api.patch(`/companies/${id}`, { alert_digest_enabled: enabled }); await company.reload(); });
  }

  async function changeZone(id: number, timezone: string) {
    await locationAction.run(async () => { await api.patch(`/locations/${id}`, { timezone }); await reloadLocations(); }, "Time zone saved.");
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
            <div className="metric"><span>{t("Sales imported")}</span><strong>{sub.usage.sales}</strong></div>
          </div>
        </Card>
      )}

      <Card title="Account security">
        <form className="form csv-form" onSubmit={changePassword}>
          <label>{t("Current password")}<input type="password" value={passwords.current} onChange={(e) => setPasswords({ ...passwords, current: e.target.value })} required /></label>
          <label>{t("New password (8+ characters)")}<input type="password" minLength={8} value={passwords.next} onChange={(e) => setPasswords({ ...passwords, next: e.target.value })} required /></label>
          <button type="submit" disabled={action.busy}>{t("Change password")}</button>
        </form>
        <ErrorNote message={action.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
        <div className="actions">
          <button type="button" className="secondary" onClick={() => void action.run(async () => { await api.post("/auth/logout"); onSignedOutEverywhere(); })}>{t("Sign out on all devices")}</button>
        </div>
      </Card>

      {canManage(role) && (
        <Card title="Team" subtitle="Invite a colleague by e-mail: they choose their own password from the link.">
          <form className="form user-form" onSubmit={sendInvite}>
            <label>{t("E-mail")}<input type="email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} required /></label>
            <label>{t("First name")}<input value={invite.first_name} onChange={(e) => setInvite({ ...invite, first_name: e.target.value })} required /></label>
            <label>{t("Last name")}<input value={invite.last_name} onChange={(e) => setInvite({ ...invite, last_name: e.target.value })} required /></label>
            <label>{t("Role")}<select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="employee">{t("Employee")}</option><option value="manager">{t("Manager")}</option>{role === "owner" && <option value="owner">{t("Owner")}</option>}</select></label>
            <span />
            <button type="submit" disabled={inviteAction.busy}>{t("Send invitation")}</button>
          </form>
          <ErrorNote message={inviteAction.error} />
          {inviteAction.notice && <p className="notice">{inviteAction.notice}</p>}
          {role === "owner" && company.data?.[0] && (
            <label className="checkbox"><input type="checkbox" checked={company.data[0].alert_digest_enabled} onChange={(e) => void toggleDigest(e.target.checked)} /> E-mail owners a daily summary of alerts</label>
          )}
        </Card>
      )}

      {canManage(role) && (
        <Card title="Locations and time zones" subtitle="Daily reports follow each location's local calendar day.">
          <ErrorNote message={locationAction.error} />
          {locationAction.notice && <p className="notice">{locationAction.notice}</p>}
          <div className="table-wrapper">
            <table>
              <thead><tr><th>{t("Location")}</th><th>{t("Time zone")}</th></tr></thead>
              <tbody>
                {locations.map((l) => (
                  <tr key={l.id}>
                    <td>{l.name}{!l.active && " (inactive)"}</td>
                    <td><select value={l.timezone ?? "Europe/Bucharest"} onChange={(e) => void changeZone(l.id, e.target.value)}>{zones.map((z) => <option key={z} value={z}>{z}</option>)}</select></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {canManage(role) && (
        <Card title="Audit log" subtitle="Who changed what. Secrets are never recorded.">
          <div className="filters">
            <label>{t("Entity")}<select value={entity} onChange={(e) => { setEntity(e.target.value); setPage(0); }}><option value="">{t("All")}</option>{["product", "product_cost", "recipe", "product_mapping", "uom_conversion", "user", "location", "pos_integration", "supplier", "goods_receipt", "stock_count", "stock_transfer", "sale", "company"].map((t) => <option key={t} value={t}>{t}</option>)}</select></label>
          </div>
          <ErrorNote message={audit.error} />
          <div className="table-wrapper">
            <table>
              <thead><tr><th>{t("When")}</th><th>{t("User")}</th><th>{t("Action")}</th><th>{t("Entity")}</th><th>{t("Details")}</th></tr></thead>
              <tbody>
                {(audit.data?.items ?? []).map((e) => (
                  <tr key={e.id}><td>{fmtDate(e.created_at)}</td><td>{e.user_id ?? "—"}</td><td>{e.action}</td><td>{e.entity_type} #{e.entity_id}</td><td><code>{JSON.stringify(e.details)}</code></td></tr>
                ))}
                {audit.data?.items.length === 0 && <tr><td colSpan={5}>{t("No entries.")}</td></tr>}
              </tbody>
            </table>
          </div>
          <Pager page={page} size={PAGE} total={audit.data?.total ?? 0} onChange={setPage} />
        </Card>
      )}
    </>
  );
}
