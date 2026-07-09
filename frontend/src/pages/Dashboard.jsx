import React, { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import {
  Activity, Server, CheckCircle, XCircle, AlertTriangle,
  RefreshCw, Play, Square, RotateCcw, Clock, Zap,
  Wifi, WifiOff, Shield, Cpu, HardDrive, MemoryStick,
  TrendingUp, ChevronRight, AlertCircle, Info, Circle
} from "lucide-react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend
} from "recharts";

// ─── Color palette ──────────────────────────────────────────────────────────
const C = {
  green:  "#22c55e",
  yellow: "#f59e0b",
  red:    "#ef4444",
  blue:   "#6366f1",
  teal:   "#38bdf8",
  purple: "#a78bfa",
  pink:   "#ec4899",
  muted:  "#64748b",
};

// ─── Status helpers ──────────────────────────────────────────────────────────
function svcStatus(svc, snap) {
  if (snap?.infrastructure?.[svc.name]) {
    const s = snap.infrastructure[svc.name];
    if (s.running && s.healthy) return "healthy";
    if (s.running && !s.healthy) return "warning";
    return "stopped";
  }
  return svc.is_active ? "running" : "stopped";
}

function svcVersion(svc, snap) {
  return snap?.infrastructure?.[svc.name]?.version ?? "—";
}

function svcError(svc, snap) {
  return snap?.infrastructure?.[svc.name]?.error ?? null;
}

function svcLastChecked(svc, snap) {
  const t = snap?.infrastructure?.[svc.name]?.last_checked ?? svc.updated_at;
  if (!t) return "—";
  return new Date(t).toLocaleTimeString();
}

const STATUS_MAP = {
  healthy: { label: "Healthy",  cls: "badge-green",  dot: "dot-green",  color: C.green },
  running: { label: "Running",  cls: "badge-green",  dot: "dot-green",  color: C.green },
  warning: { label: "Warning",  cls: "badge-yellow", dot: "dot-yellow", color: C.yellow },
  stopped: { label: "Stopped",  cls: "badge-red",    dot: "dot-red",    color: C.red },
  failed:  { label: "Failed",   cls: "badge-red",    dot: "dot-red",    color: C.red },
  pending: { label: "Pending",  cls: "badge-yellow", dot: "dot-yellow", color: C.yellow },
  Cancelled: { label: "Cancelled", cls: "badge-gray", dot: "dot-gray",  color: C.muted },
  success: { label: "Success",  cls: "badge-green",  dot: "dot-green",  color: C.green },
};

function StatusBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP["stopped"];
  return (
    <span className={`badge ${s.cls}`}>
      <span className={`status-dot ${s.dot}`} />
      {s.label}
    </span>
  );
}

// ─── Confirm Dialog ──────────────────────────────────────────────────────────
function ConfirmDialog({ isOpen, title, message, onConfirm, onCancel, isLoading }) {
  if (!isOpen) return null;
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 10000, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.5)", backdropFilter: "blur(2px)" }}>
      <div className="card" style={{ width: "90%", maxWidth: 400, padding: 24, animation: "fadeIn 0.2s ease-out" }}>
        <h3 style={{ marginTop: 0, marginBottom: 8, fontSize: "1.1rem" }}>{title}</h3>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: 24, lineHeight: 1.5 }}>
          {message}
        </p>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 12 }}>
          <button className="btn btn-ghost" onClick={onCancel} disabled={isLoading}>Cancel</button>
          <button className="btn btn-primary" onClick={onConfirm} disabled={isLoading} style={{ minWidth: 120 }}>
            {isLoading ? <span className="spinner" style={{ width: 14, height: 14, borderRightColor: "#fff" }} /> : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Toast ───────────────────────────────────────────────────────────────────
function Toast({ toasts, remove }) {
  return (
    <div style={{ position: "fixed", bottom: 24, right: 24, zIndex: 9999, display: "flex", flexDirection: "column", gap: 8 }}>
      {toasts.map(t => (
        <div key={t.id} style={{
          background: "var(--bg-card)", border: `1px solid ${t.type === "error" ? "rgba(239,68,68,0.4)" : "rgba(34,197,94,0.35)"}`,
          borderRadius: "var(--radius-md)", padding: "11px 18px",
          boxShadow: "var(--shadow-lg)", display: "flex", alignItems: "center", gap: 10,
          fontSize: "0.8rem", color: "var(--text-primary)", minWidth: 240,
          animation: "fadeIn 0.2s ease"
        }}>
          {t.type === "error"
            ? <AlertCircle size={15} color={C.red} />
            : <CheckCircle size={15} color={C.green} />}
          {t.msg}
          <button onClick={() => remove(t.id)} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", fontSize: 16, lineHeight: 1 }}>×</button>
        </div>
      ))}
    </div>
  );
}

function useToasts() {
  const [toasts, setToasts] = useState([]);
  const add = useCallback((msg, type = "success") => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  }, []);
  const remove = useCallback(id => setToasts(t => t.filter(x => x.id !== id)), []);
  return { toasts, add, remove };
}

// ─── Skeleton ────────────────────────────────────────────────────────────────
const Sk = ({ w = "100%", h = 16, r = 6 }) => (
  <div className="skeleton" style={{ width: w, height: h, borderRadius: r }} />
);

// ─── Section title ───────────────────────────────────────────────────────────
function SectionTitle({ icon, children, extra }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 700, fontSize: "0.92rem", color: "var(--text-primary)" }}>
        {React.cloneElement(icon, { size: 16, color: "var(--primary)" })}
        {children}
      </div>
      {extra}
    </div>
  );
}

// ─── Summary Stat Card ───────────────────────────────────────────────────────
function SumCard({ label, value, color, icon, loading }) {
  return (
    <div className="stat-card">
      <div className="stat-card-icon" style={{ backgroundColor: `${color}18` }}>
        {React.cloneElement(icon, { size: 17, color })}
      </div>
      {loading ? <Sk w={50} h={28} /> : (
        <div className="stat-card-value" style={{ color: "var(--text-primary)" }}>{value}</div>
      )}
      <div className="stat-card-label">{label}</div>
    </div>
  );
}

// ─── Donut Chart ─────────────────────────────────────────────────────────────
const RADIAN = Math.PI / 180;
function CustomLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent, name }) {
  if (percent < 0.06) return null;
  const r = innerRadius + (outerRadius - innerRadius) * 0.55;
  const x = cx + r * Math.cos(-midAngle * RADIAN);
  const y = cy + r * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central"
      style={{ fontSize: "0.65rem", fontWeight: 700 }}>
      {Math.round(percent * 100)}%
    </text>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────
const Dashboard = () => {
  const { authFetch } = useAuth();
  const { toasts, add: toast, remove } = useToasts();

  const [snapshot,   setSnapshot]   = useState(null);
  const [metrics,    setMetrics]    = useState(null);
  const [machine,    setMachine]    = useState(null);
  const [services,   setServices]   = useState([]);
  const [ops,        setOps]        = useState([]);
  const [loading,    setLoading]    = useState(true);
  const [lastSync,   setLastSync]   = useState(null);
  const [confirmOp,  setConfirmOp]  = useState(null); // { svcName, operation, loading }

  // ── Fetch all data ─────────────────────────────────────────────────────────
  const fetchAll = useCallback(async () => {
    try {
      // Parallel: snapshot + dashboard metrics + ops history
      const [snapR, metR, opsR] = await Promise.allSettled([
        authFetch("/snapshot"),
        authFetch("/dashboard/system"),
        authFetch("/operations/history"),
      ]);

      let snap = null, met = null;

      if (snapR.status === "fulfilled" && snapR.value.ok) {
        snap = await snapR.value.json();
        setSnapshot(snap);
      }
      if (metR.status === "fulfilled" && metR.value.ok) {
        met = await metR.value.json();
        setMetrics(met);
      }
      if (opsR.status === "fulfilled" && opsR.value.ok) {
        const d = await opsR.value.json();
        setOps(d.operations || []);
      }

      // Sequential: project → environment → machine → services
      const projR = await authFetch("/projects");
      if (projR.ok) {
        const [proj] = await projR.json();          // single project
        if (proj) {
          const envR = await authFetch(`/projects/${proj.id}/environments`);
          if (envR.ok) {
            const [env] = await envR.json();         // single environment
            if (env) {
              const machR = await authFetch(`/machines/environments/${env.id}/machines`);
              if (machR.ok) {
                const [mach] = await machR.json();   // single machine
                if (mach) {
                  setMachine(mach);
                  const svcR = await authFetch(`/services/machines/${mach.id}`);
                  if (svcR.ok) {
                    setServices(await svcR.json());
                  }
                }
              }
            }
          }
        }
      }
      setLastSync(new Date());
    } catch (e) {
      console.error("Dashboard error:", e);
    }
    setLoading(false);
  }, [authFetch]);

  useEffect(() => {
    fetchAll();
    const t = setInterval(fetchAll, 30_000);
    return () => clearInterval(t);
  }, [fetchAll]);

  // ── Service operation ──────────────────────────────────────────────────────
  const handleOpClick = useCallback((svcName, operation) => {
    setConfirmOp({ svcName, operation, loading: false });
  }, []);

  const confirmRunOp = useCallback(async () => {
    if (!confirmOp) return;
    const { svcName, operation } = confirmOp;
    
    setConfirmOp(prev => ({ ...prev, loading: true }));
    try {
      const valR = await authFetch("/operations/validate", {
        method: "POST",
        body: JSON.stringify({ service: svcName, operation }),
      });
      if (!valR.ok) throw new Error("Validation failed");
      const { token } = await valR.json();

      const exR = await authFetch("/operations/execute", {
        method: "POST",
        body: JSON.stringify({ service: svcName, operation, token }),
      });
      if (!exR.ok) throw new Error("Execution failed");
      const res = await exR.json();

      toast(`${operation.charAt(0).toUpperCase() + operation.slice(1)} queued for ${svcName}`, "success");

      // Refresh ops + snapshot after short delay
      setTimeout(() => fetchAll(), 3000);
    } catch (e) {
      toast(`Failed to ${operation} ${svcName}: ${e.message}`, "error");
    } finally {
      setConfirmOp(null);
    }
  }, [authFetch, fetchAll, toast, confirmOp]);

  // ── Derived values ─────────────────────────────────────────────────────────
  const snap = snapshot || {};
  const infra = snap.infrastructure || {};
  const sys   = snap.system || {};
  const res   = snap.resources || {};
  const avail = snap.availability || {};

  // Agent online = we have a recent snapshot with success flag
  const agentOnline = !!snapshot && snapshot.success !== false;
  const agentHost   = machine?.name || sys.hostname || "HexaAgent";
  const agentOs     = machine?.os || sys.os_version || "—";
  const agentUptime = sys.uptime_seconds
    ? `${Math.floor(sys.uptime_seconds / 3600)}h ${Math.floor((sys.uptime_seconds % 3600) / 60)}m`
    : "—";

  // CPU / memory from snapshot resources
  const cpuPct  = res.cpu?.cpu_percent ?? null;
  const memGb   = res.memory?.memory_gb ?? null;
  const diskPct = sys.disk_percent ?? null;

  // Services with live status from snapshot
  const enrichedSvcs = services.map(svc => ({
    ...svc,
    _status:       svcStatus(svc, snapshot),
    _version:      svcVersion(svc, snapshot),
    _error:        svcError(svc, snapshot),
    _last_checked: svcLastChecked(svc, snapshot),
    _port:         infra[svc.name]?.port ?? null,
    _pid:          infra[svc.name]?.pid ?? null,
    _cpu:          infra[svc.name]?.cpu_percent ?? null,
    _mem_mb:       infra[svc.name]?.memory_mb ?? null,
  }));

  // Summary counts
  const totalSvcs   = enrichedSvcs.length;
  const activeSvcs  = enrichedSvcs.filter(s => ["healthy","running"].includes(s._status)).length;
  const stoppedSvcs = enrichedSvcs.filter(s => s._status === "stopped").length;
  const warningSvcs = enrichedSvcs.filter(s => s._status === "warning").length;

  // Alerts from snapshot
  const alerts  = Array.isArray(snap.alerts) ? snap.alerts : [];
  const critical = alerts.filter(a => a.severity === "critical").length;
  const warning  = alerts.filter(a => a.severity === "warning").length;

  // Chart data — service distribution
  const svcChartData = [
    ...(activeSvcs  ? [{ name: "Healthy",  value: activeSvcs,  color: C.green }]  : []),
    ...(warningSvcs ? [{ name: "Warning",  value: warningSvcs, color: C.yellow }] : []),
    ...(stoppedSvcs ? [{ name: "Stopped",  value: stoppedSvcs, color: C.red }]    : []),
  ];

  // Chart data — operations
  const opStats = ops.reduce((acc, op) => {
    acc[op.operation] = (acc[op.operation] || 0) + 1;
    return acc;
  }, {});
  const opChartData = Object.entries(opStats).map(([name, count]) => ({ name, count }));

  // Ops from snapshot infra — deduplicated names (for service operation buttons)
  const snapSvcNames = Object.keys(infra);
  // Show all DB services, but operations use the snapshot key name
  const operableSvcs = enrichedSvcs.filter(s => snapSvcNames.includes(s.name) || s.is_active);

  // ── Resource bar ──────────────────────────────────────────────────────────
  const ResourceBar = ({ label, value, icon, color = "var(--primary)" }) => {
    if (value == null) return null;
    const pct = Math.min(100, Math.max(0, Math.round(value)));
    const barColor = pct > 85 ? C.red : pct > 65 ? C.yellow : color;
    return (
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", display: "flex", alignItems: "center", gap: 5 }}>
            {icon} {label}
          </span>
          <span style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-primary)" }}>{pct}%</span>
        </div>
        <div style={{ height: 6, background: "var(--bg-hover)", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${pct}%`, background: barColor, borderRadius: 3, transition: "width 0.6s ease" }} />
        </div>
      </div>
    );
  };

  const formatStorage = (gbValue) => {
    if (gbValue == null) return "—";
    if (gbValue < 1) {
      return `${Math.round(gbValue * 1024)} MB`;
    }
    return `${gbValue.toFixed(2)} GB`;
  };

  const met = metrics || {};

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="page-container fade-in" style={{ gap: 0, paddingBottom: 32 }}>
      <Toast toasts={toasts} remove={remove} />
      
      <ConfirmDialog 
        isOpen={!!confirmOp}
        title="Confirm Operation"
        message={`Are you sure you want to ${confirmOp?.operation} the ${confirmOp?.svcName} service? This operation may temporarily interrupt the service.`}
        onConfirm={confirmRunOp}
        onCancel={() => setConfirmOp(null)}
        isLoading={confirmOp?.loading}
      />

      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          <div className="page-title">Dashboard</div>
          <div className="page-subtitle" style={{ marginTop: 2 }}>
            {lastSync ? `Last synced ${lastSync.toLocaleTimeString()}` : "Loading…"}
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={fetchAll} disabled={loading}>
          <RefreshCw size={13} style={{ animation: loading ? "spin 1s linear infinite" : "none" }} />
          Refresh
        </button>
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* SECTION 1 — HexaAgent Status                                     */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      <div style={{ marginBottom: 20 }}>
        {loading ? (
          <div className="card" style={{ padding: 20 }}>
            <Sk w="40%" h={20} /><div style={{ height: 8 }} />
            <Sk w="60%" h={14} />
          </div>
        ) : (
          <div className="card" style={{
            padding: "18px 22px",
            borderLeft: `4px solid ${agentOnline ? C.green : C.red}`,
            background: agentOnline
              ? "linear-gradient(135deg, var(--bg-card), rgba(34,197,94,0.04))"
              : "linear-gradient(135deg, var(--bg-card), rgba(239,68,68,0.04))",
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}>
              {/* Left: identity */}
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <div style={{
                  width: 52, height: 52,
                  borderRadius: "50%",
                  background: agentOnline ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)",
                  border: `2px solid ${agentOnline ? C.green : C.red}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  position: "relative"
                }}>
                  <Server size={22} color={agentOnline ? C.green : C.red} />
                  {agentOnline && (
                    <span style={{
                      position: "absolute", bottom: 2, right: 2,
                      width: 10, height: 10, borderRadius: "50%",
                      background: C.green, border: "2px solid var(--bg-card)",
                      boxShadow: `0 0 6px ${C.green}`
                    }} />
                  )}
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: "1rem", color: "var(--text-primary)" }}>
                    {agentHost}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: 2 }}>
                    {agentOs}
                  </div>
                </div>
                <span className={`badge ${agentOnline ? "badge-green" : "badge-red"}`} style={{ fontSize: "0.75rem", padding: "4px 10px" }}>
                  <span className={`status-dot ${agentOnline ? "dot-green" : "dot-red"}`} />
                  {agentOnline ? "Online" : "Offline"}
                </span>
              </div>

              {/* Right: meta stats */}
              <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
                {[
                  { label: "Uptime", value: agentUptime, icon: <Clock size={13} /> },
                  { label: "Load (1m)", value: sys.load_average_1m?.toFixed(2) ?? "—", icon: <TrendingUp size={13} /> },
                  { label: "Disk Used", value: sys.disk_percent ? `${sys.disk_percent}%` : "—", icon: <HardDrive size={13} /> },
                  { label: "Availability", value: avail.external?.healthy ? "✓ External" : avail.internal?.healthy ? "✓ Internal" : "—", icon: <Wifi size={13} /> },
                  { label: "Last Snapshot", value: snap.timestamp ? new Date(snap.timestamp).toLocaleTimeString() : "—", icon: <Activity size={13} /> },
                ].map(({ label, value, icon }) => (
                  <div key={label} style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "0.67rem", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 3, display: "flex", alignItems: "center", gap: 3 }}>
                      {icon} {label}
                    </div>
                    <div style={{ fontWeight: 700, fontSize: "0.85rem", color: "var(--text-primary)" }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>

          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* SECTION 1.5 — System Resources & Deployment & HTTP & Alerts       */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      <div className="dashboard-grid-three-col">
        
        {/* LEFT: System Resources */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div className="card" style={{ flex: 1 }}>
            <SectionTitle icon={<Cpu />}>System Resources</SectionTitle>
            {loading ? (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <Sk h={50} /><Sk h={50} /><Sk h={50} /><Sk h={50} />
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <SumCard label="CPU Usage" value={met?.CPU?.utilization != null ? `${met.CPU.utilization.toFixed(1)}%` : "—"} color={C.blue} icon={<Cpu />} />
                <SumCard label="RAM Usage" value={formatStorage(met?.RAM?.used_gb)} color={C.purple} icon={<MemoryStick />} />
                {(met?.GPU?.utilization > 0 || met?.GPU?.model !== "Unknown") && (
                  <SumCard label="GPU Usage" value={`${met.GPU?.utilization?.toFixed(1) || 0}%`} color={C.teal} icon={<Activity />} />
                )}
                <SumCard label="Project Size" value={formatStorage(met?.["Project Storage"]?.gb)} color={C.green} icon={<HardDrive />} />
                <SumCard label="Backend Size" value={formatStorage(met?.["Backend Storage"]?.gb)} color={C.muted} icon={<HardDrive />} />
                <SumCard label="Frontend Size" value={formatStorage(met?.["Frontend Storage"]?.gb)} color={C.muted} icon={<HardDrive />} />
                <SumCard label="Uploads Size" value={formatStorage(met?.["Uploads Storage"]?.gb)} color={C.yellow} icon={<HardDrive />} />
              </div>
            )}
          </div>
        </div>

        {/* CENTER: HTTP Endpoint Monitoring & Deployment Information */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* HTTP Endpoint Monitoring */}
          <div className="card" style={{ flex: 1 }}>
            <SectionTitle icon={<Wifi />}>HTTP Endpoint Monitoring</SectionTitle>
            {loading ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Sk h={40} /><Sk h={40} />
              </div>
            ) : Object.keys(avail).length === 0 ? (
              <div className="empty-state" style={{ padding: "16px 0" }}>
                <div className="empty-state-icon"><WifiOff size={24} /></div>
                <p>No endpoint data available</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 180, overflowY: "auto", paddingRight: 4 }}>
                {Object.entries(avail).map(([key, data]) => (
                  <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 10px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                    <div>
                      <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-primary)" }}>{data.url || key}</div>
                      <div style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginTop: 1 }}>{data.last_checked ? new Date(data.last_checked).toLocaleTimeString() : "—"}</div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ fontSize: "0.7rem", fontFamily: "monospace", color: data.response_time_ms > 500 ? C.yellow : "var(--text-muted)" }}>
                        {data.response_time_ms != null ? `${data.response_time_ms} ms` : "—"}
                      </div>
                      <StatusBadge status={data.healthy ? "healthy" : "failed"} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Deployment Information */}
          <div className="card" style={{ flex: 1 }}>
            <SectionTitle icon={<Info />}>Deployment Information</SectionTitle>
            {loading ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                <Sk h={20} /><Sk h={20} /><Sk h={20} />
              </div>
            ) : !snap.deployment || Object.keys(snap.deployment).length === 0 ? (
              <div className="empty-state" style={{ padding: "16px 0" }}>
                <div className="empty-state-icon"><Info size={24} /></div>
                <p>No deployment info available</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {(() => {
                  const git = snap.deployment.git || {};
                  const deploymentFields = [
                    { label: "Git Branch", value: git.branch },
                    { label: "Commit ID", value: git.commit_sha ? git.commit_sha.substring(0, 7) : null, fullValue: git.commit_sha },
                    { label: "Commit Message", value: git.last_commit_message },
                    { label: "Commit Author", value: git.commit_author || git.author || "—" },
                    { label: "Deployment Time", value: git.last_commit_time ? new Date(git.last_commit_time).toLocaleString() : null },
                    { label: "Last Checked", value: git.last_checked ? new Date(git.last_checked).toLocaleString() : null }
                  ];
                  return deploymentFields.map(({ label, value, fullValue }) => (
                    value ? (
                      <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px dashed var(--border)" }}>
                        <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", textTransform: "capitalize" }}>{label.replace(/_/g, " ")}</span>
                        <span
                          style={{ fontSize: "0.72rem", fontWeight: 600, color: "var(--text-primary)", textAlign: "right", maxWidth: "60%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                          title={fullValue || value}
                        >
                          {value}
                        </span>
                      </div>
                    ) : null
                  ));
                })()}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT: Active Alerts */}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div className="card" style={{ flex: 1 }}>
            <SectionTitle icon={<Shield />}>Active Alerts</SectionTitle>
            {loading ? <Sk w="100%" h={180} r={8} /> : alerts.length === 0 ? (
              <div className="empty-state" style={{ padding: "24px 0" }}>
                <div className="empty-state-icon"><CheckCircle size={28} color={C.green} /></div>
                <h3 style={{ color: C.green }}>All clear</h3>
                <p>No active alerts</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 310, overflowY: "auto", paddingRight: 4 }}>
                {alerts.map((a, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px", background: "var(--bg-surface)", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)" }}>
                    <AlertTriangle size={13} color={a.severity === "critical" ? C.red : C.yellow} style={{ flexShrink: 0, marginTop: 2 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={a.title || a.message}>{a.title || a.message}</div>
                      {a.service && <div style={{ fontSize: "0.67rem", color: "var(--text-muted)", marginTop: 2 }}>{a.service}</div>}
                    </div>
                    <StatusBadge status={a.severity || "warning"} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* SECTION 2 — Summary Cards                                        */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, marginBottom: 20 }}>
        <SumCard label="Total Services"  value={totalSvcs}   color={C.blue}   icon={<Zap />}            loading={loading} />
        <SumCard label="Healthy"         value={activeSvcs}  color={C.green}  icon={<CheckCircle />}    loading={loading} />
        <SumCard label="Stopped"         value={stoppedSvcs} color={C.red}    icon={<XCircle />}        loading={loading} />
        {warningSvcs > 0 && <SumCard label="Warning" value={warningSvcs} color={C.yellow} icon={<AlertTriangle />} loading={loading} />}
        <SumCard label="Total Alerts"   value={alerts.length} color={C.teal}  icon={<Shield />}         loading={loading} />
        {critical > 0 && <SumCard label="Critical" value={critical}  color={C.red}    icon={<AlertCircle />}   loading={loading} />}
        {warning  > 0 && <SumCard label="Warnings" value={warning}   color={C.yellow} icon={<AlertTriangle />} loading={loading} />}
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* SECTION 3 & 4 — Services table + Operations                      */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      <div style={{ marginBottom: 20 }}>
        <div className="table-wrap">
          <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
            <SectionTitle icon={<Activity />}>
              Services Overview
            </SectionTitle>
          </div>

          {loading ? (
            <div style={{ padding: 20 }}>
              {[...Array(4)].map((_, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr 1fr 180px", gap: 12, marginBottom: 12, alignItems: "center" }}>
                  <Sk h={14} /><Sk h={14} /><Sk w={70} h={22} r={100} /><Sk w={70} h={22} r={100} /><Sk h={14} /><Sk h={14} /><Sk h={32} r={6} />
                </div>
              ))}
            </div>
          ) : enrichedSvcs.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon"><Server size={40} /></div>
              <h3>No services found</h3>
              <p>Services appear once HexaAgent reports them.</p>
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ minWidth: 900 }}>
                <thead>
                  <tr>
                    <th>Service</th>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Port / PID</th>
                    <th>CPU / Mem</th>
                    <th>Last Checked</th>
                    <th>Error</th>
                    <th style={{ textAlign: "right" }}>Operations</th>
                  </tr>
                </thead>
                <tbody>
                  {enrichedSvcs.map(svc => {
                    const isSnap = !!infra[svc.name];
                    return (
                      <tr key={svc.id}>
                        {/* Name */}
                        <td>
                          <div style={{ fontWeight: 600, color: "var(--text-primary)", fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 6 }}>
                            <Circle size={8} fill={STATUS_MAP[svc._status]?.color || C.muted} color="transparent" />
                            {svc.name}
                          </div>
                          <div style={{ fontSize: "0.67rem", color: "var(--text-muted)", marginTop: 1 }}>{svc.service_type}</div>
                        </td>

                        {/* Version */}
                        <td>
                          <span style={{ fontFamily: "monospace", fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                            {svc._version}
                          </span>
                        </td>

                        {/* Status */}
                        <td><StatusBadge status={svc._status} /></td>

                        {/* Port / PID */}
                        <td>
                          <span style={{ fontFamily: "monospace", fontSize: "0.72rem", color: "var(--text-muted)" }}>
                            {svc._port ? `:${svc._port}` : "—"}
                            {svc._pid ? ` · pid ${svc._pid}` : ""}
                          </span>
                        </td>

                        {/* CPU / Mem */}
                        <td>
                          <span style={{ fontFamily: "monospace", fontSize: "0.72rem", color: "var(--text-muted)" }}>
                            {svc._cpu != null ? `${svc._cpu}%` : "—"}
                            {svc._mem_mb != null ? ` · ${svc._mem_mb} MB` : ""}
                          </span>
                        </td>

                        {/* Last checked */}
                        <td style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>{svc._last_checked}</td>

                        {/* Error */}
                        <td>
                          {svc._error
                            ? <span style={{ fontSize: "0.72rem", color: C.red, maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "block" }} title={svc._error}>{svc._error}</span>
                            : <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>No Errors</span>
                          }
                        </td>

                        {/* Operations */}
                        <td>
                          <div style={{ display: "flex", gap: 5, justifyContent: "flex-end" }}>
                            {[
                              { op: "start",   label: "Start",   cls: "btn-success", icon: <Play size={11} /> },
                              { op: "stop",    label: "Stop",    cls: "btn-danger",  icon: <Square size={11} /> },
                              { op: "restart", label: "Restart", cls: "btn-ghost",   icon: <RotateCcw size={11} /> },
                            ].map(({ op, label, cls, icon }) => (
                              <button
                                key={op}
                                className={`btn ${cls} btn-sm`}
                                onClick={() => handleOpClick(svc.name, op)}
                                title={`${label} ${svc.name}`}
                                style={{ minWidth: 28, padding: "4px 8px" }}
                              >
                                {icon}
                                <span style={{ fontSize: "0.7rem" }}>{label}</span>
                              </button>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* SECTION 5 & 6 — Charts + Audit History                          */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      <div className="dashboard-grid-two-col">

        {/* Service Distribution Donut */}
        <div className="card">
          <SectionTitle icon={<Activity />}>Service Health</SectionTitle>
          {loading ? <Sk w="100%" h={180} r={8} /> : svcChartData.length === 0 ? (
            <div className="empty-state" style={{ padding: "24px 0" }}>
              <div className="empty-state-icon"><Activity size={28} /></div>
              <p>No service data</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie data={svcChartData} cx="50%" cy="50%" innerRadius={50} outerRadius={80}
                  paddingAngle={3} dataKey="value" labelLine={false} label={CustomLabel}>
                  {svcChartData.map((e, i) => <Cell key={i} fill={e.color} />)}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: "0.78rem" }}
                  formatter={(v, n) => [v, n]}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
          {/* Legend */}
          {!loading && svcChartData.length > 0 && (
            <div style={{ display: "flex", justifyContent: "center", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
              {svcChartData.map(e => (
                <div key={e.name} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: "0.72rem", color: "var(--text-secondary)" }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: e.color, display: "inline-block" }} />
                  {e.name} ({e.value})
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Operations bar chart */}
        <div className="card">
          <SectionTitle icon={<TrendingUp />}>Operations Summary</SectionTitle>
          {loading ? <Sk w="100%" h={180} r={8} /> : opChartData.length === 0 ? (
            <div className="empty-state" style={{ padding: "24px 0" }}>
              <div className="empty-state-icon"><TrendingUp size={28} /></div>
              <p>No operations yet</p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={opChartData} margin={{ top: 4, right: 4, bottom: 4, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--text-muted)" }} />
                <YAxis tick={{ fontSize: 11, fill: "var(--text-muted)" }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 8, fontSize: "0.78rem" }}
                />
                <Bar dataKey="count" name="Count" radius={[4, 4, 0, 0]}>
                  {opChartData.map((_, i) => (
                    <Cell key={i} fill={[C.green, C.red, C.blue, C.yellow, C.purple][i % 5]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════ */}
      {/* SECTION 5 — Audit / Operations History                           */}
      {/* ══════════════════════════════════════════════════════════════════ */}
      <div className="table-wrap">
        <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <SectionTitle icon={<Clock />}>Recent Operations</SectionTitle>
          {ops.length > 0 && (
            <span className="badge badge-purple">{ops.length} operations</span>
          )}
        </div>

        {loading ? (
          <div style={{ padding: 20 }}>
            {[...Array(3)].map((_, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr", gap: 12, marginBottom: 10 }}>
                {[...Array(5)].map((_, j) => <Sk key={j} h={14} />)}
              </div>
            ))}
          </div>
        ) : ops.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon"><Clock size={36} /></div>
            <h3>No operations yet</h3>
            <p>Use the Start / Stop / Restart buttons above to perform service operations.</p>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Service</th>
                <th>Operation</th>
                <th>Status</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {ops.slice(0, 50).map(op => {
                const ts = new Date(op.timestamp);
                const finished = op.finished_at ? new Date(op.finished_at) : null;
                const dur = finished ? `${((finished - ts) / 1000).toFixed(1)}s` : "—";
                return (
                  <tr key={op.id}>
                    <td style={{ fontFamily: "monospace", fontSize: "0.75rem", color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                      {ts.toLocaleTimeString()}
                      <div style={{ fontSize: "0.65rem", color: "var(--text-muted)" }}>{ts.toLocaleDateString()}</div>
                    </td>
                    <td>
                      <span style={{ fontWeight: 600, fontSize: "0.8rem", color: "var(--text-primary)" }}>
                        {op.service}
                      </span>
                    </td>
                    <td>
                      <span className="badge badge-blue" style={{ textTransform: "capitalize" }}>{op.operation}</span>
                    </td>
                    <td><StatusBadge status={op.status} /></td>
                    <td style={{ fontFamily: "monospace", fontSize: "0.72rem", color: "var(--text-muted)" }}>{dur}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default Dashboard;
