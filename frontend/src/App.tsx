import { FormEvent, useEffect, useState } from "react";

type Company = {
  id: number;
  name: string;
  tax_identifier: string | null;
  currency: string;
  active: boolean;
};

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";

function App() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [name, setName] = useState("");
  const [taxIdentifier, setTaxIdentifier] = useState("");
  const [currency, setCurrency] = useState("RON");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function loadCompanies() {
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/companies`);
      if (!response.ok) throw new Error("Could not load companies.");
      setCompanies(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load companies.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadCompanies();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/companies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          tax_identifier: taxIdentifier || null,
          currency,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Could not create company.");
      }

      setName("");
      setTaxIdentifier("");
      setCurrency("RON");
      await loadCompanies();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create company.");
    } finally {
      setSaving(false);
    }
  }

  async function deactivateCompany(id: number) {
    setError("");

    try {
      const response = await fetch(`${API_URL}/companies/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Could not deactivate company.");
      await loadCompanies();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not deactivate company.");
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">HoReCa Management Platform</p>
        <h1>Companies</h1>
        <p className="subtitle">First end-to-end module: React → FastAPI → PostgreSQL.</p>
      </header>

      <section className="card">
        <h2>Create company</h2>
        <form onSubmit={handleSubmit} className="form">
          <label>
            Company name
            <input value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} />
          </label>

          <label>
            Tax identifier
            <input value={taxIdentifier} onChange={(event) => setTaxIdentifier(event.target.value)} maxLength={50} />
          </label>

          <label>
            Currency
            <select value={currency} onChange={(event) => setCurrency(event.target.value)}>
              <option value="RON">RON</option>
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
            </select>
          </label>

          <button type="submit" disabled={saving}>
            {saving ? "Saving..." : "Create company"}
          </button>
        </form>
      </section>

      {error && <p className="error">{error}</p>}

      <section className="card">
        <div className="section-heading">
          <h2>Companies</h2>
          <button type="button" className="secondary" onClick={() => void loadCompanies()}>
            Refresh
          </button>
        </div>

        {loading ? (
          <p>Loading...</p>
        ) : companies.length === 0 ? (
          <p>No companies yet.</p>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Tax ID</th>
                  <th>Currency</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {companies.map((company) => (
                  <tr key={company.id}>
                    <td>{company.name}</td>
                    <td>{company.tax_identifier ?? "—"}</td>
                    <td>{company.currency}</td>
                    <td>{company.active ? "Active" : "Inactive"}</td>
                    <td>
                      {company.active && (
                        <button
                          type="button"
                          className="danger"
                          onClick={() => void deactivateCompany(company.id)}
                        >
                          Deactivate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

export default App;
