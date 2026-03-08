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
};

export type TaskQueueItem = {
  id: number;
  symbol: string;
  direction: "UP" | "DOWN";
  target_pct: number;
  action: "BUY" | "SELL";
  note: string;
  sibling_id?: number | null;
};

export type PassedTaskItem = {
  id: number;
  symbol: string;
  direction: "UP" | "DOWN";
  action: "BUY" | "SELL";
  target_pct: number;
  hit_pct: number;
  hit_price: number;
  note: string;
  at: string;
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
  x0: number
): Promise<TaskEnginePriceResponse> {
  const res = await fetch(`${API}/task-engine/init`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: symbol.trim().toUpperCase(), x0 }),
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
