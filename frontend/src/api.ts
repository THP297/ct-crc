const API_BASE = import.meta.env.VITE_API_URL ?? "";
const API = API_BASE ? `${API_BASE.replace(/\/$/, "")}/api` : "/api";

// --------------- Price ---------------

export type PriceResponse = { symbol: string; price: number };
export type PriceErrorResponse = { error: string };

export async function fetchCurrentPrice(
  symbol: string
): Promise<{ symbol: string; price: number } | { error: string }> {
  const sym = symbol.trim().toUpperCase();
  if (!sym) return { error: "Symbol is required" };
  const res = await fetch(`${API}/price?symbol=${encodeURIComponent(sym)}`);
  const data = await res.json();
  if (!res.ok)
    return {
      error: (data as PriceErrorResponse).error ?? "Failed to get price",
    };
  return data as PriceResponse;
}

// --------------- Task Engine ---------------

export type TaskEngineState = {
  symbol: string;
  x0: number;
  current_x: number;
  current_pct: number;
  seeded: boolean;
  coin_qty: number;
};

export type TaskQueueItem = {
  id: number;
  symbol: string;
  direction: "UP" | "DOWN";
  target_pct: number;
  action: "BUY" | "SELL";
  note: string;
  sibling_id?: number | null;
  sell_origin?: string;
};

export type PassedTaskItem = {
  id: number;
  symbol: string;
  task_id?: number | null;
  direction: "UP" | "DOWN";
  action: "BUY" | "SELL";
  target_pct: number;
  hit_pct: number;
  hit_price: number;
  note: string;
  at: string;
  sell_origin?: string;
};

export type ClosedTaskItem = {
  id: number;
  symbol: string;
  closed_task_id: number;
  sibling_triggered_id: number;
  direction: "UP" | "DOWN";
  action: "BUY" | "SELL";
  target_pct: number;
  at_pct: number;
  at_price: number;
  reason: string;
  note: string;
  at: string;
};

export type TaskEngineInfoResponse = {
  state: TaskEngineState | null;
  up_tasks: TaskQueueItem[];
  down_tasks: TaskQueueItem[];
  passed_tasks: PassedTaskItem[];
  closed_tasks: ClosedTaskItem[];
};

export type TaskEnginePriceResponse = {
  ok?: boolean;
  error?: string;
  state?: TaskEngineState;
  delta_pct?: number;
  triggered?: TaskQueueItem[];
  spawned?: TaskQueueItem[];
  up_tasks?: TaskQueueItem[];
  down_tasks?: TaskQueueItem[];
  passed_tasks?: PassedTaskItem[];
  closed_tasks?: ClosedTaskItem[];
  message?: string;
};

export async function fetchTaskEngineSymbols(): Promise<string[]> {
  const res = await fetch(`${API}/task-engine/symbols`);
  const data = await res.json();
  return data.symbols ?? [];
}

export async function initTaskEngine(
  symbol: string,
  x0: number,
  coin_qty: number = 0
): Promise<TaskEnginePriceResponse> {
  const res = await fetch(`${API}/task-engine/init`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: symbol.trim().toUpperCase(), x0, coin_qty }),
  });
  return await res.json();
}

export async function submitTaskEnginePrice(
  symbol: string,
  price: number
): Promise<TaskEnginePriceResponse> {
  const res = await fetch(`${API}/task-engine/price`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: symbol.trim().toUpperCase(), price }),
  });
  return await res.json();
}

export async function fetchTaskEngineInfo(
  symbol: string
): Promise<TaskEngineInfoResponse> {
  const res = await fetch(
    `${API}/task-engine/info?symbol=${encodeURIComponent(
      symbol.trim().toUpperCase()
    )}`
  );
  return await res.json();
}

export type LivePrices = Record<string, number>;

export async function fetchLivePrices(): Promise<LivePrices> {
  const res = await fetch(`${API}/task-engine/live-prices`);
  return await res.json();
}

// --------------- Settings ---------------

export type SettingsItem = {
  symbol: string;
  sell_down_pct: number;
  sell_up_pct: number;
};

export async function fetchSettings(): Promise<SettingsItem[]> {
  const res = await fetch(`${API}/task-engine/settings`);
  const data = await res.json();
  return data.settings ?? [];
}

export async function saveSettings(
  symbol: string,
  sell_down_pct: number,
  sell_up_pct: number
): Promise<{ ok?: boolean; error?: string }> {
  const res = await fetch(`${API}/task-engine/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: symbol.trim().toUpperCase(),
      sell_down_pct,
      sell_up_pct,
    }),
  });
  return await res.json();
}

// --------------- Summary ---------------

export type SummaryRow = TaskQueueItem & {
  coin_qty: number;
  coins_to_trade: number;
  target_price: number;
};

export type SummarySymbol = {
  symbol: string;
  state: TaskEngineState;
  settings: SettingsItem;
  sell_down: SummaryRow[];
  buy_down: SummaryRow[];
  sell_up: SummaryRow[];
  total_sell_down_coins: number;
  total_buy_down_coins: number;
  total_sell_up_coins: number;
};

export async function fetchSummary(): Promise<SummarySymbol[]> {
  const res = await fetch(`${API}/task-engine/summary`);
  const data = await res.json();
  return data.summary ?? [];
}

// --------------- Sections ---------------

export type Section = {
  id: number;
  name: string;
  symbol: string;
  x0: number;
  coin_qty: number;
  current_x: number;
  current_pct: number;
  seeded: boolean;
};

export type SectionInfoResponse = {
  section: Section | null;
  up_tasks: TaskQueueItem[];
  down_tasks: TaskQueueItem[];
  passed_tasks: PassedTaskItem[];
  closed_tasks: ClosedTaskItem[];
};

export type CreateSectionResponse = {
  ok?: boolean;
  error?: string;
  section?: Section;
  up_tasks?: TaskQueueItem[];
  down_tasks?: TaskQueueItem[];
  nearest_prices?: ValidX0Item[];
  base_x0?: number;
  grid_step_pct?: number;
  first_section_name?: string;
};

export interface ValidX0Item {
  target_x: number;
  n: number;    // grid step index: negative = below base, positive = above
  pct: number;  // = n × grid_step_pct
}

export interface ValidX0Response {
  requires_validation: boolean;
  first_section: { id: number; name: string } | null;
  base_x0: number | null;
  grid_step_pct: number;
  sample_prices: ValidX0Item[];
}

export type PriceBroadcastResult = {
  section_id: number;
  section_name: string;
  current_pct: number;
  delta_pct: number;
  triggered: TaskQueueItem[];
  spawned: TaskQueueItem[];
};

export type PriceBroadcastResponse = {
  ok?: boolean;
  error?: string;
  symbol?: string;
  price?: number;
  sections_updated?: number;
  total_triggered?: number;
  results?: PriceBroadcastResult[];
};

export async function fetchSections(
  symbol?: string
): Promise<Section[]> {
  const url = symbol
    ? `${API}/task-engine/sections?symbol=${encodeURIComponent(symbol.trim().toUpperCase())}`
    : `${API}/task-engine/sections`;
  const res = await fetch(url);
  const data = await res.json();
  return data.sections ?? [];
}

export async function fetchValidX0(symbol: string): Promise<ValidX0Response> {
  const res = await fetch(
    `${API}/task-engine/sections/valid-x0?symbol=${encodeURIComponent(symbol.trim().toUpperCase())}`
  );
  return await res.json();
}

export async function createSection(
  symbol: string,
  name: string,
  x0: number,
  coin_qty: number = 0
): Promise<CreateSectionResponse> {
  const res = await fetch(`${API}/task-engine/sections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: symbol.trim().toUpperCase(),
      name: name.trim(),
      x0,
      coin_qty,
    }),
  });
  return await res.json();
}

export async function fetchSectionInfo(
  sectionId: number
): Promise<SectionInfoResponse> {
  const res = await fetch(`${API}/task-engine/sections/${sectionId}`);
  return await res.json();
}

export async function deleteSection(
  sectionId: number
): Promise<{ ok?: boolean; error?: string }> {
  const res = await fetch(`${API}/task-engine/sections/${sectionId}`, {
    method: "DELETE",
  });
  return await res.json();
}

export async function priceBroadcast(
  symbol: string,
  price: number
): Promise<PriceBroadcastResponse> {
  const res = await fetch(`${API}/task-engine/price-broadcast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: symbol.trim().toUpperCase(),
      price,
    }),
  });
  return await res.json();
}

export async function deleteEngine(
  symbol: string
): Promise<{ ok?: boolean; error?: string }> {
  const res = await fetch(
    `${API}/task-engine/engine/${encodeURIComponent(symbol.trim().toUpperCase())}`,
    { method: "DELETE" }
  );
  return await res.json();
}

// --------------- Price History ---------------

export type PriceHistoryItem = {
  id?: number;
  symbol: string;
  price: number;
  at: string;
};

export async function fetchPriceHistory(
  symbol: string,
  limit: number = 20
): Promise<PriceHistoryItem[]> {
  const res = await fetch(
    `${API}/task-engine/price-history?symbol=${encodeURIComponent(
      symbol.trim().toUpperCase()
    )}&limit=${limit}`
  );
  const data = await res.json();
  return data.history ?? [];
}
