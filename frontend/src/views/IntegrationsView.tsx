import { useState } from "react";
import type { FormEvent } from "react";
import { canManage } from "../types";
import type { Integration, ViewProps } from "../types";
import { Card, ErrorNote, fmtDate, nameOf, useAction, useAsync } from "../ui";

type Provider = { provider: string; display_name: string; supported_connection_types: string[] };
type WebhookEvent = { id: number; external_event_id: string; event_type: string; status: string; attempts: number; error_message: string | null; received_at: string };
type SyncRun = { id: number; started_at: string; status: string; fetched: number; imported: number; skipped_duplicates: number; error_message: string | null; trigger: string };

export default function IntegrationsView({ api, role, locations, integrations, refreshIntegrations }: ViewProps) {
  const manage = canManage(role);
  const providers = useAsync(() => api.get<Provider[]>("/integrations/pos/providers"), [api]);
  const action = useAction();
  const [selected, setSelected] = useState<number | null>(null);
  const [token, setToken] = useState<{ id: number; value: string } | null>(null);
  const [form, setForm] = useState({ location_id: "", provider: "", name: "", interval: "" });

  const runs = useAsync(() => (selected ? api.get<SyncRun[]>(`/integrations/pos/${selected}/sync-runs`) : Promise.resolve([] as SyncRun[])), [api, selected]);
  const events = useAsync(
    () => (selected ? api.get<WebhookEvent[]>(`/integrations/pos/${selected}/webhook-events`, { status_filter: "failed" }) : Promise.resolve([] as WebhookEvent[])),
    [api, selected],
  );

  async function create(event: FormEvent) {
    event.preventDefault();
    const provider = providers.data?.find((p) => p.provider === form.provider);
    const ok = await action.run(async () => {
      await api.post("/integrations/pos", {
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
            <thead><tr><th>Name</th><th>Provider</th><th>Location</th><th>Status</th><th>Schedule</th><th>Last sync</th><th /></tr></thead>
            <tbody>
              {integrations.map((i) => (
                <tr key={i.id} className={selected === i.id ? "selected-row" : ""} onClick={() => setSelected(i.id)}>
                  <td>{i.name}{!i.active && " (inactive)"}</td>
                  <td>{i.provider}</td>
                  <td>{nameOf(locations, i.location_id)}</td>
                  <td>
                    <span className={`badge ${i.sync_paused_reason ? "critical" : i.status === "error" ? "warning" : "completed"}`}>{i.sync_paused_reason ? "paused" : i.status}</span>
                    {i.consecutive_failures > 0 && <span className="subtitle"> {i.consecutive_failures} failure(s)</span>}
                  </td>
                  <td>{i.sync_interval_minutes ? `every ${i.sync_interval_minutes} min` : "manual"}</td>
                  <td>{fmtDate(i.last_synced_at)}</td>
                  <td className="actions" onClick={(e) => e.stopPropagation()}>
                    {manage && i.active && (
                      <>
                        <button type="button" className="secondary" disabled={action.busy} onClick={() => void action.run(async () => { await api.post(`/integrations/pos/${i.id}/test`); await reload(); }, "Connection test finished.")}>Test</button>
                        {i.provider !== "csv" && <button type="button" disabled={action.busy} onClick={() => void action.run(async () => { await api.post(`/integrations/pos/${i.id}/sync`); setSelected(i.id); await reload(); }, "Sync finished.").then(reload)}>Sync now</button>}
                        {i.provider !== "csv" && <button type="button" className="secondary" onClick={() => void setInterval(i)}>Schedule</button>}
                        <button type="button" className="secondary" onClick={() => void action.run(async () => { const r = await api.post<{ webhook_token: string }>(`/integrations/pos/${i.id}/webhook-token`); setToken({ id: i.id, value: r.webhook_token }); await refreshIntegrations(); })}>{i.webhook_configured ? "Rotate token" : "Webhook token"}</button>
                        <button type="button" className="danger" onClick={() => { if (window.confirm(`Deactivate ${i.name}?`)) void action.run(async () => { await api.del(`/integrations/pos/${i.id}`); await reload(); }); }}>Deactivate</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {integrations.length === 0 && <tr><td colSpan={7}>No integrations yet.</td></tr>}
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
            <label>Location<select value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })} required><option value="">Select</option>{locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
            <label>Provider<select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} required><option value="">Select</option>{(providers.data ?? []).map((p) => <option key={p.provider} value={p.provider}>{p.display_name}</option>)}</select></label>
            <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
            <label>Auto-sync (min)<input type="number" min="5" max="1440" value={form.interval} onChange={(e) => setForm({ ...form, interval: e.target.value })} placeholder="manual" /></label>
            <button type="submit" disabled={action.busy}>Create</button>
          </form>
        </Card>
      )}

      {selected && (
        <>
          <Card title="Sync history" subtitle={`Integration #${selected}`}>
            <ErrorNote message={runs.error} />
            <div className="table-wrapper">
              <table>
                <thead><tr><th>Started</th><th>Trigger</th><th>Status</th><th>Fetched</th><th>Imported</th><th>Duplicates</th><th>Error</th></tr></thead>
                <tbody>
                  {(runs.data ?? []).map((r) => <tr key={r.id}><td>{fmtDate(r.started_at)}</td><td>{r.trigger}</td><td><span className={`badge ${r.status === "success" ? "completed" : "critical"}`}>{r.status}</span></td><td>{r.fetched}</td><td>{r.imported}</td><td>{r.skipped_duplicates}</td><td>{r.error_message ?? ""}</td></tr>)}
                  {runs.data?.length === 0 && <tr><td colSpan={7}>No sync runs yet.</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Failed webhook events" subtitle="Fix the cause (for example add the missing UOM conversion), then replay.">
            <ErrorNote message={events.error} />
            <div className="table-wrapper">
              <table>
                <thead><tr><th>Received</th><th>Event</th><th>Type</th><th>Attempts</th><th>Error</th><th /></tr></thead>
                <tbody>
                  {(events.data ?? []).map((e) => (
                    <tr key={e.id}>
                      <td>{fmtDate(e.received_at)}</td><td>{e.external_event_id}</td><td>{e.event_type}</td><td>{e.attempts}</td><td>{e.error_message}</td>
                      <td>{manage && <button type="button" disabled={action.busy} onClick={() => void action.run(async () => { await api.post(`/integrations/pos/${selected}/webhook-events/${e.id}/replay`); await events.reload(); }, "Event replayed.")}>Replay</button>}</td>
                    </tr>
                  ))}
                  {events.data?.length === 0 && <tr><td colSpan={6}>No failed events.</td></tr>}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
