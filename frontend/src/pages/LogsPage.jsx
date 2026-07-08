import React, { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "../context/AuthContext";
import {
  Terminal, RefreshCw, Search, Play, Pause, Trash2,
  Download, Clock, AlertCircle, Info, AlertTriangle, Bug, Zap,
  Radio, Database, X
} from "lucide-react";

// ─── Constants ────────────────────────────────────────────────────────────────
const LOG_LEVEL_CONFIG = {
  INFO:     { color: "#3b82f6", bg: "rgba(59,130,246,0.12)",    icon: <Info size={11} /> },
  DEBUG:    { color: "#8b5cf6", bg: "rgba(139,92,246,0.12)",    icon: <Bug size={11} /> },
  WARNING:  { color: "#f59e0b", bg: "rgba(245,158,11,0.12)",    icon: <AlertTriangle size={11} /> },
  WARN:     { color: "#f59e0b", bg: "rgba(245,158,11,0.12)",    icon: <AlertTriangle size={11} /> },
  ERROR:    { color: "#ef4444", bg: "rgba(239,68,68,0.12)",     icon: <AlertCircle size={11} /> },
  CRITICAL: { color: "#ec4899", bg: "rgba(236,72,153,0.12)",    icon: <Zap size={11} /> },
};

const TIME_PRESETS = [
  { label: "30s",   value: "30s" },
  { label: "1m",    value: "1m" },
  { label: "5m",    value: "5m" },
  { label: "10m",   value: "10m" },
  { label: "30m",   value: "30m" },
  { label: "1h",    value: "1h" },
  { label: "3h",    value: "3h" },
  { label: "6h",    value: "6h" },
  { label: "12h",   value: "12h" },
  { label: "24h",   value: "24h" },
];

const LOG_LEVELS = ["All", "INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"];

// ─── Level Badge ──────────────────────────────────────────────────────────────
const LevelBadge = ({ level }) => {
  const cfg = LOG_LEVEL_CONFIG[level?.toUpperCase()] || LOG_LEVEL_CONFIG.INFO;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "3px",
      fontSize: "0.68rem", fontWeight: 700, padding: "1px 6px",
      borderRadius: "4px", letterSpacing: "0.05em",
      color: cfg.color, backgroundColor: cfg.bg,
      border: `1px solid ${cfg.color}30`, whiteSpace: "nowrap"
    }}>
      {cfg.icon}{level?.toUpperCase() || "INFO"}
    </span>
  );
};

// ─── Log Row (shared between Live and History) ────────────────────────────────
const LogRow = ({ log, striped }) => (
  <div style={{
    display: "grid",
    gridTemplateColumns: "140px 110px 100px 90px 1fr",
    gap: "0.5rem",
    padding: "6px 12px",
    fontSize: "0.75rem",
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
    backgroundColor: striped ? "var(--bg-hover)" : "transparent",
    borderBottom: "1px solid var(--border)",
    alignItems: "center",
    transition: "background 0.1s",
  }}
  onMouseEnter={e => e.currentTarget.style.backgroundColor = "var(--bg-hover)"}
  onMouseLeave={e => e.currentTarget.style.backgroundColor = striped ? "var(--bg-hover)" : "transparent"}
  >
    <span style={{ color: "var(--text-muted)", userSelect: "none" }}>
      {new Date(log.timestamp).toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })}
    </span>
    <span style={{
      color: "var(--primary)", maxWidth: "110px", overflow: "hidden",
      textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500
    }} title={log.machine_name}>{log.machine_name || "—"}</span>
    <span style={{
      color: "var(--info)", maxWidth: "100px", overflow: "hidden",
      textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500
    }} title={log.service_name}>{log.service_name || "—"}</span>
    <LevelBadge level={log.log_level} />
    <span style={{
      color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis",
      whiteSpace: "nowrap"
    }} title={log.message}>{log.message}</span>
  </div>
);

// ─── Column Headers ───────────────────────────────────────────────────────────
const TableHeader = () => (
  <div style={{
    display: "grid",
    gridTemplateColumns: "140px 110px 100px 90px 1fr",
    gap: "0.5rem", padding: "8px 12px",
    fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.08em",
    color: "var(--text-muted)", textTransform: "uppercase",
    borderBottom: "1px solid var(--border)",
    backgroundColor: "var(--bg-surface)",
    position: "sticky", top: 0, zIndex: 1
  }}>
    <span>Timestamp</span>
    <span>Machine</span>
    <span>Service</span>
    <span>Level</span>
    <span>Message</span>
  </div>
);

// ─── Main Logs Page ───────────────────────────────────────────────────────────
const LogsPage = () => {
  const { authFetch } = useAuth();

  // ── Live Logs state ──────────────────────────────────────────────────────
  const [liveLogs, setLiveLogs] = useState([]);
  const [liveSearch, setLiveSearch] = useState("");
  const [liveLevel, setLiveLevel] = useState("All");
  const [liveService, setLiveService] = useState("All");
  const [autoScroll, setAutoScroll] = useState(true);
  const [wsStatus, setWsStatus] = useState("connecting"); // connecting | connected | disconnected
  const liveContainerRef = useRef(null);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const MAX_LIVE_LOGS = 2000;

  // ── History state ────────────────────────────────────────────────────────
  const [histLogs, setHistLogs] = useState([]);
  const [histLoading, setHistLoading] = useState(false);
  const [histTotal, setHistTotal] = useState(0);
  const [histPage, setHistPage] = useState(1);
  const HIST_LIMIT = 100;

  const [histMachine, setHistMachine]   = useState("All");
  const [histService, setHistService]   = useState("All");
  const [histLevel,   setHistLevel]     = useState("All");
  const [histSearch,  setHistSearch]    = useState("");
  const [histPreset,  setHistPreset]    = useState("1h");
  const [histStartTime, setHistStartTime] = useState("");
  const [histEndTime,   setHistEndTime]   = useState("");

  const [machines, setMachines] = useState([]);
  const [services, setServices] = useState([]);

  const [activeSection, setActiveSection] = useState("live"); // live | history

  // ── WebSocket connection ─────────────────────────────────────────────────
  const connectWs = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
    }

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const host = window.location.host;
    const wsUrl = `${protocol}://${host}/api/v1/logs/live`;

    setWsStatus("connecting");

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsStatus("connected");
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const incoming = JSON.parse(event.data);
        if (Array.isArray(incoming)) {
          setLiveLogs(prev => {
            const next = [...prev, ...incoming];
            return next.slice(-MAX_LIVE_LOGS);
          });
        }
      } catch (_) {}
    };

    ws.onerror = () => {
      setWsStatus("disconnected");
    };

    ws.onclose = () => {
      setWsStatus("disconnected");
      reconnectTimer.current = setTimeout(connectWs, 3000);
    };
  }, []);

  useEffect(() => {
    connectWs();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connectWs]);

  // ── Auto-scroll live logs ────────────────────────────────────────────────
  useEffect(() => {
    if (autoScroll && liveContainerRef.current) {
      liveContainerRef.current.scrollTop = liveContainerRef.current.scrollHeight;
    }
  }, [liveLogs, autoScroll]);

  // ── Fetch metadata ───────────────────────────────────────────────────────
  useEffect(() => {
    const loadMeta = async () => {
      try {
        const [mRes, sRes] = await Promise.all([
          authFetch("/logs/machines"),
          authFetch("/logs/services"),
        ]);
        if (mRes.ok) {
          const d = await mRes.json();
          setMachines(d.machines || []);
        }
        if (sRes.ok) {
          const d = await sRes.json();
          setServices(d.services || []);
        }
      } catch (_) {}
    };
    loadMeta();
  }, []);

  // ── History query ────────────────────────────────────────────────────────
  const fetchHistory = useCallback(async (page = 1) => {
    setHistLoading(true);
    try {
      const params = new URLSearchParams();
      if (histMachine !== "All") params.set("machine_name", histMachine);
      if (histService !== "All") params.set("service_name", histService);
      if (histLevel   !== "All") params.set("log_level",    histLevel);
      if (histSearch)             params.set("search",       histSearch);
      if (histPreset !== "Custom") params.set("time_preset", histPreset);
      else {
        if (histStartTime) params.set("start_time", histStartTime);
        if (histEndTime)   params.set("end_time",   histEndTime);
      }
      params.set("page", page);
      params.set("limit", HIST_LIMIT);

      const res = await authFetch(`/logs/history?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setHistLogs(data.logs || []);
        setHistTotal(data.total || 0);
        setHistPage(page);
      }
    } catch (_) {}
    setHistLoading(false);
  }, [histMachine, histService, histLevel, histSearch, histPreset, histStartTime, histEndTime, authFetch]);

  useEffect(() => {
    if (activeSection === "history") fetchHistory(1);
  }, [activeSection, histMachine, histService, histLevel, histPreset]);

  // ── Filtered live logs ───────────────────────────────────────────────────
  const filteredLive = liveLogs.filter(l => {
    const matchLevel   = liveLevel === "All" || (l.log_level || "").toUpperCase() === liveLevel;
    const matchService = liveService === "All" || (l.service_name || "") === liveService;
    const matchSearch  = !liveSearch || (l.message || "").toLowerCase().includes(liveSearch.toLowerCase());
    return matchLevel && matchService && matchSearch;
  });

  const downloadLive = () => {
    const content = filteredLive.map(l =>
      `${l.timestamp}  [${l.machine_name}]  [${l.service_name}]  ${l.log_level}  ${l.message}`
    ).join("\n");
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `hexamonitor-logs-${Date.now()}.log`; a.click();
    URL.revokeObjectURL(url);
  };

  const statusColor = wsStatus === "connected" ? "var(--success)"
    : wsStatus === "connecting" ? "var(--warning)" : "var(--danger)";

  return (
    <div className="page-container fade-in" style={{ display: "flex", flexDirection: "column", gap: 0, height: "calc(100vh - 64px)", overflow: "hidden" }}>

      {/* ── Page Header ─────────────────────────────────────────────────── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <Terminal size={20} color="var(--primary)" />
          <h1 style={{ fontSize: "1.3rem", fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>Logs Console</h1>
          <span style={{ fontSize: "0.75rem", color: statusColor, display: "flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: statusColor, display: "inline-block", boxShadow: wsStatus === "connected" ? `0 0 6px ${statusColor}` : "none" }} />
            {wsStatus === "connected" ? "Live" : wsStatus === "connecting" ? "Connecting…" : "Disconnected — retrying"}
          </span>
        </div>
        {/* Section tabs */}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            style={{ padding: "6px 18px", borderRadius: "6px", fontSize: "0.8rem", fontWeight: 600, border: "none", cursor: "pointer", transition: "all 0.2s",
              backgroundColor: activeSection === "live" ? "var(--primary)" : "var(--bg-hover)",
              color: activeSection === "live" ? "white" : "var(--text-secondary)" }}
            onClick={() => setActiveSection("live")}
          >
            Radio Live
          </button>
          <button
            style={{ padding: "6px 18px", borderRadius: "6px", fontSize: "0.8rem", fontWeight: 600, border: "none", cursor: "pointer", transition: "all 0.2s",
              backgroundColor: activeSection === "history" ? "var(--primary)" : "var(--bg-hover)",
              color: activeSection === "history" ? "white" : "var(--text-secondary)" }}
            onClick={() => { setActiveSection("history"); fetchHistory(1); }}
          >
            Database History
          </button>
        </div>
      </div>

      {/* ════════════════════════════════════════════════════════════════════ */}
      {/* LIVE SECTION                                                        */}
      {/* ════════════════════════════════════════════════════════════════════ */}
      {activeSection === "live" && (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, backgroundColor: "var(--bg-card)", borderRadius: "0.75rem", border: "1px solid var(--border)", overflow: "hidden" }}>

          {/* Live toolbar */}
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", padding: "0.625rem 1rem", borderBottom: "1px solid var(--border)", flexWrap: "wrap", backgroundColor: "var(--bg-surface)" }}>
            {/* Search */}
            <div style={{ position: "relative", display: "flex", alignItems: "center", flex: 1, minWidth: "160px" }}>
              <Search size={14} color="var(--text-muted)" style={{ position: "absolute", left: "0.6rem" }} />
              <input
                type="text"
                placeholder="Search live logs…"
                value={liveSearch}
                onChange={e => setLiveSearch(e.target.value)}
                style={{ width: "100%", padding: "0.4rem 0.5rem 0.4rem 2rem", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "0.4rem", color: "var(--text-primary)", fontSize: "0.8rem" }}
              />
              {liveSearch && <button onClick={() => setLiveSearch("")} style={{ position: "absolute", right: "0.5rem", background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer" }}><X size={13} /></button>}
            </div>
            {/* Service filter */}
            <select
              value={liveService}
              onChange={e => setLiveService(e.target.value)}
              style={{ padding: "0.4rem 0.6rem", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "0.4rem", color: "var(--text-primary)", fontSize: "0.8rem", outline: "none" }}
            >
              <option value="All">All Services</option>
              {services.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            {/* Level filter */}
            <select
              value={liveLevel}
              onChange={e => setLiveLevel(e.target.value)}
              style={{ padding: "0.4rem 0.6rem", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "0.4rem", color: "var(--text-primary)", fontSize: "0.8rem", outline: "none" }}
            >
              {LOG_LEVELS.map(l => <option key={l} value={l}>{l === "All" ? "All Levels" : l}</option>)}
            </select>

            <div style={{ height: "20px", width: "1px", backgroundColor: "var(--border)" }} />

            {/* Auto-scroll toggle */}
            <button
              onClick={() => setAutoScroll(v => !v)}
              className="btn btn-ghost btn-sm"
              style={{ backgroundColor: autoScroll ? "var(--primary-light)" : "transparent", borderColor: autoScroll ? "var(--primary)" : "var(--border)", color: autoScroll ? "var(--primary)" : "var(--text-secondary)" }}
            >
              {autoScroll ? "Pause scroll" : "Resume scroll"}
            </button>

            {/* Clear */}
            <button
              onClick={() => setLiveLogs([])}
              className="btn btn-ghost btn-sm"
            >
              <Trash2 size={13} />Clear
            </button>

            {/* Download */}
            <button
              onClick={downloadLive}
              className="btn btn-ghost btn-sm"
            >
              <Download size={13} />Download
            </button>

            {/* Reconnect */}
            {wsStatus === "disconnected" && (
              <button
                onClick={connectWs}
                className="btn btn-warning btn-sm"
              >
                <RefreshCw size={13} />Reconnect
              </button>
            )}

            <span style={{ marginLeft: "auto", fontSize: "0.72rem", color: "var(--text-muted)" }}>
              {filteredLive.length.toLocaleString()} / {liveLogs.length.toLocaleString()} entries
            </span>
          </div>

          <TableHeader />

          {/* Log stream */}
          <div
            ref={liveContainerRef}
            onScroll={e => {
              const el = e.currentTarget;
              const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
              if (!atBottom && autoScroll) setAutoScroll(false);
            }}
            style={{ flex: 1, overflowY: "auto", overflowX: "hidden" }}
          >
            {filteredLive.length === 0 ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)", gap: "0.5rem" }}>
                <Terminal size={32} />
                <p style={{ fontSize: "0.875rem", margin: 0 }}>
                  {wsStatus === "connected" ? "Waiting for log entries from HexaAgent…" : "WebSocket not connected. Logs will appear automatically when agent sends data."}
                </p>
              </div>
            ) : (
              filteredLive.map((log, idx) => (
                <LogRow key={log.id || idx} log={log} striped={idx % 2 === 0} />
              ))
            )}
          </div>
        </div>
      )}

      {/* ════════════════════════════════════════════════════════════════════ */}
      {/* HISTORY SECTION                                                     */}
      {/* ════════════════════════════════════════════════════════════════════ */}
      {activeSection === "history" && (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, gap: "0.75rem" }}>

          {/* Filters panel */}
          <div style={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "0.75rem", padding: "1rem 1.25rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: "0.75rem", marginBottom: "0.75rem" }}>
              {/* Search */}
              <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                <Search size={14} color="var(--text-muted)" style={{ position: "absolute", left: "0.65rem" }} />
                <input
                  type="text"
                  placeholder="Search log messages…"
                  value={histSearch}
                  onChange={e => setHistSearch(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && fetchHistory(1)}
                  style={{ width: "100%", padding: "0.45rem 0.5rem 0.45rem 2.1rem", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "0.4rem", color: "var(--text-primary)", fontSize: "0.8rem" }}
                />
              </div>
              {/* Machine */}
              <div>
                <label style={{ display: "block", fontSize: "0.65rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "0.25rem" }}>Machine</label>
                <select value={histMachine} onChange={e => setHistMachine(e.target.value)}
                  style={{ width: "100%", padding: "0.45rem", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "0.4rem", color: "var(--text-primary)", fontSize: "0.8rem", outline: "none" }}>
                  <option value="All">All Machines</option>
                  {machines.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
              </div>
              {/* Service */}
              <div>
                <label style={{ display: "block", fontSize: "0.65rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "0.25rem" }}>Service</label>
                <select value={histService} onChange={e => setHistService(e.target.value)}
                  style={{ width: "100%", padding: "0.45rem", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "0.4rem", color: "var(--text-primary)", fontSize: "0.8rem", outline: "none" }}>
                  <option value="All">All Services</option>
                  {services.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              {/* Level */}
              <div>
                <label style={{ display: "block", fontSize: "0.65rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "0.25rem" }}>Level</label>
                <select value={histLevel} onChange={e => setHistLevel(e.target.value)}
                  style={{ width: "100%", padding: "0.45rem", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "0.4rem", color: "var(--text-primary)", fontSize: "0.8rem", outline: "none" }}>
                  {LOG_LEVELS.map(l => <option key={l} value={l}>{l === "All" ? "All Levels" : l}</option>)}
                </select>
              </div>
            </div>

            {/* Time range */}
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
              <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginRight: "0.25rem" }}><Clock size={12} style={{ verticalAlign: "middle" }} /> Time</span>
              {TIME_PRESETS.map(p => (
                <button key={p.value} onClick={() => setHistPreset(p.value)}
                  style={{ padding: "3px 10px", fontSize: "0.75rem", fontWeight: 600, borderRadius: "4px", border: "1px solid", cursor: "pointer",
                    borderColor: histPreset === p.value ? "var(--primary)" : "var(--border)",
                    backgroundColor: histPreset === p.value ? "var(--primary-light)" : "transparent",
                    color: histPreset === p.value ? "var(--primary)" : "var(--text-secondary)" }}>
                  {p.label}
                </button>
              ))}
              <button onClick={() => setHistPreset("Custom")}
                style={{ padding: "3px 10px", fontSize: "0.75rem", fontWeight: 600, borderRadius: "4px", border: "1px solid", cursor: "pointer",
                  borderColor: histPreset === "Custom" ? "var(--primary)" : "var(--border)",
                  backgroundColor: histPreset === "Custom" ? "var(--primary-light)" : "transparent",
                  color: histPreset === "Custom" ? "var(--primary)" : "var(--text-secondary)" }}>
                Custom
              </button>

              {histPreset === "Custom" && (
                <>
                  <input type="datetime-local" value={histStartTime} onChange={e => setHistStartTime(e.target.value)}
                    style={{ padding: "3px 8px", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "4px", color: "var(--text-primary)", fontSize: "0.75rem", outline: "none" }} />
                  <span style={{ color: "var(--text-muted)" }}>→</span>
                  <input type="datetime-local" value={histEndTime} onChange={e => setHistEndTime(e.target.value)}
                    style={{ padding: "3px 8px", backgroundColor: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: "4px", color: "var(--text-primary)", fontSize: "0.75rem", outline: "none" }} />
                </>
              )}

              <div style={{ marginLeft: "auto", display: "flex", gap: "0.5rem" }}>
                <button onClick={() => fetchHistory(1)} className="btn btn-primary btn-sm">
                  <RefreshCw size={13} />Query Logs
                </button>
              </div>
            </div>
          </div>

          {/* Results table */}
          <div style={{ flex: 1, minHeight: 0, backgroundColor: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "0.75rem", display: "flex", flexDirection: "column", overflow: "hidden" }}>

            {/* Results header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.6rem 1rem", borderBottom: "1px solid var(--border)", backgroundColor: "var(--bg-surface)" }}>
              <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
                {histLoading ? "Querying…" : `${histTotal.toLocaleString()} records found`}
              </span>
              {histTotal > HIST_LIMIT && (
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                  <button
                    onClick={() => fetchHistory(histPage - 1)}
                    disabled={histPage === 1 || histLoading}
                    className="btn btn-ghost btn-sm"
                  >← Prev</button>
                  <span>Page {page} / {Math.ceil(histTotal / HIST_LIMIT)}</span>
                  <button
                    onClick={() => fetchHistory(histPage + 1)}
                    disabled={histPage >= Math.ceil(histTotal / HIST_LIMIT) || histLoading}
                    className="btn btn-ghost btn-sm"
                  >Next →</button>
                </div>
              )}
            </div>

            <TableHeader />

            {/* Logs list */}
            <div style={{ flex: 1, overflowY: "auto" }}>
              {histLoading ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", gap: "0.75rem", color: "var(--text-muted)" }}>
                  <RefreshCw size={18} style={{ animation: "spin 1s linear infinite" }} />
                  <span>Querying database…</span>
                </div>
              ) : histLogs.length === 0 ? (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-muted)", gap: "0.5rem" }}>
                  <Database size={32} />
                  <p style={{ margin: 0, fontSize: "0.875rem" }}>No log records found for the selected filters.</p>
                  <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--text-muted)" }}>Try a wider time range or different filters.</p>
                </div>
              ) : (
                histLogs.map((log, idx) => (
                  <LogRow key={log.id || idx} log={log} striped={idx % 2 === 0} />
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Spin keyframe */}
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default LogsPage;
