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
              setAuthMode(authMode === "login" ? "register" : "login");
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
    </main>
  );
}

export default App;
