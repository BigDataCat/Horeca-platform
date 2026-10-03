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

type User = {
  id: number;
  company_id: number;
  email: string;
  first_name: string;
  last_name: string;
  role: "owner" | "manager" | "employee";
  active: boolean;
};

type AuthResponse = {
  access_token: string;
  token_type: string;
  user: User;
};

type DashboardSummary = {
  sales_count: number;
  revenue: string;
  tax: string;
  gross_revenue: string;
  average_ticket: string;
  unmatched_products: number;
  stock_items: number;
  stock_value: string;
};

type POSProvider = {
  provider: string;
  display_name: string;
  supported_connection_types: ("api" | "webhook" | "file")[];
  capabilities: string[];
};

type SyncRun = {
  id: number;
  integration_id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  fetched: number;
  imported: number;
  skipped_duplicates: number;
  error_message: string | null;
};

type POSIntegration = {
  id: number;
  company_id: number;
  location_id: number;
  provider: string;
  name: string;
  connection_type: "api" | "webhook" | "file";
  status: "inactive" | "connected" | "error";
  base_url: string | null;
  external_account_id: string | null;
  credentials_ref: string | null;
  config: Record<string, unknown> | null;
  active: boolean;
};

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000/api";
const TOKEN_KEY = "horeca_access_token";

async function apiFetch(path: string, options: RequestInit = {}, token?: string) {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  return fetch(`${API_URL}${path}`, { ...options, headers });
}

function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [currentUser, setCurrentUser] = useState<User | null>(null);

  const [authMode, setAuthMode] = useState<"login" | "bootstrap">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [registerCompanyId, setRegisterCompanyId] = useState("");
  const [registerCompanyName, setRegisterCompanyName] = useState("");
  const [registerTaxIdentifier, setRegisterTaxIdentifier] = useState("");
  const [registerFirstName, setRegisterFirstName] = useState("");
  const [registerLastName, setRegisterLastName] = useState("");

  const [companies, setCompanies] = useState<Company[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [integrations, setIntegrations] = useState<POSIntegration[]>([]);
  const [syncRuns, setSyncRuns] = useState<Record<number, SyncRun[]>>({});
  const [posProviders, setPosProviders] = useState<POSProvider[]>([]);
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [products, setProducts] = useState<{ id: number; name: string; sku: string | null; base_uom: string; active: boolean }[]>([]);
  const [mappings, setMappings] = useState<{ id: number; integration_id: number; external_product_id: string; external_product_name: string | null; product_id: number; match_method: string }[]>([]);
  const [uomConversions, setUomConversions] = useState<{ id: number; product_id: number; from_uom: string; to_uom: string; factor: number }[]>([]);
  const [unmatchedProducts, setUnmatchedProducts] = useState<{
    integration_id: number;
    external_product_id: string;
    product_name: string;
    uom: string;
    occurrences: number;
    total_quantity: number;
  }[]>([]);
  const [newIntegrationName, setNewIntegrationName] = useState("");
  const [newIntegrationProvider, setNewIntegrationProvider] = useState("demo");
  const [newIntegrationLocationId, setNewIntegrationLocationId] = useState("");
  const [newIntegrationConnectionType, setNewIntegrationConnectionType] = useState<POSIntegration["connection_type"]>("api");
  const [newIntegrationBaseUrl, setNewIntegrationBaseUrl] = useState("");
  const [newIntegrationAccountId, setNewIntegrationAccountId] = useState("");

  const [newProductName, setNewProductName] = useState("");
  const [newProductSku, setNewProductSku] = useState("");
  const [newProductUom, setNewProductUom] = useState("EA");
  const [mappingIntegrationId, setMappingIntegrationId] = useState("");
  const [mappingExternalId, setMappingExternalId] = useState("");
  const [mappingProductId, setMappingProductId] = useState("");
  const [conversionProductId, setConversionProductId] = useState("");
  const [conversionFromUom, setConversionFromUom] = useState("");
  const [conversionToUom, setConversionToUom] = useState("");
  const [conversionFactor, setConversionFactor] = useState("");
  const [selectedCompanyId, setSelectedCompanyId] = useState<number | null>(null);

  const [companyName, setCompanyName] = useState("");
  const [taxIdentifier, setTaxIdentifier] = useState("");
  const [currency, setCurrency] = useState("RON");

  const [locationName, setLocationName] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("RO");
  const [editingLocationId, setEditingLocationId] = useState<number | null>(null);

  const [newUserEmail, setNewUserEmail] = useState("");
  const [newUserPassword, setNewUserPassword] = useState("");
  const [newUserFirstName, setNewUserFirstName] = useState("");
  const [newUserLastName, setNewUserLastName] = useState("");
  const [newUserRole, setNewUserRole] = useState<User["role"]>("employee");

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function readError(response: Response, fallback: string) {
    const body = await response.json().catch(() => null);
    return body?.detail ?? fallback;
  }

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");

    try {
      if (authMode === "login") {
        const response = await apiFetch("/auth/login", {
          method: "POST",
          body: JSON.stringify({ email: authEmail, password: authPassword }),
        });

        if (!response.ok) throw new Error(await readError(response, "Login failed."));

        const data: AuthResponse = await response.json();
        localStorage.setItem(TOKEN_KEY, data.access_token);
        setToken(data.access_token);
        setCurrentUser(data.user);
      } else {
        const response = await apiFetch("/auth/bootstrap", {
          method: "POST",
          body: JSON.stringify({
            company_name: registerCompanyName,
            tax_identifier: registerTaxIdentifier || null,
            currency: "RON",
            email: authEmail,
            password: authPassword,
            first_name: registerFirstName,
            last_name: registerLastName,
            role: "owner",
          }),
        });

        if (!response.ok) throw new Error(await readError(response, "Registration failed."));

        const data: AuthResponse = await response.json();
        localStorage.setItem(TOKEN_KEY, data.access_token);
        setToken(data.access_token);
        setCurrentUser(data.user);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setSaving(false);
    }
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setCurrentUser(null);
    setCompanies([]);
    setLocations([]);
    setUsers([]);
  }

  async function loadMe(activeToken: string) {
    const response = await apiFetch("/auth/me", {}, activeToken);

    if (!response.ok) {
      logout();
      return;
    }

    setCurrentUser(await response.json());
  }

  async function loadCompanies(activeToken = token) {
    if (!activeToken) return;

    setLoading(true);
    setError("");

    try {
      const response = await apiFetch("/companies", {}, activeToken);
      if (!response.ok) throw new Error(await readError(response, "Could not load companies."));

      const data: Company[] = await response.json();
      setCompanies(data);

      if (selectedCompanyId === null && data.length > 0) {
        setSelectedCompanyId(data[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load companies.");
    } finally {
      setLoading(false);
    }
  }

  async function loadLocations(companyId: number) {
    if (!token) return;

    try {
      const response = await apiFetch(`/locations?company_id=${companyId}`, {}, token);
      if (!response.ok) throw new Error(await readError(response, "Could not load locations."));
      setLocations(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load locations.");
    }
  }

  async function loadDashboard() {
    if (!token) return;
    const response = await apiFetch("/dashboard/summary", {}, token);
    if (!response.ok) { setError(await readError(response, "Could not load dashboard.")); return; }
    setDashboard(await response.json());
  }

  async function loadPosProviders() {
    const response = await apiFetch("/integrations/pos/providers");
    if (!response.ok) throw new Error(await readError(response, "Could not load POS providers."));
    const data: POSProvider[] = await response.json();
    setPosProviders(data);
    if (data.length > 0 && !data.some((provider) => provider.provider === newIntegrationProvider)) {
      setNewIntegrationProvider(data[0].provider);
    }
  }

  async function loadIntegrations() {
    if (!token) return;
    const response = await apiFetch("/integrations/pos", {}, token);
    if (!response.ok) throw new Error(await readError(response, "Could not load POS integrations."));
    setIntegrations(await response.json());
  }

  async function createIntegration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const response = await apiFetch("/integrations/pos", {
      method: "POST",
      body: JSON.stringify({
        location_id: Number(newIntegrationLocationId),
        provider: newIntegrationProvider,
        name: newIntegrationName,
        connection_type: newIntegrationConnectionType,
        base_url: newIntegrationBaseUrl || null,
        external_account_id: newIntegrationAccountId || null,
      }),
    }, token);
    if (!response.ok) { setError(await readError(response, "Could not create POS integration.")); return; }
    setNewIntegrationName("");
    setNewIntegrationLocationId("");
    setNewIntegrationBaseUrl("");
    setNewIntegrationAccountId("");
    await loadIntegrations();
  }

  async function loadSyncRuns(id: number) {
    if (!token) return;
    const response = await apiFetch(`/integrations/pos/${id}/sync-runs`, {}, token);
    if (!response.ok) { setError(await readError(response, "Could not load sync history.")); return; }
    const data: SyncRun[] = await response.json();
    setSyncRuns((current) => ({ ...current, [id]: data }));
  }

  async function testIntegration(id: number) {
    if (!token) return;
    const response = await apiFetch(`/integrations/pos/${id}/test`, { method: "POST" }, token);
    if (!response.ok) { setError(await readError(response, "Could not test POS integration.")); return; }
    await loadIntegrations();
  }

  async function syncIntegration(id: number) {
    if (!token) return;
    const response = await apiFetch(`/integrations/pos/${id}/sync`, { method: "POST" }, token);
    if (!response.ok) { setError(await readError(response, "Could not sync POS integration.")); return; }
    const result = await response.json();
    setError(`Sync completed: ${result.fetched} fetched, ${result.imported} imported, ${result.skipped_duplicates} duplicates skipped.`);
    await loadIntegrations();
    await loadUnmatchedProducts();
  }

  async function deactivateIntegration(id: number) {
    if (!token) return;
    const response = await apiFetch(`/integrations/pos/${id}`, { method: "DELETE" }, token);
    if (!response.ok) { setError(await readError(response, "Could not deactivate POS integration.")); return; }
    await loadIntegrations();
  }

  async function loadProducts() {
    if (!token) return;
    const response = await apiFetch("/products", {}, token);
    if (!response.ok) throw new Error(await readError(response, "Could not load products."));
    setProducts(await response.json());
  }

  async function loadMappings() {
    if (!token) return;
    const response = await apiFetch("/product-mappings", {}, token);
    if (!response.ok) throw new Error(await readError(response, "Could not load product mappings."));
    setMappings(await response.json());
  }

  async function loadUomConversions() {
    if (!token) return;
    const response = await apiFetch("/product-mappings/uom-conversions", {}, token);
    if (!response.ok) throw new Error(await readError(response, "Could not load UOM conversions."));
    setUomConversions(await response.json());
  }

  async function loadUnmatchedProducts() {
    if (!token) return;
    const response = await apiFetch("/sales/unmatched-products", {}, token);
    if (!response.ok) throw new Error(await readError(response, "Could not load unmatched POS products."));
    setUnmatchedProducts(await response.json());
  }

  async function createProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const response = await apiFetch("/products", {
      method: "POST",
      body: JSON.stringify({ name: newProductName, sku: newProductSku || null, base_uom: newProductUom }),
    }, token);
    if (!response.ok) { setError(await readError(response, "Could not create product.")); return; }
    setNewProductName(""); setNewProductSku(""); setNewProductUom("EA");
    await loadProducts();
  }

  async function createMapping(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const response = await apiFetch("/product-mappings", {
      method: "POST",
      body: JSON.stringify({
        integration_id: Number(mappingIntegrationId),
        external_product_id: mappingExternalId,
        product_id: Number(mappingProductId),
      }),
    }, token);
    if (!response.ok) { setError(await readError(response, "Could not create product mapping.")); return; }
    setMappingExternalId(""); await loadMappings();
  }

  async function createConversion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const response = await apiFetch("/product-mappings/uom-conversions", {
      method: "POST",
      body: JSON.stringify({
        product_id: Number(conversionProductId),
        from_uom: conversionFromUom,
        to_uom: conversionToUom,
        factor: Number(conversionFactor),
      }),
    }, token);
    if (!response.ok) { setError(await readError(response, "Could not create UOM conversion.")); return; }
    setConversionFromUom(""); setConversionToUom(""); setConversionFactor("");
    await loadUomConversions();
  }

  async function loadUsers() {
    if (!token) return;

    try {
      const response = await apiFetch("/users", {}, token);
      if (!response.ok) throw new Error(await readError(response, "Could not load users."));
      setUsers(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load users.");
    }
  }

  useEffect(() => {
    if (token) {
      void loadMe(token);
      void loadCompanies(token);
      void loadUsers();
      void loadPosProviders();
      void loadDashboard();
      void loadIntegrations();
      void loadProducts();
      void loadMappings();
      void loadUomConversions();
      void loadUnmatchedProducts();
    }
  }, [token]);

  useEffect(() => {
    if (selectedCompanyId !== null && token) {
      void loadLocations(selectedCompanyId);
    }
  }, [selectedCompanyId, token]);

  async function handleCompanySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!token) return;

    setSaving(true);
    setError("");

    try {
      const response = await apiFetch("/companies", {
        method: "POST",
        body: JSON.stringify({
          name: companyName,
          tax_identifier: taxIdentifier || null,
          currency,
        }),
      }, token);

      if (!response.ok) throw new Error(await readError(response, "Could not create company."));

      setCompanyName("");
      setTaxIdentifier("");
      setCurrency("RON");
      await loadCompanies(token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create company.");
    } finally {
      setSaving(false);
    }
  }

  async function handleLocationSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!token || selectedCompanyId === null) {
      setError("Select a company first.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      const isEditing = editingLocationId !== null;
      const response = await apiFetch(
        isEditing ? `/locations/${editingLocationId}` : "/locations",
        {
          method: isEditing ? "PATCH" : "POST",
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
        },
        token,
      );

      if (!response.ok) throw new Error(await readError(response, "Could not save location."));

      setLocationName("");
      setAddress("");
      setCity("");
      setCountry("RO");
      setEditingLocationId(null);
      await loadLocations(selectedCompanyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save location.");
    } finally {
      setSaving(false);
    }
  }

  async function deactivateLocation(id: number) {
    if (!token || selectedCompanyId === null) return;

    try {
      const response = await apiFetch(`/locations/${id}`, { method: "DELETE" }, token);
      if (!response.ok) throw new Error(await readError(response, "Could not deactivate location."));
      await loadLocations(selectedCompanyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not deactivate location.");
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!token || !currentUser) return;

    setSaving(true);
    setError("");

    try {
      const response = await apiFetch("/users", {
        method: "POST",
        body: JSON.stringify({
          company_id: currentUser.company_id,
          email: newUserEmail,
          password: newUserPassword,
          first_name: newUserFirstName,
          last_name: newUserLastName,
          role: newUserRole,
        }),
      }, token);

      if (!response.ok) throw new Error(await readError(response, "Could not create user."));

      setNewUserEmail("");
      setNewUserPassword("");
      setNewUserFirstName("");
      setNewUserLastName("");
      setNewUserRole("employee");
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create user.");
    } finally {
      setSaving(false);
    }
  }

  async function deactivateUser(id: number) {
    if (!token) return;

    try {
      const response = await apiFetch(`/users/${id}`, { method: "DELETE" }, token);
      if (!response.ok) throw new Error(await readError(response, "Could not deactivate user."));
      await loadUsers();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not deactivate user.");
    }
  }

  if (!token || !currentUser) {
    return (
      <main className="auth-page">
        <section className="card auth-card">
          <p className="eyebrow">HoReCa Management Platform</p>
          <h1>{authMode === "login" ? "Sign in" : "Create your HoReCa company"}</h1>

          <form onSubmit={handleAuth} className="auth-form">
            {authMode === "bootstrap" && (
              <>
                <label>
                  Company name
                  <input
                    value={registerCompanyName}
                    onChange={(event) => setRegisterCompanyName(event.target.value)}
                    required
                  />
                </label>

                <label>
                  Tax identifier
                  <input
                    value={registerTaxIdentifier}
                    onChange={(event) => setRegisterTaxIdentifier(event.target.value)}
                  />
                </label>

                <label>
                  First name
                  <input
                    value={registerFirstName}
                    onChange={(event) => setRegisterFirstName(event.target.value)}
                    required
                  />
                </label>

                <label>
                  Last name
                  <input
                    value={registerLastName}
                    onChange={(event) => setRegisterLastName(event.target.value)}
                    required
                  />
                </label>
              </>
            )}

            <label>
              Email
              <input
                type="email"
                value={authEmail}
                onChange={(event) => setAuthEmail(event.target.value)}
                required
              />
            </label>

            <label>
              Password
              <input
                type="password"
                value={authPassword}
                onChange={(event) => setAuthPassword(event.target.value)}
                required
                minLength={8}
              />
            </label>

            <button type="submit" disabled={saving}>
              {saving
                ? "Please wait..."
                : authMode === "login"
                  ? "Sign in"
                  : "Create owner account"}
            </button>
          </form>

          <button
            type="button"
            className="secondary full-width"
            onClick={() => {
              setAuthMode(authMode === "login" ? "bootstrap" : "login");
              setError("");
            }}
          >
            {authMode === "login"
              ? "First user? Create the company owner account"
              : "Already have an account? Sign in"}
          </button>

          {error && <p className="error">{error}</p>}
        </section>
      </main>
    );
  }

  return (
    <main>
      <header className="topbar">
        <div>
          <p className="eyebrow">HoReCa Management Platform</p>
          <h1>Company Management</h1>
          <p className="subtitle">
            Signed in as {currentUser.first_name} {currentUser.last_name} · {currentUser.role}
          </p>
        </div>
        <button type="button" className="secondary" onClick={logout}>
          Sign out
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      {dashboard && (
        <section className="card">
          <div className="section-heading">
            <div>
              <h2>Operations Dashboard</h2>
              <p className="subtitle">Current company-level operational indicators.</p>
            </div>
            <button type="button" className="secondary" onClick={() => void loadDashboard()}>Refresh</button>
          </div>
          <div className="dashboard-grid">
            <div className="metric"><span>Orders</span><strong>{dashboard.sales_count}</strong></div>
            <div className="metric"><span>Net revenue</span><strong>{dashboard.revenue}</strong></div>
            <div className="metric"><span>Gross revenue</span><strong>{dashboard.gross_revenue}</strong></div>
            <div className="metric"><span>Average ticket</span><strong>{dashboard.average_ticket}</strong></div>
            <div className="metric"><span>Unmatched products</span><strong>{dashboard.unmatched_products}</strong></div>
            <div className="metric"><span>Stock value</span><strong>{dashboard.stock_value}</strong></div>
          </div>
        </section>
      )}

      <section className="card">
        <div className="section-heading">
          <h2>Companies</h2>
          <button type="button" className="secondary" onClick={() => void loadCompanies()}>Refresh</button>
        </div>

        {loading ? <p>Loading...</p> : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr><th>Name</th><th>Tax ID</th><th>Currency</th><th>Status</th></tr>
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
            <button type="button" className="secondary" onClick={() => void loadLocations(selectedCompanyId)}>
              Refresh
            </button>
          )}
        </div>

        {selectedCompanyId !== null && (
          <>
            <form onSubmit={handleLocationSubmit} className="form location-form">
              <label>
                Location name
                <input value={locationName} onChange={(event) => setLocationName(event.target.value)} required />
              </label>
              <label>
                Address
                <input value={address} onChange={(event) => setAddress(event.target.value)} />
              </label>
              <label>
                City
                <input value={city} onChange={(event) => setCity(event.target.value)} />
              </label>
              <label>
                Country
                <input value={country} onChange={(event) => setCountry(event.target.value.toUpperCase())} required maxLength={2} />
              </label>
              <div className="form-actions">
                <button type="submit" disabled={saving}>
                  {editingLocationId === null ? "Create location" : "Save changes"}
                </button>
                {editingLocationId !== null && (
                  <button type="button" className="secondary" onClick={() => {
                    setEditingLocationId(null);
                    setLocationName("");
                    setAddress("");
                    setCity("");
                    setCountry("RO");
                  }}>
                    Cancel
                  </button>
                )}
              </div>
            </form>

            {locations.length > 0 && (
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr><th>Name</th><th>Address</th><th>City</th><th>Country</th><th>Status</th><th /></tr>
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
                              <button type="button" className="secondary" onClick={() => {
                                setEditingLocationId(location.id);
                                setLocationName(location.name);
                                setAddress(location.address ?? "");
                                setCity(location.city ?? "");
                                setCountry(location.country);
                              }}>Edit</button>
                              <button type="button" className="danger" onClick={() => void deactivateLocation(location.id)}>
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

      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Users</h2>
            <p className="subtitle">Users belonging to your company.</p>
          </div>
          <button type="button" className="secondary" onClick={() => void loadUsers()}>Refresh</button>
        </div>

        {(currentUser.role === "owner" || currentUser.role === "manager") && (
          <form onSubmit={handleCreateUser} className="form user-form">
            <label>
              First name
              <input value={newUserFirstName} onChange={(event) => setNewUserFirstName(event.target.value)} required />
            </label>
            <label>
              Last name
              <input value={newUserLastName} onChange={(event) => setNewUserLastName(event.target.value)} required />
            </label>
            <label>
              Email
              <input type="email" value={newUserEmail} onChange={(event) => setNewUserEmail(event.target.value)} required />
            </label>
            <label>
              Password
              <input type="password" value={newUserPassword} onChange={(event) => setNewUserPassword(event.target.value)} required minLength={8} />
            </label>
            <label>
              Role
              <select value={newUserRole} onChange={(event) => setNewUserRole(event.target.value as User["role"])}>
                <option value="employee">Employee</option>
                <option value="manager">Manager</option>
                <option value="owner">Owner</option>
              </select>
            </label>
            <button type="submit" disabled={saving}>Create user</button>
          </form>
        )}

        <div className="table-wrapper">
          <table>
            <thead>
              <tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td>{user.first_name} {user.last_name}</td>
                  <td>{user.email}</td>
                  <td>{user.role}</td>
                  <td>{user.active ? "Active" : "Inactive"}</td>
                  <td className="actions">
                    {user.active && user.id !== currentUser.id && (currentUser.role === "owner" || currentUser.role === "manager") && (
                      <button type="button" className="danger" onClick={() => void deactivateUser(user.id)}>
                        Deactivate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>POS Integrations</h2>
            <p className="subtitle">Connect a POS account to a specific HoReCa location. The integration ID is now managed by the platform.</p>
          </div>
          <button type="button" className="secondary" onClick={() => void loadIntegrations()}>Refresh</button>
        </div>

        {(currentUser.role === "owner" || currentUser.role === "manager") && (
          <form onSubmit={createIntegration} className="form user-form">
            <label>Name<input value={newIntegrationName} onChange={(e) => setNewIntegrationName(e.target.value)} placeholder="Main POS" required /></label>
            <label>Provider<select value={newIntegrationProvider} onChange={(e) => setNewIntegrationProvider(e.target.value)} required><option value="">Select</option>{posProviders.map((provider) => <option key={provider.provider} value={provider.provider}>{provider.display_name}</option>)}</select></label>
            <label>Location<select value={newIntegrationLocationId} onChange={(e) => setNewIntegrationLocationId(e.target.value)} required><option value="">Select</option>{locations.filter((l) => l.active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
            <label>Connection<select value={newIntegrationConnectionType} onChange={(e) => setNewIntegrationConnectionType(e.target.value as POSIntegration["connection_type"])}><option value="api">API</option><option value="webhook">Webhook</option><option value="file">File</option></select></label>
            <label>Base URL<input value={newIntegrationBaseUrl} onChange={(e) => setNewIntegrationBaseUrl(e.target.value)} placeholder="https://..." /></label>
            <label>External Account ID<input value={newIntegrationAccountId} onChange={(e) => setNewIntegrationAccountId(e.target.value)} /></label>
            <button type="submit">Add integration</button>
          </form>
        )}

        <div className="table-wrapper">
          <table>
            <thead><tr><th>Name</th><th>Provider</th><th>Location</th><th>Connection</th><th>Status</th><th>ID</th><th /></tr></thead>
            <tbody>
              {integrations.map((integration) => (
                <tr key={integration.id}>
                  <td>{integration.name}</td>
                  <td>{integration.provider}</td>
                  <td>{locations.find((l) => l.id === integration.location_id)?.name ?? integration.location_id}</td>
                  <td>{integration.connection_type}</td>
                  <td>{integration.active ? integration.status : "inactive"}</td>
                  <td>{integration.id}</td>
                  <td className="actions">
                    {(currentUser.role === "owner" || currentUser.role === "manager") && integration.active && (
                      <>
                        <button type="button" className="secondary" onClick={() => void testIntegration(integration.id)}>Test</button>
                        <button type="button" className="secondary" onClick={() => void syncIntegration(integration.id)}>Sync</button><button type="button" className="secondary" onClick={() => void loadSyncRuns(integration.id)}>History</button>
                        <button type="button" className="danger" onClick={() => void deactivateIntegration(integration.id)}>Deactivate</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Sync History</h2>
            <p className="subtitle">Audit trail for POS synchronization runs.</p>
          </div>
        </div>
        {Object.entries(syncRuns).length === 0 ? (
          <p>Load history from a POS integration to see its synchronization runs.</p>
        ) : (
          Object.entries(syncRuns).map(([integrationId, runs]) => (
            <div key={integrationId} className="table-wrapper">
              <table>
                <thead>
                  <tr><th>Integration</th><th>Started</th><th>Status</th><th>Fetched</th><th>Imported</th><th>Duplicates</th><th>Error</th></tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id}>
                      <td>{integrations.find((i) => i.id === Number(integrationId))?.name ?? integrationId}</td>
                      <td>{new Date(run.started_at).toLocaleString()}</td>
                      <td>{run.status}</td>
                      <td>{run.fetched}</td>
                      <td>{run.imported}</td>
                      <td>{run.skipped_duplicates}</td>
                      <td>{run.error_message ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))
        )}
      </section>

      <section className="card">
        <div className="section-heading"><div><h2>Product Master</h2><p className="subtitle">Canonical products used by the platform.</p></div></div>
        {(currentUser.role === "owner" || currentUser.role === "manager") && (
          <form onSubmit={createProduct} className="form user-form">
            <label>Name<input value={newProductName} onChange={(e) => setNewProductName(e.target.value)} required /></label>
            <label>SKU<input value={newProductSku} onChange={(e) => setNewProductSku(e.target.value)} /></label>
            <label>Base UOM<input value={newProductUom} onChange={(e) => setNewProductUom(e.target.value.toUpperCase())} required /></label>
            <button type="submit">Create product</button>
          </form>
        )}
        <div className="table-wrapper"><table><thead><tr><th>Name</th><th>SKU</th><th>Base UOM</th></tr></thead>
          <tbody>{products.map((p) => <tr key={p.id}><td>{p.name}</td><td>{p.sku ?? "—"}</td><td>{p.base_uom}</td></tr>)}</tbody>
        </table></div>
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <h2>Unmatched POS Products</h2>
            <p className="subtitle">Products received from POS integrations that could not be linked to the platform product master.</p>
          </div>
          <button type="button" className="secondary" onClick={() => void loadUnmatchedProducts()}>Refresh</button>
        </div>
        {unmatchedProducts.length === 0 ? (
          <p>No unmatched POS products.</p>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr><th>POS Product</th><th>Integration</th><th>UOM</th><th>Occurrences</th><th>Total Qty</th><th /></tr>
              </thead>
              <tbody>
                {unmatchedProducts.map((item) => (
                  <tr key={item.integration_id + ":" + item.external_product_id}>
                    <td>{item.product_name} ({item.external_product_id})</td>
                    <td>{item.integration_id}</td>
                    <td>{item.uom}</td>
                    <td>{item.occurrences}</td>
                    <td>{item.total_quantity}</td>
                    <td>
                      {(currentUser.role === "owner" || currentUser.role === "manager") && (
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => {
                            setMappingIntegrationId(String(item.integration_id));
                            setMappingExternalId(item.external_product_id);
                            setError("");
                            window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
                          }}
                        >
                          Prepare mapping
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

      <section className="card">
        <div className="section-heading"><div><h2>POS Product Mapping</h2><p className="subtitle">Map an external POS product to the canonical product.</p></div></div>
        {(currentUser.role === "owner" || currentUser.role === "manager") && (
          <form onSubmit={createMapping} className="form user-form">
            <label>POS Integration<select value={mappingIntegrationId} onChange={(e) => setMappingIntegrationId(e.target.value)} required><option value="">Select</option>{integrations.filter((i) => i.active).map((i) => <option key={i.id} value={i.id}>{i.name} · {i.provider} · {locations.find((l) => l.id === i.location_id)?.name ?? i.location_id}</option>)}</select></label>
            <label>POS Product ID<input value={mappingExternalId} onChange={(e) => setMappingExternalId(e.target.value)} required /></label>
            <label>Platform Product<select value={mappingProductId} onChange={(e) => setMappingProductId(e.target.value)} required><option value="">Select</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            <button type="submit">Create mapping</button>
          </form>
        )}
        <div className="table-wrapper"><table><thead><tr><th>POS Product</th><th>Platform Product</th><th>Method</th></tr></thead>
          <tbody>{mappings.map((m) => <tr key={m.id}><td>{m.external_product_name ?? m.external_product_id}</td><td>{products.find((p) => p.id === m.product_id)?.name ?? m.product_id}</td><td>{m.match_method}</td></tr>)}</tbody>
        </table></div>
      </section>

      <section className="card">
        <div className="section-heading"><div><h2>UOM Conversions</h2><p className="subtitle">Normalize POS quantities into the product base UOM.</p></div></div>
        {(currentUser.role === "owner" || currentUser.role === "manager") && (
          <form onSubmit={createConversion} className="form user-form">
            <label>Product<select value={conversionProductId} onChange={(e) => setConversionProductId(e.target.value)} required><option value="">Select</option>{products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.base_uom})</option>)}</select></label>
            <label>From UOM<input value={conversionFromUom} onChange={(e) => setConversionFromUom(e.target.value.toUpperCase())} placeholder="CASE" required /></label>
            <label>To UOM<input value={conversionToUom} onChange={(e) => setConversionToUom(e.target.value.toUpperCase())} placeholder="EA" required /></label>
            <label>Factor<input value={conversionFactor} onChange={(e) => setConversionFactor(e.target.value)} type="number" step="0.000001" min="0.000001" required /></label>
            <button type="submit">Create conversion</button>
          </form>
        )}
        <div className="table-wrapper"><table><thead><tr><th>Product</th><th>From</th><th>To</th><th>Factor</th></tr></thead>
          <tbody>{uomConversions.map((c) => <tr key={c.id}><td>{products.find((p) => p.id === c.product_id)?.name ?? c.product_id}</td><td>{c.from_uom}</td><td>{c.to_uom}</td><td>{c.factor}</td></tr>)}</tbody>
        </table></div>
      </section>

    </main>
  );
}

export default App;
