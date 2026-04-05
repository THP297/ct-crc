import { useEffect, useState } from "react";
import {
  fetchCurrentPrice,
  fetchLivePrices,
  fetchSettings,
  saveSettings,
  fetchSummary,
  fetchSections,
  createSection,
  fetchSectionInfo,
  deleteSection,
  priceBroadcast,
  deleteEngine,
  fetchPriceHistory,
  type TaskQueueItem,
  type PassedTaskItem,
  type ClosedTaskItem,
  type LivePrices,
  type SettingsItem,
  type SummarySymbol,
  type Section,
  type PriceHistoryItem,
} from "./api";
import "./App.css";

function formatPrice(price: number): string {
  return price.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function App() {
  const [page, setPage] = useState<
    "engine" | "price" | "settings" | "summary"
  >("engine");
  const [toast, setToast] = useState(false);

  // Current price
  const [priceSymbol, setPriceSymbol] = useState("");
  const [priceResult, setPriceResult] = useState<
    { symbol: string; price: number } | { error: string } | null
  >(null);
  const [priceLoading, setPriceLoading] = useState(false);

  // Sections
  const [allSections, setAllSections] = useState<Section[]>([]);
  const [engineSymbols, setEngineSymbols] = useState<string[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [selectedSectionId, setSelectedSectionId] = useState<number | null>(
    null
  );
  const [sectionUpTasks, setSectionUpTasks] = useState<TaskQueueItem[]>([]);
  const [sectionDownTasks, setSectionDownTasks] = useState<TaskQueueItem[]>([]);
  const [sectionPassedTasks, setSectionPassedTasks] = useState<
    PassedTaskItem[]
  >([]);
  const [sectionClosedTasks, setSectionClosedTasks] = useState<
    ClosedTaskItem[]
  >([]);

  // Create section form
  const [newSectionSymbol, setNewSectionSymbol] = useState("");
  const [newSectionName, setNewSectionName] = useState("");
  const [newSectionX0, setNewSectionX0] = useState("");
  const [newSectionQty, setNewSectionQty] = useState("");

  // Price broadcast
  const [broadcastPrice, setBroadcastPrice] = useState("");
  const [engineMessage, setEngineMessage] = useState("");

  const [loading, setLoading] = useState(true);

  // Live prices
  const [livePrices, setLivePrices] = useState<LivePrices>({});

  // Price history
  const [priceHistory, setPriceHistory] = useState<PriceHistoryItem[]>([]);

  // Settings
  const [settingsList, setSettingsList] = useState<SettingsItem[]>([]);
  const [settingsEdits, setSettingsEdits] = useState<
    Record<string, { sell_down_pct: string; sell_up_pct: string }>
  >({});
  const [settingsMessage, setSettingsMessage] = useState("");

  // Summary
  const [summaryData, setSummaryData] = useState<SummarySymbol[]>([]);

  const loadAllSections = async () => {
    const secs = await fetchSections();
    setAllSections(secs);
    const syms = [...new Set(secs.map((s) => s.symbol))].sort();
    setEngineSymbols(syms);
    return { secs, syms };
  };

  const loadSectionInfo = (sectionId: number | null) => {
    if (!sectionId) {
      setSectionUpTasks([]);
      setSectionDownTasks([]);
      setSectionPassedTasks([]);
      setSectionClosedTasks([]);
      return;
    }
    fetchSectionInfo(sectionId).then((info) => {
      setSectionUpTasks(info.up_tasks ?? []);
      setSectionDownTasks(info.down_tasks ?? []);
      setSectionPassedTasks(info.passed_tasks ?? []);
      setSectionClosedTasks(info.closed_tasks ?? []);
    });
  };


  useEffect(() => {
    loadAllSections().then(({ secs, syms }) => {
      if (!selectedSymbol && syms.length > 0) {
        setSelectedSymbol(syms[0]);
        const first = secs.find((s) => s.symbol === syms[0]);
        if (first) setSelectedSectionId(first.id);
      }
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (page === "engine") loadAllSections();
  }, [page]);

  useEffect(() => {
    if (selectedSectionId) {
      loadSectionInfo(selectedSectionId);
      const sec = allSections.find((s) => s.id === selectedSectionId);
      if (sec) {
        fetchPriceHistory(sec.symbol, 15).then(setPriceHistory);
      }
    }
  }, [selectedSectionId]);

  // Poll live prices
  useEffect(() => {
    if (page !== "engine") return;
    const poll = () =>
      fetchLivePrices()
        .then(setLivePrices)
        .catch(() => {});
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, [page]);

  // Settings
  useEffect(() => {
    if (page !== "settings") return;
    fetchSettings().then((items) => {
      setSettingsList(items);
      const edits: Record<
        string,
        { sell_down_pct: string; sell_up_pct: string }
      > = {};
      for (const s of items) {
        edits[s.symbol] = {
          sell_down_pct: String(s.sell_down_pct),
          sell_up_pct: String(s.sell_up_pct),
        };
      }
      setSettingsEdits(edits);
    });
  }, [page]);

  // Summary
  useEffect(() => {
    if (page !== "summary") return;
    fetchSummary().then(setSummaryData);
  }, [page]);

  const selectedSection = allSections.find(
    (s) => s.id === selectedSectionId
  );
  const symbolSections = allSections.filter(
    (s) => s.symbol === selectedSymbol
  );

  // Handlers
  const handleCreateSection = async () => {
    const sym = newSectionSymbol.trim().toUpperCase();
    const name = newSectionName.trim();
    const x0 = parseFloat(newSectionX0.replace(/,/g, "").trim());
    if (!sym || !name || isNaN(x0) || x0 <= 0) return;
    const qty = parseFloat(newSectionQty.replace(/,/g, "").trim()) || 0;
    const result = await createSection(sym, name, x0, qty);
    if (result.error) {
      setEngineMessage(result.error);
    } else {
      setEngineMessage(
        `Created section "${name}" for ${sym} with x0=${formatPrice(x0)}, qty=${qty}`
      );
      setNewSectionSymbol("");
      setNewSectionName("");
      setNewSectionX0("");
      setNewSectionQty("");
      await loadAllSections();
      setSelectedSymbol(sym);
      if (result.section) setSelectedSectionId(result.section.id);
      setToast(true);
      setTimeout(() => setToast(false), 2000);
    }
  };

  const handleDeleteSection = async (secId: number) => {
    if (!confirm("Delete this section and all its tasks?")) return;
    const result = await deleteSection(secId);
    if (result.error) {
      setEngineMessage(result.error);
    } else {
      setEngineMessage("Section deleted.");
      const { secs: updatedSecs } = await loadAllSections();
      if (selectedSectionId === secId) {
        const next = updatedSecs.find((s) => s.symbol === selectedSymbol);
        setSelectedSectionId(next ? next.id : null);
      }
    }
  };

  const handleDeleteEngine = async (sym: string) => {
    if (
      !confirm(
        `Delete ALL data for ${sym}? (sections, tasks, settings, history)`
      )
    )
      return;
    await deleteEngine(sym);
    setEngineMessage(`${sym} deleted.`);
    const { secs: remaining, syms: remainingSyms } = await loadAllSections();
    if (selectedSymbol === sym) {
      setSelectedSymbol(remainingSyms[0] || "");
      setSelectedSectionId(remaining[0]?.id ?? null);
    }
  };

  const handlePriceBroadcast = async () => {
    if (!selectedSymbol) return;
    const price = parseFloat(broadcastPrice.replace(/,/g, "").trim());
    if (isNaN(price) || price <= 0) return;
    const result = await priceBroadcast(selectedSymbol, price);
    if (result.error) {
      setEngineMessage(result.error);
    } else {
      const n = result.sections_updated ?? 0;
      const t = result.total_triggered ?? 0;
      setEngineMessage(
        `Updated ${n} section(s) for ${selectedSymbol} @ ${formatPrice(price)}. ${t} task(s) triggered.`
      );
      await loadAllSections();
      if (selectedSectionId) loadSectionInfo(selectedSectionId);
      fetchPriceHistory(selectedSymbol, 15).then(setPriceHistory);
    }
    setBroadcastPrice("");
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
    { id: "summary" as const, label: "Summary", icon: "📊" },
    { id: "settings" as const, label: "Settings", icon: "🔧" },
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
              Task Engine: tạo section cho mỗi lần mua coin. Mỗi section có x0,
              coin_qty riêng. Cập nhật giá sẽ broadcast tới tất cả section
              cùng symbol.
            </p>

            {/* Create section */}
            <section className="card">
              <h2>Create Section</h2>
              <p className="sub">
                Mỗi lần mua coin ở giá khác nhau = 1 section. Nhập symbol, tên,
                giá mua (x0), số lượng coin.
              </p>
              <div className="engine-init-form">
                <input
                  type="text"
                  placeholder="Symbol (e.g. ETHUSDT)"
                  value={newSectionSymbol}
                  onChange={(e) => setNewSectionSymbol(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Tên section (e.g. S1)"
                  value={newSectionName}
                  onChange={(e) => setNewSectionName(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Giá mua x0"
                  value={newSectionX0}
                  onChange={(e) => setNewSectionX0(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Số lượng coin"
                  value={newSectionQty}
                  onChange={(e) => setNewSectionQty(e.target.value)}
                  onKeyDown={(e) =>
                    e.key === "Enter" && handleCreateSection()
                  }
                />
                <button
                  type="button"
                  onClick={handleCreateSection}
                  disabled={
                    !newSectionSymbol.trim() ||
                    !newSectionName.trim() ||
                    !newSectionX0.trim()
                  }
                >
                  Create
                </button>
              </div>
            </section>

            {/* Live prices */}
            {engineSymbols.length > 0 && (
              <section className="card">
                <h2>Live Prices (auto-refresh 30s)</h2>
                <div className="live-prices-grid">
                  {engineSymbols.map((sym) => {
                    const lp = livePrices[sym];
                    return (
                      <div
                        key={sym}
                        className={`live-price-card ${selectedSymbol === sym ? "live-price-selected" : ""}`}
                        onClick={() => {
                          setSelectedSymbol(sym);
                          const first = allSections.find(
                            (s) => s.symbol === sym
                          );
                          setSelectedSectionId(first?.id ?? null);
                          setEngineMessage("");
                        }}
                      >
                        <span className="live-price-symbol">{sym}</span>
                        <span className="live-price-value">
                          {lp !== undefined ? formatPrice(lp) : "—"}
                        </span>
                        <span className="live-price-sections">
                          {allSections.filter((s) => s.symbol === sym).length}{" "}
                          section(s)
                        </span>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Symbol & sections selector */}
            {selectedSymbol && (
              <section className="card">
                <div className="section-header-row">
                  <h2>
                    {selectedSymbol} — Sections ({symbolSections.length})
                  </h2>
                  <button
                    type="button"
                    className="btn-danger btn-sm"
                    onClick={() => handleDeleteEngine(selectedSymbol)}
                  >
                    Delete {selectedSymbol}
                  </button>
                </div>
                <div className="sections-grid">
                  {symbolSections.map((sec) => (
                    <div
                      key={sec.id}
                      className={`section-card ${selectedSectionId === sec.id ? "section-selected" : ""}`}
                      onClick={() => setSelectedSectionId(sec.id)}
                    >
                      <div className="section-card-header">
                        <strong>{sec.name}</strong>
                        <button
                          type="button"
                          className="btn-danger btn-xs"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteSection(sec.id);
                          }}
                        >
                          ×
                        </button>
                      </div>
                      <div className="section-card-stats">
                        <span>x0: {formatPrice(sec.x0)}</span>
                        <span>
                          now: {formatPrice(sec.current_x)}
                        </span>
                        <span
                          className={
                            sec.current_pct >= 0 ? "pct-up" : "pct-down"
                          }
                        >
                          {sec.current_pct >= 0 ? "+" : ""}
                          {sec.current_pct.toFixed(4)}%
                        </span>
                        <span>qty: {sec.coin_qty}</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Price broadcast */}
                <div className="engine-price-form" style={{ marginTop: "1rem" }}>
                  <input
                    type="text"
                    placeholder={`Giá mới cho ${selectedSymbol} (broadcast)`}
                    value={broadcastPrice}
                    onChange={(e) => setBroadcastPrice(e.target.value)}
                    onKeyDown={(e) =>
                      e.key === "Enter" && handlePriceBroadcast()
                    }
                  />
                  <button
                    type="button"
                    onClick={handlePriceBroadcast}
                    disabled={!broadcastPrice.trim()}
                  >
                    Broadcast
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      loadAllSections();
                      if (selectedSectionId)
                        loadSectionInfo(selectedSectionId);
                    }}
                    style={{ background: "var(--accent-alt)" }}
                  >
                    Refresh
                  </button>
                </div>
                {engineMessage && (
                  <div className="engine-message">{engineMessage}</div>
                )}
              </section>
            )}

            {/* Price history */}
            {selectedSymbol && priceHistory.length > 0 && (
              <section className="card">
                <h2>Price History — {selectedSymbol} (last {priceHistory.length})</h2>
                <table>
                  <thead>
                    <tr>
                      <th>Price</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {priceHistory.map((h, i) => (
                      <tr key={`ph-${i}`}>
                        <td>{formatPrice(h.price)}</td>
                        <td>{h.at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}

            {/* Selected section detail */}
            {selectedSection && (
              <>
                <section className="card">
                  <h2>
                    Section: {selectedSection.name} [{selectedSection.symbol}]
                  </h2>
                  <div className="engine-state-grid">
                    <div className="engine-stat">
                      <span className="engine-stat-label">Giá gốc (x0)</span>
                      <span className="engine-stat-value">
                        {formatPrice(selectedSection.x0)}
                      </span>
                    </div>
                    <div className="engine-stat">
                      <span className="engine-stat-label">Giá hiện tại</span>
                      <span className="engine-stat-value">
                        {formatPrice(selectedSection.current_x)}
                      </span>
                    </div>
                    <div className="engine-stat">
                      <span className="engine-stat-label">% so với x0</span>
                      <span
                        className={`engine-stat-value ${selectedSection.current_pct >= 0 ? "pct-up" : "pct-down"}`}
                      >
                        {selectedSection.current_pct >= 0 ? "+" : ""}
                        {selectedSection.current_pct.toFixed(4)}%
                      </span>
                    </div>
                    <div className="engine-stat">
                      <span className="engine-stat-label">Coin Qty</span>
                      <span className="engine-stat-value">
                        {selectedSection.coin_qty}
                      </span>
                    </div>
                    {livePrices[selectedSection.symbol] !== undefined && (
                      <div className="engine-stat engine-stat-live">
                        <span className="engine-stat-label">
                          Live (Binance)
                        </span>
                        <span className="engine-stat-value">
                          {formatPrice(livePrices[selectedSection.symbol])}
                        </span>
                      </div>
                    )}
                  </div>
                </section>

                {/* Queue UP */}
                <section className="card">
                  <h2>Queue UP (trigger khi pct &ge; target)</h2>
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
                      {sectionUpTasks.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="empty">
                            No UP tasks
                          </td>
                        </tr>
                      ) : (
                        sectionUpTasks.map((t) => (
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
                                selectedSection.x0 *
                                  (1 + t.target_pct / 100)
                              )}
                            </td>
                            <td>
                              {t.sibling_id ? `#${t.sibling_id}` : "—"}
                            </td>
                            <td>{t.note}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </section>

                {/* Queue DOWN */}
                <section className="card">
                  <h2>Queue DOWN (trigger khi pct &le; target)</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Action</th>
                        <th>Target %</th>
                        <th>Target Price</th>
                        <th>Sibling</th>
                        <th>Origin</th>
                        <th>Note</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sectionDownTasks.length === 0 ? (
                        <tr>
                          <td colSpan={7} className="empty">
                            No DOWN tasks
                          </td>
                        </tr>
                      ) : (
                        sectionDownTasks.map((t) => (
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
                                selectedSection.x0 *
                                  (1 + t.target_pct / 100)
                              )}
                            </td>
                            <td>
                              {t.sibling_id ? `#${t.sibling_id}` : "—"}
                            </td>
                            <td>{t.sell_origin || "—"}</td>
                            <td>{t.note}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </section>

                {/* Passed */}
                <section className="card">
                  <h2>Passed Tasks (Triggered)</h2>
                  <table>
                    <thead>
                      <tr>
                        <th>Task #</th>
                        <th>Action</th>
                        <th>Direction</th>
                        <th>Target %</th>
                        <th>Hit %</th>
                        <th>Hit Price</th>
                        <th>Origin</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sectionPassedTasks.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="empty">
                            No passed tasks yet
                          </td>
                        </tr>
                      ) : (
                        sectionPassedTasks.map((t, i) => (
                          <tr key={`passed-${t.id}-${i}`}>
                            <td>#{t.task_id ?? "?"}</td>
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
                            <td>{t.sell_origin || "—"}</td>
                            <td>{t.at}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </section>

                {/* Closed */}
                <section className="card">
                  <h2>Closed Tasks (Cancelled)</h2>
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
                      {sectionClosedTasks.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="empty">
                            No closed tasks yet
                          </td>
                        </tr>
                      ) : (
                        sectionClosedTasks.map((t, i) => (
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
                              className={
                                t.at_pct >= 0 ? "pct-up" : "pct-down"
                              }
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

            {selectedSymbol && symbolSections.length === 0 && (
              <section className="card">
                <p className="sub">
                  No sections for {selectedSymbol}. Create one above.
                </p>
              </section>
            )}
          </>
        )}

        {page === "settings" && (
          <>
            <p className="sub">
              Cấu hình % bán coin cho mỗi symbol. SELL DOWN % và SELL UP %
              quyết định số lượng coin sẽ bán khi task trigger.
            </p>
            <section className="card">
              <h2>Settings (per-symbol)</h2>
              {settingsMessage && (
                <div className="engine-message">{settingsMessage}</div>
              )}
              {settingsList.length === 0 ? (
                <p className="sub">
                  Chưa có symbol nào. Tạo section trước để tạo settings.
                </p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>SELL DOWN %</th>
                      <th>SELL UP %</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {settingsList.map((s) => {
                      const edit = settingsEdits[s.symbol] || {
                        sell_down_pct: String(s.sell_down_pct),
                        sell_up_pct: String(s.sell_up_pct),
                      };
                      return (
                        <tr key={s.symbol}>
                          <td>
                            <strong>{s.symbol}</strong>
                          </td>
                          <td>
                            <input
                              type="text"
                              value={edit.sell_down_pct}
                              onChange={(e) =>
                                setSettingsEdits((prev) => ({
                                  ...prev,
                                  [s.symbol]: {
                                    ...edit,
                                    sell_down_pct: e.target.value,
                                  },
                                }))
                              }
                              style={{ width: "80px" }}
                            />
                          </td>
                          <td>
                            <input
                              type="text"
                              value={edit.sell_up_pct}
                              onChange={(e) =>
                                setSettingsEdits((prev) => ({
                                  ...prev,
                                  [s.symbol]: {
                                    ...edit,
                                    sell_up_pct: e.target.value,
                                  },
                                }))
                              }
                              style={{ width: "80px" }}
                            />
                          </td>
                          <td>
                            <button
                              type="button"
                              onClick={async () => {
                                const down = parseFloat(edit.sell_down_pct);
                                const up = parseFloat(edit.sell_up_pct);
                                if (
                                  isNaN(down) ||
                                  isNaN(up) ||
                                  down <= 0 ||
                                  down > 100 ||
                                  up <= 0 ||
                                  up > 100
                                ) {
                                  setSettingsMessage(
                                    "Values must be between 0 and 100"
                                  );
                                  return;
                                }
                                const res = await saveSettings(
                                  s.symbol,
                                  down,
                                  up
                                );
                                if (res.error) {
                                  setSettingsMessage(res.error);
                                } else {
                                  setSettingsMessage(
                                    `Saved ${s.symbol}: SELL DOWN=${down}%, SELL UP=${up}%`
                                  );
                                  fetchSettings().then(setSettingsList);
                                  setToast(true);
                                  setTimeout(() => setToast(false), 2000);
                                }
                              }}
                            >
                              Save
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>
          </>
        )}

        {page === "summary" && (
          <>
            <p className="sub">
              Tổng hợp action sắp tới (pending) cho tất cả symbol, chia theo
              SELL DOWN / BUY DOWN / SELL UP, kèm số lượng coin và tên
              section.
            </p>
            <div className="summary-actions">
              <button
                type="button"
                onClick={() => fetchSummary().then(setSummaryData)}
              >
                Refresh
              </button>
            </div>
            {summaryData.length === 0 ? (
              <section className="card">
                <p className="sub">Chưa có section nào được tạo.</p>
              </section>
            ) : (
              summaryData.map((sym) => (
                <section
                  className="card summary-coin-card"
                  key={sym.symbol}
                >
                  <h2>
                    {sym.symbol} — SELL DOWN:{" "}
                    {sym.settings.sell_down_pct}% | SELL UP:{" "}
                    {sym.settings.sell_up_pct}%
                  </h2>

                  {/* SELL DOWN */}
                  <h3 className="summary-section-title">SELL DOWN</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Section</th>
                        <th>#</th>
                        <th>Target %</th>
                        <th>Target Price</th>
                        <th>Coins</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sym.sell_down.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="empty">
                            (none)
                          </td>
                        </tr>
                      ) : (
                        <>
                          {sym.sell_down.map((r: any) => (
                            <tr key={r.id}>
                              <td>{r.section_name}</td>
                              <td>{r.id}</td>
                              <td className="pct-down">
                                {r.target_pct >= 0 ? "+" : ""}
                                {r.target_pct.toFixed(4)}%
                              </td>
                              <td>{formatPrice(r.target_price)}</td>
                              <td>{r.coins_to_trade.toFixed(4)}</td>
                            </tr>
                          ))}
                          <tr className="summary-total-row">
                            <td colSpan={4}>
                              <strong>Total coins to sell</strong>
                            </td>
                            <td>
                              <strong>
                                {sym.total_sell_down_coins.toFixed(4)}
                              </strong>
                            </td>
                          </tr>
                        </>
                      )}
                    </tbody>
                  </table>

                  {/* BUY DOWN */}
                  <h3 className="summary-section-title">BUY DOWN</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Section</th>
                        <th>#</th>
                        <th>Target %</th>
                        <th>Target Price</th>
                        <th>Coins</th>
                        <th>Origin</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sym.buy_down.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="empty">
                            (none)
                          </td>
                        </tr>
                      ) : (
                        <>
                          {sym.buy_down.map((r: any) => (
                            <tr key={r.id}>
                              <td>{r.section_name}</td>
                              <td>{r.id}</td>
                              <td className="pct-down">
                                {r.target_pct >= 0 ? "+" : ""}
                                {r.target_pct.toFixed(4)}%
                              </td>
                              <td>{formatPrice(r.target_price)}</td>
                              <td>{r.coins_to_trade.toFixed(4)}</td>
                              <td>{r.sell_origin || "—"}</td>
                            </tr>
                          ))}
                          <tr className="summary-total-row">
                            <td colSpan={4}>
                              <strong>Total coins to buy</strong>
                            </td>
                            <td>
                              <strong>
                                {sym.total_buy_down_coins.toFixed(4)}
                              </strong>
                            </td>
                            <td></td>
                          </tr>
                        </>
                      )}
                    </tbody>
                  </table>

                  {/* SELL UP */}
                  <h3 className="summary-section-title">SELL UP</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>Section</th>
                        <th>#</th>
                        <th>Target %</th>
                        <th>Target Price</th>
                        <th>Coins</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sym.sell_up.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="empty">
                            (none)
                          </td>
                        </tr>
                      ) : (
                        <>
                          {sym.sell_up.map((r: any) => (
                            <tr key={r.id}>
                              <td>{r.section_name}</td>
                              <td>{r.id}</td>
                              <td className="pct-up">
                                {r.target_pct >= 0 ? "+" : ""}
                                {r.target_pct.toFixed(4)}%
                              </td>
                              <td>{formatPrice(r.target_price)}</td>
                              <td>{r.coins_to_trade.toFixed(4)}</td>
                            </tr>
                          ))}
                          <tr className="summary-total-row">
                            <td colSpan={4}>
                              <strong>Total coins to sell</strong>
                            </td>
                            <td>
                              <strong>
                                {sym.total_sell_up_coins.toFixed(4)}
                              </strong>
                            </td>
                          </tr>
                        </>
                      )}
                    </tbody>
                  </table>
                </section>
              ))
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
