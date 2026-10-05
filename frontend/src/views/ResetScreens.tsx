import { useState } from "react";
import { LanguageSwitch, useT } from "../i18n";
import type { FormEvent } from "react";

const API_URL = import.meta.env.VITE_API_URL ?? "/api";

async function post(path: string, body: unknown) {
  const response = await fetch(`${API_URL}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: { msg?: string }) => d.msg).join("\n") : "Request failed");
  }
  return data;
}

export function ForgotPassword({ onBack }: { onBack: () => void }) {
  const t = useT();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/auth/password-reset/request", { email });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="card auth-card">
        <LanguageSwitch />
        <p className="eyebrow">{t("HoReCa Management Platform")}</p>
        <h1>{t("Reset your password")}</h1>
        {sent ? (
          <p className="notice">If an account exists for {email}, an e-mail with a reset link is on its way. The link works once and expires after an hour.</p>
        ) : (
          <form onSubmit={submit} className="auth-form">
            <label>{t("Email")}<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
            <button type="submit" disabled={busy}>{busy ? "Please wait..." : "Send reset link"}</button>
          </form>
        )}
        {error && <p className="error">{error}</p>}
        <button type="button" className="secondary full-width" onClick={onBack}>{t("Back to sign in")}</button>
      </section>
    </main>
  );
}

export function ChooseNewPassword({ token, onDone, onBack }: { token: string; onDone: (accessToken: string) => void; onBack: () => void }) {
  const t = useT();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await post("/auth/password-reset/confirm", { token, new_password: password });
      window.history.replaceState({}, "", window.location.pathname);
      onDone(data.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="card auth-card">
        <LanguageSwitch />
        <p className="eyebrow">{t("HoReCa Management Platform")}</p>
        <h1>{t("Choose a new password")}</h1>
        <form onSubmit={submit} className="auth-form">
          <label>{t("New password (8+ characters)")}<input type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required autoFocus /></label>
          <button type="submit" disabled={busy}>{busy ? "Please wait..." : "Save and sign in"}</button>
        </form>
        {error && <p className="error">{error}</p>}
        <button type="button" className="secondary full-width" onClick={onBack}>{t("Back to sign in")}</button>
      </section>
    </main>
  );
}
