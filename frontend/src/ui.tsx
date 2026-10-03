import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await loader());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, deps);
  useEffect(() => {
    void run();
  }, [run]);
  return { data, error, loading, reload: run };
}

export function ErrorNote({ message }: { message: string }) {
  return message ? <p className="error" role="alert" style={{ whiteSpace: "pre-line" }}>{message}</p> : null;
}

export function Card({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      <div className="section-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p className="subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function Pager({ page, size, total, onChange }: { page: number; size: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="actions pager">
      <button type="button" className="secondary" disabled={page <= 0} onClick={() => onChange(page - 1)}>Previous</button>
      <span>Page {page + 1} of {pages} · {total} rows</span>
      <button type="button" className="secondary" disabled={page + 1 >= pages} onClick={() => onChange(page + 1)}>Next</button>
    </div>
  );
}

export const fmtDate = (value: string | null | undefined) => (value ? new Date(value).toLocaleString() : "—");

export function money(value: string | number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : String(value);
}

export function nameOf<T extends { id: number; name: string }>(items: T[], id: number | null | undefined) {
  return items.find((item) => item.id === id)?.name ?? (id ?? "—");
}

export function useAction() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function run(action: () => Promise<unknown>, success = "") {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(success);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { error, busy, notice, run, setError };
}
