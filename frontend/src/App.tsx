import { useEffect, useState } from "react";
import {
  fetchCurrentPrice,
  fetchTaskEngineSymbols,
  initTaskEngine,
  submitTaskEnginePrice,
  fetchTaskEngineInfo,
  fetchLivePrices,
  type TaskEngineState,
  type TaskQueueItem,
  type PassedTaskItem,
  type ClosedTaskItem,
  type LivePrices,
} from "./api";
import "./App.css";

function formatPrice(price: number): string {
  return price.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function App() {
  const [page, setPage] = useState<"engine" | "price">("engine");
  const [toast, setToast] = useState(false);

  // Current price
  const [priceSymbol, setPriceSymbol] = useState("");
  const [priceResult, setPriceResult] = useState<
    { symbol: string; price: number } | { error: string } | null
  >(null);
  const [priceLoading, setPriceLoading] = useState(false);

  // Task Engine
  const [engineSymbols, setEngineSymbols] = useState<string[]>([]);
  const [engineSelectedSymbol, setEngineSelectedSymbol] = useState("");
  const [engineState, setEngineState] = useState<TaskEngineState | null>(null);
  const [engineUpTasks, setEngineUpTasks] = useState<TaskQueueItem[]>([]);
  const [engineDownTasks, setEngineDownTasks] = useState<TaskQueueItem[]>([]);
  const [enginePassedTasks, setEnginePassedTasks] = useState<PassedTaskItem[]>(
    [],
  );
  const [engineClosedTasks, setEngineClosedTasks] = useState<ClosedTaskItem[]>(
    [],
  );
  const [engineNewPrice, setEngineNewPrice] = useState("");
  const [engineInitSymbol, setEngineInitSymbol] = useState("");
  const [engineInitX0, setEngineInitX0] = useState("");
  const [engineTriggered, setEngineTriggered] = useState<TaskQueueItem[]>([]);
  const [engineMessage, setEngineMessage] = useState("");
  const [loading, setLoading] = useState(true);

  // Live prices from realtime poller
  const [livePrices, setLivePrices] = useState<LivePrices>({});

  const loadEngineSymbols = () =>
    fetchTaskEngineSymbols().then((syms) => {
      setEngineSymbols(syms);
      return syms;
    });

  const loadEngineInfo = (sym: string) => {
    if (!sym) {
      setEngineState(null);
      setEngineUpTasks([]);
      setEngineDownTasks([]);
      setEnginePassedTasks([]);
      setEngineClosedTasks([]);
      return;
    }
    fetchTaskEngineInfo(sym).then((info) => {
      setEngineState(info.state);
      setEngineUpTasks(info.up_tasks ?? []);
      setEngineDownTasks(info.down_tasks ?? []);
      setEnginePassedTasks(info.passed_tasks ?? []);
      setEngineClosedTasks(info.closed_tasks ?? []);
    });
  };

  useEffect(() => {
    loadEngineSymbols().then((syms) => {
      if (!engineSelectedSymbol && syms && syms.length > 0) {
        setEngineSelectedSymbol(syms[0]);
      }
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (page === "engine") loadEngineSymbols();
  }, [page]);

  useEffect(() => {
    if (engineSelectedSymbol) loadEngineInfo(engineSelectedSymbol);
  }, [engineSelectedSymbol]);

  // Poll live prices every 2m when on engine page
  useEffect(() => {
    if (page !== "engine") return;
    const poll = () =>
      fetchLivePrices()
        .then(setLivePrices)
        .catch(() => {});
    poll();
    const id = setInterval(poll, 120_000);
    return () => clearInterval(id);
  }, [page]);

  // Handlers
  const handleEngineInit = async () => {
    const sym = engineInitSymbol.trim().toUpperCase();
    const x0 = parseFloat(engineInitX0.replace(/,/g, "").trim());
    if (!sym || isNaN(x0) || x0 <= 0) return;
    const result = await initTaskEngine(sym, x0);
    if (result.error) {
      setEngineMessage(result.error);
    } else {
      setEngineMessage(
        `Initialized ${sym} with x0 = ${formatPrice(
          x0,
        )}. Sibling pair spawned (SELL -2% / SELL +3%).`,
      );
      setEngineInitSymbol("");
      setEngineInitX0("");
      if (result.state) setEngineState(result.state);
      setEngineUpTasks(result.up_tasks ?? []);
      setEngineDownTasks(result.down_tasks ?? []);
      setEnginePassedTasks([]);
      setEngineClosedTasks([]);
      setEngineTriggered([]);
      await loadEngineSymbols();
      setEngineSelectedSymbol(sym);
      setToast(true);
      setTimeout(() => setToast(false), 2000);
    }
  };

  const handleEngineSubmitPrice = async () => {
    if (!engineSelectedSymbol) return;
    const price = parseFloat(engineNewPrice.replace(/,/g, "").trim());
    if (isNaN(price) || price <= 0) return;
    const result = await submitTaskEnginePrice(engineSelectedSymbol, price);
    if (result.error) {
      setEngineMessage(result.error);
      setEngineTriggered([]);
    } else {
      if (result.state) setEngineState(result.state);
      setEngineUpTasks(result.up_tasks ?? []);
      setEngineDownTasks(result.down_tasks ?? []);
      setEnginePassedTasks(result.passed_tasks ?? []);
      setEngineClosedTasks(result.closed_tasks ?? []);
      setEngineTriggered(result.triggered ?? []);
      if (result.message) {
        setEngineMessage(result.message);
      } else if (result.triggered && result.triggered.length > 0) {
        const signals = result.triggered
          .map(
            (t) => `${t.action} (${t.direction} ${t.target_pct.toFixed(2)}%)`,
          )
          .join(", ");
        setEngineMessage(`Triggered: ${signals}`);
      } else {
        setEngineMessage(
          `Updated. pct = ${result.state?.current_pct?.toFixed(
            4,
          )}%, delta = ${result.delta_pct?.toFixed(4)}%`,
        );
      }
    }
    setEngineNewPrice("");
  };

  const handleGetPrice = async () => {
    const sym = priceSymbol.trim().toUpperCase();
    if (!sym) return;
    setPriceLoading(true);
    setPriceResult(null);
    try {
      const result = await fetchCurrentPrice(sym);
      setPriceResult(result);
    } finally {
      setPriceLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="app">
        <p className="sub">Loading...</p>
      </div>
    );
  }

  const navItems = [
    { id: "engine" as const, label: "Task Engine", icon: "⚙" },
    { id: "price" as const, label: "Current price", icon: "📈" },
  ];

  return (
    <div className="app">
      <aside className="sidebar">
        <h1 className="sidebar-title">CTC</h1>
        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`sidebar-item ${page === item.id ? "active" : ""}`}
              onClick={() => setPage(item.id)}
            >
              <span className="sidebar-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
      </aside>
      <main className="main-content">
        {page === "engine" && (
          <>
            <p className="sub">
              Task Engine: nhập giá mới cho symbol, hệ thống tự tính % so với
              giá gốc (x0) và trigger BUY/SELL dựa trên queue UP/DOWN.
            </p>

            {/* Init new engine */}
            <section className="card">
              <h2>Initialize Engine</h2>
              <p className="sub">
                Nhập symbol (e.g. BTCUSDT, ETHUSDT) và giá gốc (x0) để khởi tạo
                engine.
              </p>
              <div className="engine-init-form">
                <input
                  type="text"
                  placeholder="Symbol (e.g. BTCUSDT)"
                  value={engineInitSymbol}
                  onChange={(e) => setEngineInitSymbol(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Giá gốc x0 (e.g. 97000)"
                  value={engineInitX0}
                  onChange={(e) => setEngineInitX0(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleEngineInit()}
                />
                <button
                  type="button"
                  onClick={handleEngineInit}
                  disabled={!engineInitSymbol.trim() || !engineInitX0.trim()}
                >
                  Init
                </button>
              </div>
            </section>

            {/* Live prices for all engine symbols */}
            {engineSymbols.length > 0 && (
              <section className="card">
                <h2>Live Prices (Binance realtime, auto-refresh 2m)</h2>
                <div className="live-prices-grid">
                  {engineSymbols.map((sym) => {
                    const lp = livePrices[sym];
                    return (
                      <div
                        key={sym}
                        className={`live-price-card ${
                          engineSelectedSymbol === sym
                            ? "live-price-selected"
                            : ""
                        }`}
                        onClick={() => {
                          setEngineSelectedSymbol(sym);
                          setEngineTriggered([]);
                          setEngineMessage("");
                        }}
                      >
                        <span className="live-price-symbol">{sym}</span>
                        <span className="live-price-value">
                          {lp !== undefined ? formatPrice(lp) : "—"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Select symbol */}
            <section className="card">
              <h2>Select Symbol</h2>
              <div className="filter-row">
                <label htmlFor="engine-symbol">Symbol:</label>
                <select
                  id="engine-symbol"
                  value={engineSelectedSymbol}
                  onChange={(e) => {
                    setEngineSelectedSymbol(e.target.value);
                    setEngineTriggered([]);
                    setEngineMessage("");
                  }}
                >
                  <option value="">-- Select --</option>
                  {engineSymbols.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => loadEngineInfo(engineSelectedSymbol)}
                  disabled={!engineSelectedSymbol}
                >
                  Refresh
                </button>
              </div>
            </section>

            {engineSelectedSymbol && engineState && (
              <>
                {/* Engine state */}
                <section className="card">
                  <h2>Engine State: {engineState.symbol}</h2>
                  <div className="engine-state-grid">
                    <div className="engine-stat">
                      <span className="engine-stat-label">Giá gốc (x0)</span>
                      <span className="engine-stat-value">
                        {formatPrice(engineState.x0)}
                      </span>
                    </div>
                    <div className="engine-stat">
                      <span className="engine-stat-label">Giá hiện tại</span>
                      <span className="engine-stat-value">
                        {formatPrice(engineState.current_x)}
                      </span>
                    </div>
                    <div className="engine-stat">
                      <span className="engine-stat-label">% so với x0</span>
                      <span
                        className={`engine-stat-value ${
                          engineState.current_pct >= 0 ? "pct-up" : "pct-down"
                        }`}
                      >
                        {engineState.current_pct >= 0 ? "+" : ""}
                        {engineState.current_pct.toFixed(4)}%
                      </span>
                    </div>
                    <div className="engine-stat">
                      <span className="engine-stat-label">Seeded</span>
                      <span className="engine-stat-value">
                        {engineState.seeded ? "Yes" : "No"}
                      </span>
                    </div>
                    {livePrices[engineState.symbol] !== undefined && (
                      <div className="engine-stat engine-stat-live">
                        <span className="engine-stat-label">
                          Live Price (Binance)
                        </span>
                        <span className="engine-stat-value">
                          {formatPrice(livePrices[engineState.symbol])}
                        </span>
                      </div>
                    )}
                  </div>
                </section>

                {/* Input new price */}
                <section className="card">
                  <h2>Nhập giá observer mới</h2>
                  <div className="engine-price-form">
                    <input
                      type="text"
                      placeholder={`Giá mới cho ${engineSelectedSymbol}`}
                      value={engineNewPrice}
                      onChange={(e) => setEngineNewPrice(e.target.value)}
                      onKeyDown={(e) =>
                        e.key === "Enter" && handleEngineSubmitPrice()
                      }
                    />
                    <button
                      type="button"
                      onClick={handleEngineSubmitPrice}
                      disabled={!engineNewPrice.trim()}
                    >
                      Submit
                    </button>
                  </div>
                  {engineMessage && (
                    <div
                      className={`engine-message ${
                        engineTriggered.length > 0
                          ? "engine-message-trigger"
                          : ""
                      }`}
                    >
                      {engineMessage}
                    </div>
                  )}
                  {engineTriggered.length > 0 && (
                    <div className="engine-triggered-list">
                      {engineTriggered.map((t, i) => (
                        <div
                          key={`trigger-${t.id}-${i}`}
                          className={`engine-triggered-item signal-${t.action.toLowerCase()}`}
                        >
                          <strong>{t.action}</strong> — {t.direction} target{" "}
                          {t.target_pct.toFixed(4)}%
                          <span className="engine-triggered-note">
                            {t.note}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                {/* Queue UP */}
                <section className="card">
                  <h2>Queue UP (trigger khi current_pct &ge; target)</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Action</th>
                        <th>Target %</th>
                        <th>Target Price</th>
                        <th>Sibling</th>
                        <th>Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {engineUpTasks.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="empty">
                            No UP tasks
                          </td>
                        </tr>
                      ) : (
                        engineUpTasks.map((t) => (
                          <tr key={t.id}>
                            <td>{t.id}</td>
                            <td>
                              <span
                                className={`action-badge action-${t.action.toLowerCase()}`}
                              >
                                {t.action}
                              </span>
                            </td>
                            <td className="pct-up">
                              {t.target_pct >= 0 ? "+" : ""}
                              {t.target_pct.toFixed(4)}%
                            </td>
                            <td>
                              {formatPrice(
                                engineState.x0 * (1 + t.target_pct / 100),
                              )}
                            </td>
                            <td>{t.sibling_id ? `#${t.sibling_id}` : "—"}</td>
                            <td>{t.note}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </section>

                {/* Queue DOWN */}
                <section className="card">
                  <h2>Queue DOWN (trigger khi current_pct &le; target)</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Action</th>
                        <th>Target %</th>
                        <th>Target Price</th>
                        <th>Sibling</th>
                        <th>Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {engineDownTasks.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="empty">
                            No DOWN tasks
                          </td>
                        </tr>
                      ) : (
                        engineDownTasks.map((t) => (
                          <tr key={t.id}>
                            <td>{t.id}</td>
                            <td>
                              <span
                                className={`action-badge action-${t.action.toLowerCase()}`}
                              >
                                {t.action}
                              </span>
                            </td>
                            <td className="pct-down">
                              {t.target_pct >= 0 ? "+" : ""}
                              {t.target_pct.toFixed(4)}%
                            </td>
                            <td>
                              {formatPrice(
                                engineState.x0 * (1 + t.target_pct / 100),
                              )}
                            </td>
                            <td>{t.sibling_id ? `#${t.sibling_id}` : "—"}</td>
                            <td>{t.note}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </section>

                {/* Passed tasks */}
                <section className="card">
                  <h2>Passed Tasks (Triggered)</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>Action</th>
                        <th>Direction</th>
                        <th>Target %</th>
                        <th>Hit %</th>
                        <th>Hit Price</th>
                        <th>Note</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {enginePassedTasks.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="empty">
                            No passed tasks yet
                          </td>
                        </tr>
                      ) : (
                        enginePassedTasks.map((t, i) => (
                          <tr key={`passed-${t.id}-${i}`}>
                            <td>
                              <span
                                className={`action-badge action-${t.action.toLowerCase()}`}
                              >
                                {t.action}
                              </span>
                            </td>
                            <td>{t.direction}</td>
                            <td>
                              {t.target_pct >= 0 ? "+" : ""}
                              {t.target_pct.toFixed(4)}%
                            </td>
                            <td>
                              {t.hit_pct >= 0 ? "+" : ""}
                              {t.hit_pct.toFixed(4)}%
                            </td>
                            <td>{formatPrice(t.hit_price)}</td>
                            <td>{t.note}</td>
                            <td>{t.at}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </section>

                {/* Closed tasks (sibling cancelled) */}
                <section className="card">
                  <h2>Closed Tasks (Sibling Cancelled)</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>Closed #</th>
                        <th>Action</th>
                        <th>Direction</th>
                        <th>Target %</th>
                        <th>Triggered By</th>
                        <th>At %</th>
                        <th>At Price</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {engineClosedTasks.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="empty">
                            No closed tasks yet
                          </td>
                        </tr>
                      ) : (
                        engineClosedTasks.map((t, i) => (
                          <tr key={`closed-${t.id}-${i}`}>
                            <td>#{t.closed_task_id}</td>
                            <td>
                              <span
                                className={`action-badge action-${t.action.toLowerCase()}`}
                              >
                                {t.action}
                              </span>
                            </td>
                            <td>{t.direction}</td>
                            <td>
                              {t.target_pct >= 0 ? "+" : ""}
                              {t.target_pct.toFixed(4)}%
                            </td>
                            <td>#{t.sibling_triggered_id}</td>
                            <td
                              className={t.at_pct >= 0 ? "pct-up" : "pct-down"}
                            >
                              {t.at_pct >= 0 ? "+" : ""}
                              {t.at_pct.toFixed(4)}%
                            </td>
                            <td>{formatPrice(t.at_price)}</td>
                            <td>{t.at}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </section>
              </>
            )}

            {engineSelectedSymbol && !engineState && (
              <section className="card">
                <p className="sub">
                  No engine state for {engineSelectedSymbol}. Initialize it
                  first.
                </p>
              </section>
            )}
          </>
        )}

        {page === "price" && (
          <section className="card page-card">
            <h2>Current crypto price</h2>
            <p className="sub">Get live price from Binance API.</p>
            <div className="price-lookup">
              <label htmlFor="price-symbol">Symbol</label>
              <div className="price-lookup-row">
                <input
                  id="price-symbol"
                  type="text"
                  placeholder="e.g. BTCUSDT, ETHUSDT"
                  value={priceSymbol}
                  onChange={(e) => setPriceSymbol(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleGetPrice()}
                  aria-label="Symbol to look up"
                />
                <button
                  type="button"
                  onClick={handleGetPrice}
                  disabled={!priceSymbol.trim() || priceLoading}
                >
                  {priceLoading ? "Loading..." : "Get price"}
                </button>
              </div>
              {priceResult && (
                <div
                  className={
                    "price-result " +
                    ("error" in priceResult ? "price-error" : "price-ok")
                  }
                >
                  {"error" in priceResult ? (
                    priceResult.error
                  ) : (
                    <>
                      <strong>{priceResult.symbol}</strong>:{" "}
                      {formatPrice(priceResult.price)}
                    </>
                  )}
                </div>
              )}
            </div>
          </section>
        )}
      </main>

      {toast && <div className="toast">Saved.</div>}
    </div>
  );
}

export default App;
