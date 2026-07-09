import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import {
  Activity, ArrowLeft, ArrowUpDown, ChevronDown, ChevronRight,
  Clock, Database, Filter, Info, RefreshCw, Search, ShieldAlert,
  TrendingUp, Wifi, WifiOff, Zap, AlertTriangle, AlertCircle, CheckCircle,
  BarChart2, Play, CornerDownRight
} from "lucide-react";
import {
  LineChart, Line, AreaChart, Area, PieChart, Pie, BarChart, Bar,
  Cell, Tooltip, ResponsiveContainer, XAxis, YAxis, CartesianGrid
} from "recharts";

// Color Palette matching Datadog/Grafana observability styling
const COLORS = {
  healthy: "#22c55e", // Green
  warning: "#eab308", // Yellow
  critical: "#ef4444", // Red
  noTraffic: "#64748b", // Gray
  blue: "#3b82f6",
  purple: "#a855f7",
  magenta: "#ec4899",
  orange: "#f97316",
  gridLine: "var(--border)"
};

const METHOD_COLORS = {
  GET: { bg: "rgba(34, 197, 94, 0.1)", text: "#22c55e", border: "rgba(34, 197, 94, 0.3)" },
  POST: { bg: "rgba(59, 130, 246, 0.1)", text: "#3b82f6", border: "rgba(59, 130, 246, 0.3)" },
  PUT: { bg: "rgba(234, 179, 8, 0.1)", text: "#eab308", border: "rgba(234, 179, 8, 0.3)" },
  DELETE: { bg: "rgba(239, 68, 68, 0.1)", text: "#ef4444", border: "rgba(239, 68, 68, 0.3)" },
  PATCH: { bg: "rgba(168, 85, 247, 0.1)", text: "#a855f7", border: "rgba(168, 85, 247, 0.3)" },
  OPTIONS: { bg: "rgba(100, 116, 139, 0.1)", text: "#64748b", border: "rgba(100, 116, 139, 0.3)" }
};

// Categorize endpoints into logical groups based on route components
const categorizeRoute = (route) => {
  if (!route) return "General";
  const path = route.toLowerCase();
  
  if (path.includes("/auth")) return "Authentication";
  if (path.includes("/posts")) return "Posts";
  if (path.includes("/channels") || path.includes("/channel-posts")) return "Channels";
  if (path.includes("/profile")) return "Profile";
  if (path.includes("/wallet")) return "Wallet";
  if (path.includes("/users")) return "Users";
  if (path.includes("/assignments")) return "Assignments";
  if (path.includes("/notifications")) return "Notifications";
  if (path.includes("/chat")) return "Chat";
  if (path.includes("/projects")) return "Projects";
  if (path.includes("/admin")) return "Admin";
  if (path.includes("/events")) return "Events";
  if (path.includes("/search")) return "Search";
  if (path.includes("/launchpad")) return "Launchpad";
  if (path.includes("/education")) return "Education";
  if (path.includes("/tasks")) return "Tasks";
  if (path.includes("/polls")) return "Polls";
  
  // Dynamic fallback to the first segment after /api/v1/
  const match = route.match(/^\/api\/v1\/([^/]+)/);
  if (match && match[1]) {
    const raw = match[1];
    return raw.charAt(0).toUpperCase() + raw.slice(1).replace(/-/g, " ");
  }
  return "General";
};

// Check if an endpoint matches search query and filters
const matchEndpoint = (ep, query, filters) => {
  if (query) {
    const lowerQuery = query.toLowerCase();
    const matchesRoute = ep.route?.toLowerCase().includes(lowerQuery);
    const matchesMethod = ep.method?.toLowerCase().includes(lowerQuery);
    const matchesName = ep.name?.toLowerCase().includes(lowerQuery);
    if (!matchesRoute && !matchesMethod && !matchesName) return false;
  }

  if (filters.health !== "All") {
    const healthMap = {
      Healthy: "healthy",
      Warning: "warning",
      Critical: "critical",
      "No Traffic": "no_traffic"
    };
    const targetStatus = healthMap[filters.health];
    if (ep.health_status !== targetStatus) return false;
  }

  if (filters.method !== "All") {
    if (ep.method !== filters.method) return false;
  }

  if (filters.statusCode !== "All") {
    const code = String(ep.last_status_code || "");
    if (!code.startsWith(filters.statusCode.charAt(0))) return false;
  }

  if (filters.latency !== "All") {
    const latency = ep.avg_latency || 0;
    if (filters.latency === "<10ms" && latency >= 10) return false;
    if (filters.latency === "10-50ms" && (latency < 10 || latency > 50)) return false;
    if (filters.latency === "50-100ms" && (latency < 50 || latency > 100)) return false;
    if (filters.latency === "100ms+" && latency <= 100) return false;
  }

  if (filters.traffic !== "All") {
    const rps = ep.requests_per_second || 0;
    if (filters.traffic === "High" && rps < 5) return false;
    if (filters.traffic === "Medium" && (rps < 0.5 || rps >= 5)) return false;
    if (filters.traffic === "Low" && rps >= 0.5) return false;
  }

  return true;
};

// KPI Cards Component
const ApiOverviewCards = ({ endpoints }) => {
  const stats = useMemo(() => {
    let totalRequests = 0;
    let totalRps = 0;
    let sumLatency = 0;
    let countLatency = 0;
    let sumSuccess = 0;
    let countSuccess = 0;

    let healthy = 0;
    let warning = 0;
    let critical = 0;
    let noTraffic = 0;

    endpoints.forEach(ep => {
      totalRequests += ep.total_requests || 0;
      totalRps += ep.requests_per_second || 0;
      
      if (ep.total_requests > 0) {
        sumLatency += (ep.avg_latency || 0) * (ep.total_requests);
        countLatency += ep.total_requests;
        sumSuccess += (ep.success_rate || 0) * (ep.total_requests);
        countSuccess += ep.total_requests;
      }

      if (ep.health_status === "healthy") healthy++;
      else if (ep.health_status === "warning") warning++;
      else if (ep.health_status === "critical") critical++;
      else noTraffic++;
    });

    const avgLatency = countLatency > 0 ? sumLatency / countLatency : 0;
    const avgSuccess = countSuccess > 0 ? sumSuccess / countSuccess : 100;

    return {
      total: endpoints.length,
      healthy,
      warning,
      critical,
      noTraffic,
      totalRequests,
      overallRps: totalRps,
      avgLatency,
      avgSuccess,
      avgFailure: 100 - avgSuccess
    };
  }, [endpoints]);

  const cardsData = [
    { label: "Total Endpoints", value: stats.total, color: COLORS.blue, icon: <Activity size={15} /> },
    { label: "Healthy", value: stats.healthy, color: COLORS.healthy, icon: <CheckCircle size={15} /> },
    { label: "Warning", value: stats.warning, color: COLORS.warning, icon: <AlertTriangle size={15} /> },
    { label: "Critical", value: stats.critical, color: COLORS.critical, icon: <AlertCircle size={15} /> },
    { label: "No Traffic", value: stats.noTraffic, color: COLORS.noTraffic, icon: <WifiOff size={15} /> },
    { label: "Total Requests", value: stats.totalRequests.toLocaleString(), color: COLORS.purple, icon: <Database size={15} /> },
    { label: "Overall Req/s", value: stats.overallRps.toFixed(2), color: COLORS.orange, icon: <TrendingUp size={15} /> },
    { label: "Avg Latency", value: `${stats.avgLatency.toFixed(1)} ms`, color: COLORS.magenta, icon: <Clock size={15} /> },
    { label: "Success Rate", value: `${stats.avgSuccess.toFixed(1)}%`, color: COLORS.healthy, icon: <CheckCircle size={15} /> }
  ];

  return (
    <div className="api-kpi-grid">
      {cardsData.map(c => (
        <div key={c.label} className="stat-card" style={{ padding: "10px 12px", borderBottom: `2px solid ${c.color}30`, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ fontSize: "0.68rem", color: "var(--text-muted)", fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={c.label}>{c.label}</span>
            <span style={{ color: c.color, flexShrink: 0 }}>{c.icon}</span>
          </div>
          <div style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={c.value}>{c.value}</div>
        </div>
      ))}
    </div>
  );
};

// Sticky Search and Filter Panel
const ApiFilterBar = ({ search, setSearch, filters, setFilters }) => {
  const handleFilterChange = (key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div style={{
      backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)",
      padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10
    }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        {/* Search */}
        <div style={{ position: "relative", flex: 2, minWidth: 260 }}>
          <Search size={14} color="var(--text-muted)" style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)" }} />
          <input
            type="text"
            placeholder="Search by Route, Method, or Name..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              width: "100%", padding: "6px 10px 6px 30px",
              fontSize: "0.8rem", borderRadius: 6,
              border: "1px solid var(--border)", backgroundColor: "var(--bg-input)", color: "var(--text-primary)"
            }}
          />
        </div>

        {/* Health filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 600 }}>HEALTH</span>
          <select
            value={filters.health}
            onChange={e => handleFilterChange("health", e.target.value)}
            style={{ padding: "4px 8px", fontSize: "0.78rem", borderRadius: 4, border: "1px solid var(--border)", backgroundColor: "var(--bg-input)", color: "var(--text-primary)" }}
          >
            <option>All</option>
            <option>Healthy</option>
            <option>Warning</option>
            <option>Critical</option>
            <option>No Traffic</option>
          </select>
        </div>

        {/* Method filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 600 }}>METHOD</span>
          <select
            value={filters.method}
            onChange={e => handleFilterChange("method", e.target.value)}
            style={{ padding: "4px 8px", fontSize: "0.78rem", borderRadius: 4, border: "1px solid var(--border)", backgroundColor: "var(--bg-input)", color: "var(--text-primary)" }}
          >
            <option>All</option>
            <option>GET</option>
            <option>POST</option>
            <option>PUT</option>
            <option>DELETE</option>
            <option>PATCH</option>
            <option>OPTIONS</option>
          </select>
        </div>

        {/* Status Codes filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 600 }}>STATUS</span>
          <select
            value={filters.statusCode}
            onChange={e => handleFilterChange("statusCode", e.target.value)}
            style={{ padding: "4px 8px", fontSize: "0.78rem", borderRadius: 4, border: "1px solid var(--border)", backgroundColor: "var(--bg-input)", color: "var(--text-primary)" }}
          >
            <option>All</option>
            <option>2xx</option>
            <option>3xx</option>
            <option>4xx</option>
            <option>5xx</option>
          </select>
        </div>

        {/* Latency Filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 600 }}>LATENCY</span>
          <select
            value={filters.latency}
            onChange={e => handleFilterChange("latency", e.target.value)}
            style={{ padding: "4px 8px", fontSize: "0.78rem", borderRadius: 4, border: "1px solid var(--border)", backgroundColor: "var(--bg-input)", color: "var(--text-primary)" }}
          >
            <option>All</option>
            <option>&lt;10ms</option>
            <option>10-50ms</option>
            <option>50-100ms</option>
            <option>100ms+</option>
          </select>
        </div>

        {/* Traffic Filter */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", fontWeight: 600 }}>TRAFFIC</span>
          <select
            value={filters.traffic}
            onChange={e => handleFilterChange("traffic", e.target.value)}
            style={{ padding: "4px 8px", fontSize: "0.78rem", borderRadius: 4, border: "1px solid var(--border)", backgroundColor: "var(--bg-input)", color: "var(--text-primary)" }}
          >
            <option>All</option>
            <option>High</option>
            <option>Medium</option>
            <option>Low</option>
          </select>
        </div>
      </div>
    </div>
  );
};

// Endpoint Row Component (Optimized & Memoized)
const ApiEndpointRow = React.memo(({ ep, onSelect }) => {
  const mStyle = METHOD_COLORS[ep.method] || METHOD_COLORS.GET;
  const statusCodes = ep.status_codes || {};
  const statusString = Object.entries(statusCodes)
    .map(([code, count]) => `${code}(${count})`)
    .join(", ") || "—";

  const getHealthBadge = (health) => {
    switch (health) {
      case "healthy": return <span className="badge badge-green" style={{ fontSize: "0.7rem" }}><span className="status-dot dot-green" />Healthy</span>;
      case "warning": return <span className="badge badge-yellow" style={{ fontSize: "0.7rem" }}><span className="status-dot dot-yellow" />Warning</span>;
      case "critical": return <span className="badge badge-red" style={{ fontSize: "0.7rem" }}><span className="status-dot dot-red" />Critical</span>;
      default: return <span className="badge badge-gray" style={{ fontSize: "0.7rem" }}><span className="status-dot dot-gray" />No Traffic</span>;
    }
  };

  return (
    <div
      onClick={() => onSelect(ep)}
      style={{
        display: "grid",
        gridTemplateColumns: "80px 1.5fr 110px 100px 90px 90px 90px 100px 1fr 40px",
        gap: 12, alignItems: "center", padding: "10px 16px",
        borderBottom: "1px solid var(--border)", cursor: "pointer",
        transition: "background 0.15s ease", fontSize: "0.78rem"
      }}
      className="nav-item-hover"
      onMouseEnter={e => e.currentTarget.style.backgroundColor = "var(--bg-hover)"}
      onMouseLeave={e => e.currentTarget.style.backgroundColor = "transparent"}
    >
      {/* Method */}
      <div>
        <span style={{
          display: "inline-block", width: "100%", textAlign: "center",
          fontWeight: 700, fontSize: "0.7rem", padding: "2px 0", borderRadius: 4,
          backgroundColor: mStyle.bg, color: mStyle.text, border: `1px solid ${mStyle.border}`
        }}>{ep.method}</span>
      </div>

      {/* Route */}
      <div style={{ fontWeight: 600, color: "var(--text-primary)", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }} title={ep.route}>
        {ep.route}
      </div>

      {/* Health */}
      <div>{getHealthBadge(ep.health_status)}</div>

      {/* Req/s */}
      <div style={{ fontWeight: 600, fontFamily: "monospace" }}>{ep.requests_per_second?.toFixed(2) || "0.00"} req/s</div>

      {/* Avg Latency */}
      <div style={{ fontFamily: "monospace" }}>{ep.avg_latency?.toFixed(1) || "0.0"} ms</div>

      {/* P95 */}
      <div style={{ fontFamily: "monospace" }}>{ep.p95?.toFixed(1) || "—"}</div>

      {/* Success % */}
      <div style={{ color: COLORS.healthy, fontWeight: 600 }}>{ep.success_rate != null ? `${ep.success_rate.toFixed(1)}%` : "—"}</div>

      {/* Failure % */}
      <div style={{ color: COLORS.critical, fontWeight: 600 }}>{ep.failure_rate != null ? `${ep.failure_rate.toFixed(1)}%` : "—"}</div>

      {/* Total Requests */}
      <div style={{ fontFamily: "monospace" }}>{ep.total_requests?.toLocaleString() || "0"}</div>

      {/* Codes */}
      <div style={{ color: "var(--text-muted)", fontSize: "0.72rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={statusString}>
        {statusString}
      </div>

      {/* Action */}
      <div style={{ display: "flex", justifyContent: "flex-end", color: "var(--text-muted)" }}>
        <ChevronRight size={14} />
      </div>
    </div>
  );
}, (prev, next) => {
  // Only re-render if crucial observability data has changed
  return (
    prev.ep.total_requests === next.ep.total_requests &&
    prev.ep.requests_per_second === next.ep.requests_per_second &&
    prev.ep.health_status === next.ep.health_status &&
    prev.ep.avg_latency === next.ep.avg_latency &&
    prev.ep.p95 === next.ep.p95 &&
    prev.ep.last_status_code === next.ep.last_status_code
  );
});

// Group Headers Component
const ApiGroupHeader = ({ name, count, health, totalReqs, avgLatency, isExpanded, onToggle }) => {
  const getGroupHealthColor = () => {
    if (health === "critical") return COLORS.critical;
    if (health === "warning") return COLORS.warning;
    if (health === "healthy") return COLORS.healthy;
    return COLORS.noTraffic;
  };

  return (
    <div
      onClick={onToggle}
      style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 16px", backgroundColor: "var(--bg-card)",
        border: "1px solid var(--border)", borderRadius: 6, cursor: "pointer",
        userSelect: "none", marginBottom: 6, transition: "background 0.2s"
      }}
      onMouseEnter={e => e.currentTarget.style.backgroundColor = "var(--bg-hover)"}
      onMouseLeave={e => e.currentTarget.style.backgroundColor = "var(--bg-card)"}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span style={{ fontWeight: 700, fontSize: "0.85rem", color: "var(--text-primary)" }}>{name}</span>
        <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>({count} endpoints)</span>
        <span style={{
          width: 8, height: 8, borderRadius: "50%",
          backgroundColor: getGroupHealthColor(),
          boxShadow: `0 0 5px ${getGroupHealthColor()}`
        }} />
      </div>
      
      <div style={{ display: "flex", gap: 24, fontSize: "0.75rem", color: "var(--text-secondary)" }}>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Total Requests: </span>
          <strong style={{ fontFamily: "monospace" }}>{totalReqs.toLocaleString()}</strong>
        </div>
        <div>
          <span style={{ color: "var(--text-muted)" }}>Avg Latency: </span>
          <strong style={{ fontFamily: "monospace" }}>{avgLatency.toFixed(1)} ms</strong>
        </div>
      </div>
    </div>
  );
};

// Endpoint Details Component (Observer Mode)
const ApiEndpointDetails = ({ ep, history, onBack }) => {
  const mStyle = METHOD_COLORS[ep.method] || METHOD_COLORS.GET;
  const statusCodes = ep.status_codes || {};
  const failureHistory = Array.isArray(ep.failure_history) ? ep.failure_history : [];

  // Helper for safe time formatting
  const formatTime = (ts) => {
    if (!ts) return "—";
    try {
      const d = new Date(ts);
      return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString();
    } catch (_) {
      return "—";
    }
  };

  // Recharts structured metrics
  const chartData = useMemo(() => {
    if (!Array.isArray(history) || history.length === 0) {
      return [{ timestamp: new Date().toLocaleTimeString(), rps: 0, latency: 0 }];
    }
    return history;
  }, [history]);

  const pieData = useMemo(() => {
    return Object.entries(statusCodes).map(([code, count]) => ({
      name: `HTTP ${code}`,
      value: count || 0,
      color: code.startsWith("2") ? COLORS.healthy : code.startsWith("5") ? COLORS.critical : COLORS.warning
    }));
  }, [statusCodes]);

  const donutData = useMemo(() => [
    { name: "Success", value: ep.success_count || 0, color: COLORS.healthy },
    { name: "Failure", value: ep.failure_count || 0, color: COLORS.critical }
  ], [ep.success_count, ep.failure_count]);

  return (
    <div className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Detail Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, borderBottom: "1px solid var(--border)", paddingBottom: 14 }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack} style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <ArrowLeft size={14} /> Back to Explorer
        </button>
        <span style={{
          fontWeight: 700, fontSize: "0.75rem", padding: "3px 8px", borderRadius: 4,
          backgroundColor: mStyle.bg, color: mStyle.text, border: `1px solid ${mStyle.border}`
        }}>{ep.method}</span>
        <h2 style={{ fontSize: "1.2rem", fontWeight: 700, margin: 0, color: "var(--text-primary)", flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>
          {ep.route}
        </h2>
        {ep.health_status === "healthy" && <span className="badge badge-green"><span className="status-dot dot-green" />Healthy</span>}
        {ep.health_status === "warning" && <span className="badge badge-yellow"><span className="status-dot dot-yellow" />Warning</span>}
        {ep.health_status === "critical" && <span className="badge badge-red"><span className="status-dot dot-red" />Critical</span>}
        {ep.health_status === "no_traffic" && <span className="badge badge-gray"><span className="status-dot dot-gray" />No Traffic</span>}
      </div>

      {/* Overview Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12 }}>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Requests / Sec</span>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--text-primary)", fontFamily: "monospace" }}>
            {ep.requests_per_second?.toFixed(2) || "0.00"}
          </div>
        </div>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Avg Latency</span>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--text-primary)", fontFamily: "monospace" }}>
            {ep.avg_latency?.toFixed(1) || "0.0"} ms
          </div>
        </div>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>P95 Latency</span>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--text-primary)", fontFamily: "monospace" }}>
            {ep.p95?.toFixed(1) || "—"} ms
          </div>
        </div>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>P99 Latency</span>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "var(--text-primary)", fontFamily: "monospace" }}>
            {ep.p99?.toFixed(1) || "—"} ms
          </div>
        </div>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Min / Max Latency</span>
          <div style={{ fontSize: "1rem", fontWeight: 700, color: "var(--text-primary)", fontFamily: "monospace", paddingTop: 3 }}>
            {ep.min_latency?.toFixed(0) || "—"} / {ep.max_latency?.toFixed(0) || "—"} ms
          </div>
        </div>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Success Rate</span>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: COLORS.healthy }}>
            {ep.success_rate?.toFixed(1) || "0.0"}%
          </div>
        </div>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Active Requests</span>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: COLORS.blue, fontFamily: "monospace" }}>
            {ep.active_requests || 0}
          </div>
        </div>
        <div className="stat-card" style={{ padding: "10px 14px" }}>
          <span style={{ fontSize: "0.72rem", color: "var(--text-muted)", display: "block", marginBottom: 4 }}>Last Status Code</span>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: ep.last_status_code?.toString().startsWith("2") ? COLORS.healthy : COLORS.critical, fontFamily: "monospace" }}>
            {ep.last_status_code || "—"}
          </div>
        </div>
      </div>

      {/* Row 1 — Timelines (RPS/Latency and Cumulative Requests) */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(450px, 1fr))", gap: 16, marginBottom: 16 }}>
        {/* Requests & Latency Live Line/Area Chart */}
        <div className="card" style={{ height: 300 }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <TrendingUp size={14} color="var(--primary)" /> API Traffic (Req/sec & Latency)
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorRps" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={COLORS.blue} stopOpacity={0.3}/>
                  <stop offset="95%" stopColor={COLORS.blue} stopOpacity={0.0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.gridLine} />
              <XAxis dataKey="timestamp" tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
              <YAxis yAxisId="left" tick={{ fontSize: 9, fill: "var(--text-muted)" }} label={{ value: 'req/s', angle: -90, position: 'insideLeft', style: {fontSize: 10, fill: "var(--text-muted)"} }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 9, fill: "var(--text-muted)" }} label={{ value: 'ms', angle: 90, position: 'insideRight', style: {fontSize: 10, fill: "var(--text-muted)"} }} />
              <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--border)", fontSize: "0.75rem", color: "var(--text-primary)" }} />
              <Area yAxisId="left" type="monotone" dataKey="rps" stroke={COLORS.blue} fillOpacity={1} fill="url(#colorRps)" name="Requests/sec" />
              <Line yAxisId="right" type="monotone" dataKey="latency" stroke={COLORS.purple} dot={false} strokeWidth={2} name="Latency (ms)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Requests Count Line Chart */}
        <div className="card" style={{ height: 300 }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <Database size={14} color="var(--primary)" /> Cumulative Requests over Time
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.gridLine} />
              <XAxis dataKey="timestamp" tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
              <YAxis tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
              <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--border)", fontSize: "0.75rem", color: "var(--text-primary)" }} />
              <Line type="monotone" dataKey="requests" stroke={COLORS.magenta} strokeWidth={2} dot={false} name="Total Requests" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Row 2 — Distribution & Analysis (Ratio, Status Codes, Latency bars) */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16, marginBottom: 16 }}>
        {/* Donut Chart: Success vs Failure */}
        <div className="card" style={{ height: 280, display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <CheckCircle size={14} color="var(--primary)" /> Success vs Failure Ratio
          </div>
          <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "space-around" }}>
            {((ep.success_count || 0) === 0 && (ep.failure_count || 0) === 0) ? (
              <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>No request telemetry</span>
            ) : (
              <>
                <div style={{ width: "50%", height: 180 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={donutData} dataKey="value" innerRadius={45} outerRadius={65} paddingAngle={2}>
                        {donutData.map((d, index) => <Cell key={index} fill={d.color} />)}
                      </Pie>
                      <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--border)", fontSize: "0.75rem", color: "var(--text-primary)" }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ fontSize: "0.75rem", display: "flex", flexDirection: "column", gap: 6 }}>
                  <div>
                    <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", backgroundColor: COLORS.healthy, marginRight: 6 }} />
                    Success ({ep.success_count || 0})
                  </div>
                  <div>
                    <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", backgroundColor: COLORS.critical, marginRight: 6 }} />
                    Failure ({ep.failure_count || 0})
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* HTTP Status Code Distribution */}
        <div className="card" style={{ height: 280, display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <Database size={14} color="var(--primary)" /> Status Code Distribution
          </div>
          <div style={{ display: "flex", flex: 1, alignItems: "center", justifyContent: "space-around" }}>
            {pieData.length === 0 ? (
              <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>No HTTP responses recorded</span>
            ) : (
              <>
                <div style={{ width: "50%", height: 180 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={60} label={{ fontSize: 9 }}>
                        {pieData.map((d, index) => <Cell key={index} fill={d.color} />)}
                      </Pie>
                      <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--border)", fontSize: "0.75rem", color: "var(--text-primary)" }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ fontSize: "0.72rem", display: "flex", flexDirection: "column", gap: 6, maxHeight: 150, overflowY: "auto" }}>
                  {pieData.map((d, index) => (
                    <div key={index}>
                      <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", backgroundColor: d.color, marginRight: 6 }} />
                      {d.name}: {d.value}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Latency Threshold Analysis */}
        <div className="card" style={{ height: 280, display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <Clock size={14} color="var(--primary)" /> Latency Analysis
          </div>
          
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ padding: "8px 12px", backgroundColor: "var(--bg-surface)", borderRadius: 6 }}>
              <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", display: "block" }}>Latency Status</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: "50%",
                  backgroundColor: ep.avg_latency > 300 ? COLORS.critical : ep.avg_latency > 100 ? COLORS.warning : COLORS.healthy
                }} />
                <span style={{ fontSize: "0.78rem", fontWeight: 600 }}>
                  {ep.avg_latency > 300 ? "High Latency Warning" : ep.avg_latency > 100 ? "Degraded Performance" : "Nominal Performance"}
                </span>
              </div>
            </div>

            {/* Threshold bars */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {[
                { label: "Min Latency", val: ep.min_latency || 0, color: COLORS.healthy },
                { label: "Avg Latency", val: ep.avg_latency || 0, color: ep.avg_latency > 200 ? COLORS.warning : COLORS.blue },
                { label: "P95 Latency", val: ep.p95 || 0, color: ep.p95 > 300 ? COLORS.orange : COLORS.purple },
                { label: "Max Latency", val: ep.max_latency || 0, color: COLORS.critical }
              ].map(bar => (
                <div key={bar.label}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.68rem", marginBottom: 2 }}>
                    <span style={{ color: "var(--text-muted)" }}>{bar.label}</span>
                    <span style={{ fontWeight: 600 }}>{bar.val.toFixed(1)} ms</span>
                  </div>
                  <div style={{ height: 4, backgroundColor: "var(--border)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${Math.min(100, (bar.val / 600) * 100)}%`, backgroundColor: bar.color, borderRadius: 2 }} />
                  </div>
                </div>
              ))}
            </div>
            
            <div style={{ fontSize: "0.65rem", color: "var(--text-muted)", borderTop: "1px dashed var(--border)", paddingTop: 8 }}>
              <Info size={11} style={{ verticalAlign: "middle", marginRight: 4 }} />
              Calculated over a running 100-request window.
            </div>
          </div>
        </div>
      </div>

      {/* Row 3 — Failures Timeline & Future Charts Placeholder */}
      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 16, marginBottom: 16 }}>
        {/* Failures & Timeline */}
        <div className="card" style={{ display: "flex", flexDirection: "column", height: 320 }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
            <ShieldAlert size={14} color={COLORS.critical} /> Failure Observability
          </div>
          
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12, overflowY: "auto", maxHeight: 260 }}>
            {(ep.latest_error_message || ep.latest_failure_information) && (
              <div style={{ padding: 12, backgroundColor: "rgba(239, 68, 68, 0.05)", border: `1px solid ${COLORS.critical}30`, borderRadius: 6, display: "flex", flexDirection: "column", gap: 6 }}>
                <div>
                  <span style={{ fontSize: "0.7rem", fontWeight: 700, color: COLORS.critical, display: "block", textTransform: "uppercase", marginBottom: 4 }}>Latest Error</span>
                  <div style={{ fontSize: "0.78rem", fontWeight: 600, color: "var(--text-primary)" }}>{ep.latest_error_message || "Failed Request"}</div>
                </div>
                {ep.latest_failure_information && (
                  <div>
                    <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "var(--text-muted)", display: "block", textTransform: "uppercase", marginBottom: 2 }}>Failure Information</span>
                    <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", fontFamily: "monospace", whiteSpace: "pre-wrap" }}>
                      {typeof ep.latest_failure_information === "object"
                        ? JSON.stringify(ep.latest_failure_information, null, 2)
                        : String(ep.latest_failure_information)
                      }
                    </div>
                  </div>
                )}
                {ep.latest_exception && (
                  <div>
                    <span style={{ fontSize: "0.7rem", fontWeight: 700, color: "var(--text-muted)", display: "block", textTransform: "uppercase", marginBottom: 2 }}>Exception</span>
                    <code style={{ fontSize: "0.68rem", color: "var(--text-muted)", display: "block", whiteSpace: "pre-wrap", overflowX: "auto" }}>{ep.latest_exception}</code>
                  </div>
                )}
              </div>
            )}

            {failureHistory.length === 0 ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flex: 1, color: "var(--text-muted)", padding: 20 }}>
                <CheckCircle size={28} color={COLORS.healthy} style={{ marginBottom: 6 }} />
                <span style={{ fontSize: "0.78rem" }}>No failures logged. Endpoint is healthy.</span>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <span style={{ fontSize: "0.72rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>Failure History Logs</span>
                {failureHistory.map((item, idx) => {
                  if (!item) return null;
                  return (
                    <div key={idx} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "8px 10px", borderLeft: `3px solid ${COLORS.critical}`, backgroundColor: "var(--bg-surface)", fontSize: "0.72rem" }}>
                      <div style={{ color: "var(--text-muted)", fontFamily: "monospace", flexShrink: 0 }}>{formatTime(item.timestamp)}</div>
                      <div style={{ flex: 1 }}>
                        <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{item.message || "Failed Request"}</span>
                        {item.exception && <div style={{ fontSize: "0.65rem", color: "var(--text-muted)", marginTop: 2, fontFamily: "monospace" }}>{item.exception}</div>}
                      </div>
                      <span className="badge badge-red" style={{ fontSize: "0.65rem" }}>HTTP {item.status_code || 500}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Future chart placeholder (Payload Size Distribution) */}
        <div className="card" style={{ height: 320, display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--text-primary)", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <TrendingUp size={14} color="var(--primary)" /> Network Payload Insights
            </span>
            <span className="badge badge-blue" style={{ fontSize: "0.62rem", padding: "2px 6px", borderRadius: 4 }}>BETA PREVIEW</span>
          </div>
          
          <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div style={{ fontSize: "0.72rem", color: "var(--text-secondary)", marginBottom: 6 }}>
              Payload transfer sizes distributed over running requests.
            </div>
            
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={[
                { range: "< 1 KB", count: 1420 },
                { range: "1-10 KB", count: 3840 },
                { range: "10-100 KB", count: 920 },
                { range: "100 KB+", count: 150 }
              ]}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="range" tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
                <YAxis tick={{ fontSize: 9, fill: "var(--text-muted)" }} />
                <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", border: "1px solid var(--border)", fontSize: "0.75rem", color: "var(--text-primary)" }} />
                <Bar dataKey="count" fill="var(--primary)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            
            <div style={{ fontSize: "0.68rem", color: "var(--text-muted)", borderTop: "1px dashed var(--border)", paddingTop: 8, marginTop: 6 }}>
              <Info size={12} style={{ verticalAlign: "middle", marginRight: 4 }} />
              Bandwidth metrics streaming logic will activate in next minor agent release.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// Main ApiMonitorPage Layout
const ApiMonitorPage = () => {
  const { authFetch } = useAuth();
  
  const [snapshot, setSnapshot] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEndpoint, setSelectedEndpoint] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  const [historyData, setHistoryData] = useState({});

  const [filters, setFilters] = useState({
    health: "All",
    method: "All",
    statusCode: "All",
    latency: "All",
    traffic: "All"
  });

  const [sorting, setSorting] = useState({
    by: "route", // route | requests | rps | latency | successRate | failureRate | lastCalled
    order: "asc" // asc | desc
  });

  // Fetch Endpoint telemetry snapshot
  const fetchSnapshot = useCallback(async () => {
    try {
      const res = await authFetch("/snapshot");
      if (res.ok) {
        const data = await res.json();
        setSnapshot(data);
        setError(null);
      } else {
        throw new Error("HTTP snapshot pull failed");
      }
    } catch (err) {
      console.error(err);
      setError("Failed to fetch API metrics snapshot. Reconnecting...");
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  // Handle live updates every 1 second
  useEffect(() => {
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, 1000);
    return () => clearInterval(interval);
  }, [fetchSnapshot]);

  // Maintain Rolling Metrics History for charts
  useEffect(() => {
    if (!snapshot?.api?.endpoints) return;

    setHistoryData(prev => {
      const updated = { ...prev };
      const nowStr = new Date().toLocaleTimeString();

      snapshot.api.endpoints.forEach(ep => {
        const key = `${ep.method}-${ep.route}`;
        const currentHistory = updated[key] || [];

        const newPoint = {
          timestamp: nowStr,
          requests: ep.total_requests || 0,
          latency: ep.avg_latency || 0,
          rps: ep.requests_per_second || 0
        };

        // Maintain the last 30 data points
        updated[key] = [...currentHistory, newPoint].slice(-30);
      });

      return updated;
    });
  }, [snapshot]);

  // Extract endpoints array from snapshot safely
  const endpoints = useMemo(() => {
    return snapshot?.api?.endpoints || [];
  }, [snapshot]);

  // Apply search filtering
  const filteredEndpoints = useMemo(() => {
    return endpoints.filter(ep => matchEndpoint(ep, searchQuery, filters));
  }, [endpoints, searchQuery, filters]);

  // Apply sorting
  const sortedEndpoints = useMemo(() => {
    const sorted = [...filteredEndpoints];
    sorted.sort((a, b) => {
      let valA, valB;

      switch (sorting.by) {
        case "requests":
          valA = a.total_requests || 0;
          valB = b.total_requests || 0;
          break;
        case "rps":
          valA = a.requests_per_second || 0;
          valB = b.requests_per_second || 0;
          break;
        case "latency":
          valA = a.avg_latency || 0;
          valB = b.avg_latency || 0;
          break;
        case "successRate":
          valA = a.success_rate || 0;
          valB = b.success_rate || 0;
          break;
        case "failureRate":
          valA = a.failure_rate || 0;
          valB = b.failure_rate || 0;
          break;
        case "lastCalled":
          valA = a.last_called ? new Date(a.last_called).getTime() : 0;
          valB = b.last_called ? new Date(b.last_called).getTime() : 0;
          break;
        default:
          valA = a.route || "";
          valB = b.route || "";
      }

      if (typeof valA === "string") {
        return sorting.order === "asc"
          ? valA.localeCompare(valB)
          : valB.localeCompare(valA);
      }

      return sorting.order === "asc" ? valA - valB : valB - valA;
    });
    return sorted;
  }, [filteredEndpoints, sorting]);

  // Group Endpoints automatically
  const groupedEndpoints = useMemo(() => {
    const groups = {};
    sortedEndpoints.forEach(ep => {
      const gName = categorizeRoute(ep.route);
      if (!groups[gName]) {
        groups[gName] = {
          endpoints: [],
          health: "healthy",
          totalReqs: 0,
          sumLatency: 0,
          latencyCount: 0
        };
      }

      groups[gName].endpoints.push(ep);
      groups[gName].totalReqs += ep.total_requests || 0;
      if (ep.total_requests > 0) {
        groups[gName].sumLatency += (ep.avg_latency || 0) * (ep.total_requests);
        groups[gName].latencyCount += ep.total_requests;
      }

      // Propagate critical/warning state upward
      if (ep.health_status === "critical") {
        groups[gName].health = "critical";
      } else if (ep.health_status === "warning" && groups[gName].health !== "critical") {
        groups[gName].health = "warning";
      } else if (ep.health_status === "no_traffic" && groups[gName].health === "healthy" && groups[gName].endpoints.every(item => item.health_status === "no_traffic")) {
        groups[gName].health = "no_traffic";
      }
    });

    // Compute average latencies for groups
    Object.keys(groups).forEach(k => {
      const g = groups[k];
      g.avgLatency = g.latencyCount > 0 ? g.sumLatency / g.latencyCount : 0;
    });

    return groups;
  }, [sortedEndpoints]);

  // Sync selected endpoint when snapshot polling updates it
  const currentSelectedEndpoint = useMemo(() => {
    if (!selectedEndpoint) return null;
    return endpoints.find(
      ep => ep.route === selectedEndpoint.route && ep.method === selectedEndpoint.method
    ) || selectedEndpoint;
  }, [endpoints, selectedEndpoint]);

  const handleToggleSort = (field) => {
    setSorting(prev => ({
      by: field,
      order: prev.by === field && prev.order === "asc" ? "desc" : "asc"
    }));
  };

  const handleToggleGroup = (group) => {
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  return (
    <div className="page-container fade-in" style={{
      display: "flex",
      flexDirection: "column",
      height: "auto",
      overflow: "visible",
      gap: 0,
      paddingBottom: 32
    }}>
      {/* Connection Failure Status */}
      {error && (
        <div style={{
          padding: "10px 18px", backgroundColor: "rgba(239, 68, 68, 0.1)",
          border: `1px solid ${COLORS.critical}40`, borderRadius: 8,
          marginBottom: 16, display: "flex", alignItems: "center", gap: 10,
          fontSize: "0.8rem", color: "var(--text-primary)", flexShrink: 0
        }}>
          <WifiOff size={15} color={COLORS.critical} />
          {error}
        </div>
      )}

      {/* Main Title & Sync status - Fixed at top */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexShrink: 0 }}>
        <div>
          <div className="page-title">API Monitor</div>
          <div className="page-subtitle" style={{ marginTop: 2 }}>
            Real-time API performance telemetry and endpoint health monitoring.
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.75rem", color: "var(--text-muted)" }}>
          <RefreshCw size={13} style={{ animation: "spin 1s linear infinite" }} />
          Polling 1s
        </div>
      </div>

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, flex: 1 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
            <div className="skeleton" style={{ height: 60, borderRadius: 6 }} />
            <div className="skeleton" style={{ height: 60, borderRadius: 6 }} />
            <div className="skeleton" style={{ height: 60, borderRadius: 6 }} />
            <div className="skeleton" style={{ height: 60, borderRadius: 6 }} />
          </div>
          <div className="skeleton" style={{ height: 300, borderRadius: 8, flex: 1 }} />
        </div>
      ) : endpoints.length === 0 ? (
        <div className="empty-state" style={{ padding: 48 }}>
          <div className="empty-state-icon"><Activity size={48} /></div>
          <h3>No API telemetry available</h3>
          <p>Please wait for HexaAgent to start monitoring APIs and ingest requests.</p>
        </div>
      ) : currentSelectedEndpoint ? (
        /* Selected Endpoint Detail View */
        <ApiEndpointDetails
          ep={currentSelectedEndpoint}
          history={historyData[`${currentSelectedEndpoint.method}-${currentSelectedEndpoint.route}`]}
          onBack={() => setSelectedEndpoint(null)}
        />
      ) : (
        /* Endpoint Explorer List View with Sticky Header and Scrollable Rows */
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          
          {/* KPI Cards (scroll away normally) */}
          <ApiOverviewCards endpoints={endpoints} />

          {/* Sticky Search, Filters, and Table Header */}
          <div style={{
            position: "sticky",
            top: "var(--header-h)",
            zIndex: 40,
            backgroundColor: "var(--bg-base)",
            paddingTop: "12px",
            paddingBottom: "8px"
          }}>
            <div style={{
              borderRadius: "8px 8px 0 0",
              borderTop: "1px solid var(--border)",
              borderLeft: "1px solid var(--border)",
              borderRight: "1px solid var(--border)",
              overflow: "hidden"
            }}>
              <ApiFilterBar
                search={searchQuery}
                setSearch={setSearchQuery}
                filters={filters}
                setFilters={setFilters}
              />

              {/* List Headers */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "80px 1.5fr 110px 100px 90px 90px 90px 100px 1fr 40px",
                gap: 12, alignItems: "center", padding: "12px 16px",
                backgroundColor: "var(--bg-surface)", borderBottom: "1px solid var(--border)",
                fontSize: "0.68rem", fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase"
              }}>
                <div>Method</div>
                <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }} onClick={() => handleToggleSort("route")}>
                  Route <ArrowUpDown size={10} />
                </div>
                <div>Health</div>
                <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }} onClick={() => handleToggleSort("rps")}>
                  Req/Sec <ArrowUpDown size={10} />
                </div>
                <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }} onClick={() => handleToggleSort("latency")}>
                  Avg Latency <ArrowUpDown size={10} />
                </div>
                <div>P95</div>
                <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }} onClick={() => handleToggleSort("successRate")}>
                  Success % <ArrowUpDown size={10} />
                </div>
                <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }} onClick={() => handleToggleSort("failureRate")}>
                  Failure % <ArrowUpDown size={10} />
                </div>
                <div style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 4 }} onClick={() => handleToggleSort("requests")}>
                  Total Req <ArrowUpDown size={10} />
                </div>
                <div>Codes</div>
                <div></div>
              </div>
            </div>
          </div>

          {/* List Content Rows (non-sticky, scroll underneath) */}
          <div style={{
            backgroundColor: "var(--bg-card)",
            borderLeft: "1px solid var(--border)",
            borderRight: "1px solid var(--border)",
            borderBottom: "1px solid var(--border)",
            borderRadius: "0 0 8px 8px",
            marginTop: "-8px"
          }}>
            <div style={{ padding: "8px 12px" }}>
              {filteredEndpoints.length === 0 ? (
                <div style={{ padding: 48, textAlign: "center", color: "var(--text-muted)" }}>
                  <Search size={28} style={{ marginBottom: 6 }} />
                  <p style={{ fontSize: "0.85rem", margin: 0 }}>No endpoints match your filters.</p>
                </div>
              ) : (
                Object.entries(groupedEndpoints).map(([groupName, group]) => {
                  const isExpanded = expandedGroups[groupName] !== false; // Default expanded
                  return (
                    <div key={groupName} style={{ marginBottom: 12 }}>
                      <ApiGroupHeader
                        name={groupName}
                        count={group.endpoints.length}
                        health={group.health}
                        totalReqs={group.totalReqs}
                        avgLatency={group.avgLatency}
                        isExpanded={isExpanded}
                        onToggle={() => handleToggleGroup(groupName)}
                      />
                      {isExpanded && (
                        <div style={{ paddingLeft: 12, borderLeft: "2px solid var(--border)", display: "flex", flexDirection: "column" }}>
                          {group.endpoints.map(ep => (
                            <ApiEndpointRow
                              key={`${ep.method}-${ep.route}`}
                              ep={ep}
                              onSelect={setSelectedEndpoint}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ApiMonitorPage;
