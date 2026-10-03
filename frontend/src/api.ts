const API_URL = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export type Page<T> = { items: T[]; total: number };

function describe(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => (typeof entry === "string" ? entry : (entry?.msg as string | undefined) ?? JSON.stringify(entry)))
      .join("\n");
  }
  return fallback;
}

export type Api = ReturnType<typeof createApi>;

export function createApi(token: string, onUnauthorized: () => void) {
  async function request(path: string, init: RequestInit = {}, contentType: string | null = "application/json") {
    const headers = new Headers(init.headers);
    if (contentType) headers.set("Content-Type", contentType);
    headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(`${API_URL}${path}`, { ...init, headers });
    if (response.status === 401) onUnauthorized();
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(describe(body?.detail, `Request failed (${response.status})`), response.status);
    }
    return response;
  }

  const query = (params?: Record<string, string | number | boolean | null | undefined>) => {
    const search = new URLSearchParams();
    Object.entries(params ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
    });
    const text = search.toString();
    return text ? `?${text}` : "";
  };

  return {
    query,
    async get<T>(path: string, params?: Record<string, string | number | boolean | null | undefined>): Promise<T> {
      return (await request(path + query(params))).json();
    },
    async page<T>(path: string, params?: Record<string, string | number | boolean | null | undefined>): Promise<Page<T>> {
      const response = await request(path + query(params));
      const items: T[] = await response.json();
      return { items, total: Number(response.headers.get("X-Total-Count") ?? items.length) };
    },
    async post<T>(path: string, body?: unknown): Promise<T> {
      const response = await request(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
      return response.status === 204 ? (undefined as T) : response.json();
    },
    async patch<T>(path: string, body: unknown): Promise<T> {
      return (await request(path, { method: "PATCH", body: JSON.stringify(body) })).json();
    },
    async del<T>(path: string): Promise<T | undefined> {
      const response = await request(path, { method: "DELETE" });
      return response.status === 204 ? undefined : response.json();
    },
    async uploadCsv<T>(path: string, text: string): Promise<T> {
      return (await request(path, { method: "POST", body: text }, "text/csv")).json();
    },
    async download(path: string, filename: string, params?: Record<string, string | number | boolean | null | undefined>) {
      const response = await request(path + query(params), {}, null);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    },
  };
}
