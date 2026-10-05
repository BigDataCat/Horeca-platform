import { useT } from "../i18n";
import { useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { Integration, ViewProps } from "../types";
import { Card, ErrorNote, fmtDate, nameOf, useAction, useAsync } from "../ui";

const HTTP_TEMPLATE = JSON.stringify(
  {
    sales_path: "/v1/transactions",
    cursor_param: "updated_after",
    page_size_param: "limit",
    page_size: 100,
    page_param: "page",
    items_path: "data.items",
    auth: { type: "bearer" },
    amount_divisor: 100,
    default_currency: "RON",
    mapping: {
      external_id: "id",
      occurred_at: "created_at",
      currency: "currency",
      lines_path: "lines",
      line: { external_product_id: "sku", product_name: "name", quantity: "qty", uom: "unit", unit_price: "price", net_value: "net", tax_value: "tax" },
    },
  },
  null,
  2,
);

type Provider = { provider: string; display_name: string; supported_connection_types: string[] };
type WebhookEvent = { id: number; external_event_id: string; event_type: string; status: string; attempts: number; error_message: string | null; received_at: string };
type SyncRun = { id: number; started_at: string; status: string; fetched: number; imported: number; skipped_duplicates: number; error_message: string | null; trigger: string };

export default function IntegrationsView({ api, role, locations, integrations, refreshIntegrations }: ViewProps) {
  const t = useT();
  const manage = canManage(role);
  const providers = useAsync(() => api.get<Provider[]>("/integrations/pos/providers"), [api]);
  const action = useAction();
  const [selected, setSelected] = useState<number | null>(null);
  const [token, setToken] = useState<{ id: number; value: string } | null>(null);
  const [form, setForm] = useState({ location_id: "", provider: "", name: "", interval: "", base_url: "", credentials_ref: "", config: "" });

  const runs = useAsync(() => (selected ? api.get<SyncRun[]>(`/integrations/pos/${selected}/sync-runs`) : Promise.resolve([] as SyncRun[])), [api, selected]);
  const events = useAsync(
    () => (selected ? api.get<WebhookEvent[]>(`/integrations/pos/${selected}/webhook-events`, { status_filter: "failed" }) : Promise.resolve([] as WebhookEvent[])),
    [api, selected],
  );

  async function create(event: FormEvent) {
    event.preventDefault();
    const provider = providers.data?.find((p) => p.provider === form.provider);
    let config: unknown = null;
    if (form.provider === "http") {
      try {
        config = JSON.parse(form.config);
      } catch {
        action.setError("The configuration is not valid JSON.");
        return;
      }
    }
    const ok = await action.run(async () => {
      await api.post("/integrations/pos", {
        base_url: form.provider === "http" ? form.base_url : null,
        credentials_ref: form.provider === "http" && form.credentials_ref ? form.credentials_ref : null,
        config,
        location_id: Number(form.location_id),
        provider: form.provider,
        name: form.name,
        connection_type: provider?.supported_connection_types[0] ?? "api",
        sync_interval_minutes: form.interval ? Number(form.interval) : null,
      });
      await refreshIntegrations();
    }, "Integration created.");
    if (ok) setForm({ ...form, name: "", interval: "" });
  }

  const reload = async () => {
    await refreshIntegrations();
    await runs.reload();
    await events.reload();
  };

  async function setInterval(integration: Integration) {
    const answer = window.prompt("Automatic sync every how many minutes (5–1440)? Leave empty to disable.", integration.sync_interval_minutes?.toString() ?? "");
    if (answer === null) return;
    await action.run(async () => {
      await api.patch(`/integrations/pos/${integration.id}`, { sync_interval_minutes: answer.trim() ? Number(answer) : null });
      await reload();
    }, "Schedule updated.");
  }

  return (
    <>
      <Card title="POS integrations" subtitle="Connect POS systems. API integrations can sync automatically; CSV integrations accept uploaded exports.">
        <ErrorNote message={action.error || providers.error} />
        {action.notice && <p className="notice">{action.notice}</p>}
        {token && (
          <p className="notice">
            Webhook token for integration #{token.id} (shown once, copy it now): <code>{token.value}</code>
            <br />Send it as the <code>X-Webhook-Token</code> header to <code>POST /api/integrations/pos/{token.id}/webhook</code>.
          </p>
        )}
        <div className="table-wrapper">
          <table>
            <thead><tr><th>{t("Name")}</th><th>{t("Provider")}</th><th>{t("Location")}</th><th>{t("Status")}</th><th>{t("Schedule")}</th><th>{t("Last sync")}</th><th /></tr></thead>
            <tbody>
              {integrations.map((i) => (
                <tr key={i.id} className={selected === i.id ? "selected-row" : ""} onClick={() => setSelected(i.id)}>
                  <td>{i.name}{!i.active && " (inactive)"}</td>
                  <td>{i.provider}</td>
                  <td>{nameOf(locations, i.location_id)}</td>
                  <td>
                    <span className={`badge ${i.sync_paused_reason ? "critical" : i.status === "error" ? "warning" : "completed"}`}>{t(i.sync_paused_reason ? "paused" : i.status)}</span>
                    {i.consecutive_failures > 0 && <span className="subtitle"> {i.consecutive_failures} failure(s)</span>}
                  </td>
                  <td>{i.sync_interval_minutes ? `${t("every")} ${i.sync_interval_minutes} min` : t("manual")}</td>
                  <td>{fmtDate(i.last_synced_at)}</td>
                  <td className="actions" onClick={(e) => e.stopPropagation()}>
                    {manage && i.active && (
                      <>
                        <button type="button" className="secondary" disabled={action.busy} onClick={() => void action.run(async () => { await api.post(`/integrations/pos/${i.id}/test`); await reload(); }, "Connection test finished.")}>{t("Test")}</button>
                        {i.provider !== "csv" && <button type="button" disabled={action.busy} onClick={() => void action.run(async () => { await api.post(`/integrations/pos/${i.id}/sync`); setSelected(i.id); await reload(); }, "Sync finished.").then(reload)}>{t("Sync now")}</button>}
                        {i.provider !== "csv" && <button type="button" className="secondary" onClick={() => void setInterval(i)}>{t("Schedule")}</button>}
                        <button type="button" className="secondary" onClick={() => void action.run(async () => { const r = await api.post<{ webhook_token: string }>(`/integrations/pos/${i.id}/webhook-token`); setToken({ id: i.id, value: r.webhook_token }); await refreshIntegrations(); })}>{t(i.webhook_configured ? "Rotate token" : "Webhook token")}</button>
                        <button type="button" className="danger" onClick={() => { if (window.confirm(`Deactivate ${i.name}?`)) void action.run(async () => { await api.del(`/integrations/pos/${i.id}`); await reload(); }); }}>{t("Deactivate")}</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {integrations.length === 0 && <tr><td colSpan={7}>{t("No integrations yet.")}</td></tr>}
            </tbody>
          </table>
        </div>
        {integrations.find((i) => i.id === selected)?.sync_paused_reason && (
          <p className="error">Automatic sync is paused: {integrations.find((i) => i.id === selected)?.sync_paused_reason} Fix the cause, then set the schedule again to resume.</p>
        )}
      </Card>

      {manage && (
        <Card title="Add integration">
          <form className="form integration-form" onSubmit={create}>
            <label>{t("Location")}<select value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })} required><option value="">{t("Select")}</option>{locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
            <label>{t("Provider")}<select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} required><option value="">{t("Select")}</option>{(providers.data ?? []).map((p) => <option key={p.provider} value={p.provider}>{p.display_name}</option>)}</select></label>
            <label>{t("Name")}<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
            <label>{t("Auto-sync (min)")}<input type="number" min="5" max="1440" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })} placeholder={t("manual")} /></label>
            <button type="submit" disabled={action.busy}>{t("Create")}</button>
          </form>
          {form.provider === "http" && (
            <div className="http-config">
              <p className="subtitle">{t("Generic REST/JSON API: describe the endpoint and how its fields map to a sale. The secret is read from a server environment variable, never stored here.")}</p>
              <div className="filters">
                <label>{t("Base URL")}<input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.example-pos.com" required /></label>
                <label>{t("Secret reference")}<input value={form.credentials_ref} onChange={(e) => setForm({ ...form, credentials_ref: e.target.value })} placeholder="env:MYPOS_TOKEN" /></label>
                <button type="button" className="secondary" onClick={() => setForm({ ...form, config: HTTP_TEMPLATE })}>{t("Insert example configuration")}</button>
              </div>
              <label>{t("Configuration (JSON)")}<textarea rows={14} value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} spellCheck={false} required /></label>
            </div>
          )}
        </Card>
      )}

      {selected && (
        <>
          <Card title="Sync history" subtitle={`Integration #${selected}`}>
            <ErrorNote message={runs.error} />
            <div className="table-wrapper">
              <table>
                <thead><tr><th>{t("Started")}</th><th>{t("Trigger")}</th><th>{t("Status")}</th><th>{t("Fetched")}</th><th>{t("Imported")}</th><th>{t("Duplicates")}</th><th>{t("Error")}</th></tr></thead>
                <tbody>
                  {(runs.data ?? []).map((r) => <tr key={r.id}><td>{fmtDate(r.started_at)}</td><td>{t(r.trigger)}</td><td><span className={`badge ${r.status === "success" ? "completed" : "critical"}`}>{t(r.status)}</span></td><td>{r.fetched}</td><td>{r.imported}</td><td>{r.skipped_duplicates}</td><td>{r.error_message ?? ""}</td></tr>)}
                  {runs.data?.length === 0 && <tr><td colSpan={7}>{t("No sync runs yet.")}</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Failed webhook events" subtitle="Fix the cause (for example add the missing UOM conversion), then replay.">
            <ErrorNote message={events.error} />
            <div className="table-wrapper">
              <table>
                <thead><tr><th>{t("Received")}</th><th>{t("Event")}</th><th>{t("Type")}</th><th>{t("Attempts")}</th><th>{t("Error")}</th><th /></tr></thead>
                <tbody>
                  {(events.data ?? []).map((e) => (
                    <tr key={e.id}>
                      <td>{fmtDate(e.received_at)}</td><td>{e.external_event_id}</td><td>{e.event_type}</td><td>{e.attempts}</td><td>{e.error_message}</td>
                      <td>{manage && <button type="button" disabled={action.busy} onClick={() => void action.run(async () => { await api.post(`/integrations/pos/${selected}/webhook-events/${e.id}/replay`); await events.reload(); }, "Event replayed.")}>{t("Replay")}</button>}</td>
                    </tr>
                  ))}
                  {events.data?.length === 0 && <tr><td colSpan={6}>{t("No failed events.")}</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
