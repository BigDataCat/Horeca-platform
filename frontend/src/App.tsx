import { FormEvent, useEffect, useState } from "react";

type Company = {
  id: number;
  name: string;
  tax_identifier: string | null;
  currency: string;
  active: boolean;
};

type Location = {
  id: number;
  company_id: number;
  name: string;
  address: string | null;
  city: string | null;
  country: string;
  active: boolean;
};

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";

function App() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState<number | null>(null);

  const [companyName, setCompanyName] = useState("");
  const [taxIdentifier, setTaxIdentifier] = useState("");
  const [currency, setCurrency] = useState("RON");

  const [locationName, setLocationName] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("RO");
  const [editingLocationId, setEditingLocationId] = useState<number | null>(null);

  const [loadingCompanies, setLoadingCompanies] = useState(true);
  const [loadingLocations, setLoadingLocations] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function loadCompanies() {
    setLoadingCompanies(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/companies`);
      if (!response.ok) throw new Error("Could not load companies.");

      const data: Company[] = await response.json();
      setCompanies(data);

      if (selectedCompanyId === null && data.length > 0) {
        setSelectedCompanyId(data[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load companies.");
    } finally {
      setLoadingCompanies(false);
    }
  }

  async function loadLocations(companyId: number) {
    setLoadingLocations(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/locations?company_id=${companyId}`);
      if (!response.ok) throw new Error("Could not load locations.");

      setLocations(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load locations.");
    } finally {
      setLoadingLocations(false);
    }
  }

  useEffect(() => {
    void loadCompanies();
  }, []);

  useEffect(() => {
    if (selectedCompanyId !== null) {
      void loadLocations(selectedCompanyId);
    } else {
      setLocations([]);
    }
  }, [selectedCompanyId]);

  function resetLocationForm() {
    setLocationName("");
    setAddress("");
    setCity("");
    setCountry("RO");
    setEditingLocationId(null);
  }

  function startEditLocation(location: Location) {
    setEditingLocationId(location.id);
    setLocationName(location.name);
    setAddress(location.address ?? "");
    setCity(location.city ?? "");
    setCountry(location.country);
    setError("");
  }

  async function handleCompanySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");

    try {
      const response = await fetch(`${API_URL}/companies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: companyName,
          tax_identifier: taxIdentifier || null,
          currency,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Could not create company.");
      }

      setCompanyName("");
      setTaxIdentifier("");
      setCurrency("RON");
      await loadCompanies();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create company.");
    } finally {
      setSaving(false);
    }
  }

  async function handleLocationSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (selectedCompanyId === null) {
      setError("Select a company before creating a location.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      const isEditing = editingLocationId !== null;
      const url = isEditing
        ? `${API_URL}/locations/${editingLocationId}`
        : `${API_URL}/locations`;

      const response = await fetch(url, {
        method: isEditing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          isEditing
            ? { name: locationName, address: address || null, city: city || null, country }
            : {
                company_id: selectedCompanyId,
                name: locationName,
                address: address || null,
                city: city || null,
                country,
              },
        ),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Could not save location.");
      }

      resetLocationForm();
      await loadLocations(selectedCompanyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save location.");
    } finally {
      setSaving(false);
    }
  }

  async function deactivateLocation(id: number) {
    setError("");

    try {
      const response = await fetch(`${API_URL}/locations/${id}`, {
        method: "DELETE",
      });

      if (!response.ok) throw new Error("Could not deactivate location.");

      if (selectedCompanyId !== null) {
        await loadLocations(selectedCompanyId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not deactivate location.");
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">HoReCa Management Platform</p>
        <h1>Company & Location Management</h1>
        <p className="subtitle">
          Manage companies and their physical HoReCa locations.
        </p>
      </header>

      <section className="card">
        <h2>Create company</h2>

        <form onSubmit={handleCompanySubmit} className="form">
          <label>
            Company name
            <input
              value={companyName}
              onChange={(event) => setCompanyName(event.target.value)}
              required
              maxLength={200}
            />
          </label>

          <label>
            Tax identifier
            <input
              value={taxIdentifier}
              onChange={(event) => setTaxIdentifier(event.target.value)}
              maxLength={50}
            />
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
            Create company
          </button>
        </form>
      </section>

      <section className="card">
        <div className="section-heading">
          <h2>Companies</h2>
          <button type="button" className="secondary" onClick={() => void loadCompanies()}>
            Refresh
          </button>
        </div>

        {loadingCompanies ? (
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
                  <tr
                    key={company.id}
                    className={selectedCompanyId === company.id ? "selected-row" : ""}
                    onClick={() => setSelectedCompanyId(company.id)}
                  >
                    <td>{company.name}</td>
                    <td>{company.tax_identifier ?? "—"}</td>
                    <td>{company.currency}</td>
                    <td>{company.active ? "Active" : "Inactive"}</td>
                    <td />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Locations</h2>
            <p className="subtitle">
              {selectedCompanyId === null
                ? "Select a company first."
                : `Locations for: ${companies.find((company) => company.id === selectedCompanyId)?.name ?? "selected company"}`}
            </p>
          </div>
          {selectedCompanyId !== null && (
            <button
              type="button"
              className="secondary"
              onClick={() => void loadLocations(selectedCompanyId)}
            >
              Refresh
            </button>
          )}
        </div>

        {selectedCompanyId !== null && (
          <>
            <form onSubmit={handleLocationSubmit} className="form location-form">
              <label>
                Location name
                <input
                  value={locationName}
                  onChange={(event) => setLocationName(event.target.value)}
                  required
                  maxLength={200}
                  placeholder="e.g. Central Restaurant"
                />
              </label>

              <label>
                Address
                <input
                  value={address}
                  onChange={(event) => setAddress(event.target.value)}
                  maxLength={300}
                />
              </label>

              <label>
                City
                <input
                  value={city}
                  onChange={(event) => setCity(event.target.value)}
                  maxLength={100}
                />
              </label>

              <label>
                Country
                <input
                  value={country}
                  onChange={(event) => setCountry(event.target.value.toUpperCase())}
                  minLength={2}
                  maxLength={2}
                  required
                />
              </label>

              <div className="form-actions">
                <button type="submit" disabled={saving}>
                  {saving
                    ? "Saving..."
                    : editingLocationId === null
                      ? "Create location"
                      : "Save changes"}
                </button>

                {editingLocationId !== null && (
                  <button type="button" className="secondary" onClick={resetLocationForm}>
                    Cancel
                  </button>
                )}
              </div>
            </form>

            {loadingLocations ? (
              <p>Loading locations...</p>
            ) : locations.length === 0 ? (
              <p>No locations for this company yet.</p>
            ) : (
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Address</th>
                      <th>City</th>
                      <th>Country</th>
                      <th>Status</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {locations.map((location) => (
                      <tr key={location.id}>
                        <td>{location.name}</td>
                        <td>{location.address ?? "—"}</td>
                        <td>{location.city ?? "—"}</td>
                        <td>{location.country}</td>
                        <td>{location.active ? "Active" : "Inactive"}</td>
                        <td className="actions">
                          {location.active && (
                            <>
                              <button
                                type="button"
                                className="secondary"
                                onClick={() => startEditLocation(location)}
                              >
                                Edit
                              </button>
                              <button
                                type="button"
                                className="danger"
                                onClick={() => void deactivateLocation(location.id)}
                              >
                                Deactivate
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>

      {error && <p className="error">{error}</p>}
    </main>
  );
}

export default App;
