export type Role = "owner" | "manager" | "employee";

export type Location = { id: number; name: string; active: boolean };
export type Product = {
  id: number;
  name: string;
  sku: string | null;
  base_uom: string;
  category?: string | null;
  reorder_level?: string | null;
  active: boolean;
};
export type Integration = {
  id: number;
  location_id: number;
  provider: string;
  name: string;
  status: string;
  active: boolean;
  connection_type: string;
  webhook_configured: boolean;
  sync_interval_minutes: number | null;
  next_sync_at: string | null;
  consecutive_failures: number;
  sync_paused_reason: string | null;
  last_synced_at: string | null;
};

export type ViewProps = {
  api: import("./api").Api;
  role: Role;
  locations: Location[];
  products: Product[];
  integrations: Integration[];
  refreshProducts: () => Promise<void>;
  refreshIntegrations: () => Promise<void>;
};

export const canManage = (role: Role) => role === "owner" || role === "manager";
