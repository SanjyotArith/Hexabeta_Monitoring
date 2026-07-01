import React, { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { 
  Server, 
  Activity, 
  Globe, 
  AlertOctagon, 
  CheckCircle2, 
  AlertTriangle, 
  Clock, 
  RefreshCw 
} from "lucide-react";
import { 
  ResponsiveContainer, 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  Tooltip, 
  CartesianGrid 
} from "recharts";

const Dashboard = ({ selectedEnv, selectedProject }) => {
  const { authFetch } = useAuth();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({
    cpu: 0,
    ramPercent: 0,
    diskPercent: 0,
    activeIncidents: 0,
    onlineServices: 0,
    totalServices: 5,
    apiUptime: 100,
    agentUptime: "Offline",
  });
  
  const [services, setServices] = useState([
    { name: "Backend API", status: "stopped", cpu: 0, ram: "0 MB", details: "launchd plist stopped" },
    { name: "Nginx", status: "unknown", cpu: 0, ram: "0 MB", details: "No agent telemetry" },
    { name: "PostgreSQL", status: "unknown", cpu: 0, ram: "0 MB", details: "No agent telemetry" },
    { name: "MongoDB", status: "unknown", cpu: 0, ram: "0 MB", details: "No agent telemetry" },
    { name: "Cloudflare Tunnel", status: "unknown", cpu: 0, ram: "0 MB", details: "No agent telemetry" },
  ]);

  const [incidents, setIncidents] = useState([]);
  const [latencyData, setLatencyData] = useState([]);
  const [activeMachine, setActiveMachine] = useState(null);
  const [activeCheck, setActiveCheck] = useState(null);

  const loadDashboardData = async () => {
    if (!selectedEnv) return;
    setLoading(true);
    try {
      // 1. Fetch active incidents
      const incRes = await authFetch(`/incidents/environments/${selectedEnv.id}/active`);
      let activeIncCount = 0;
      if (incRes.ok) {
        const incData = await incRes.ok ? await incRes.json() : [];
        setIncidents(incData);
        activeIncCount = incData.length;
      }

      // 2. Fetch Machines (to read core metrics from the agent)
      const machinesRes = await authFetch(`/machines/environments/${selectedEnv.id}/machines`);
      if (machinesRes.ok) {
        const machines = await machinesRes.json();
        const mainMachine = machines[0];
        setActiveMachine(mainMachine || null);
        if (mainMachine) {
          // Fetch current metrics
          const metricsRes = await authFetch(`/metrics/machines/${mainMachine.id}/current`);
          const metrics = metricsRes.ok ? await metricsRes.json() : null;

          // Fetch services
          const servicesRes = await authFetch(`/services/machines/${mainMachine.id}`);
          const servicesData = servicesRes.ok ? await servicesRes.json() : [];
          
          if (servicesData.length > 0) {
            setServices(servicesData.map(s => ({
              name: s.name,
              status: s.is_active ? "running" : "stopped",
              cpu: 0,
              ram: "0 MB"
            })));
          } else {
            setServices([]);
          }

          if (metrics) {
            const ramPct = (metrics.ram_used_bytes / metrics.ram_total_bytes) * 100;
            const diskPct = (metrics.disk_used_bytes / metrics.disk_total_bytes) * 100;
            setStats(prev => ({
              ...prev,
              cpu: metrics.cpu_usage,
              ramPercent: ramPct,
              diskPercent: diskPct,
              activeIncidents: activeIncCount,
              agentUptime: "Online"
            }));
          } else {
            setStats(prev => ({
              ...prev,
              cpu: 0,
              ramPercent: 0,
              diskPercent: 0,
              activeIncidents: activeIncCount,
              agentUptime: "Online"
            }));
          }
        } else {
          setServices([]);
          setStats(prev => ({
            ...prev,
            cpu: 0,
            ramPercent: 0,
            diskPercent: 0,
            activeIncidents: activeIncCount,
            agentUptime: "Offline"
          }));
        }
      }

      // 3. Fetch Synthetic API Checks to build latency curve
      const apiChecksRes = await authFetch(`/api-checks/environments/${selectedEnv.id}`);
      if (apiChecksRes.ok) {
        const checks = await apiChecksRes.json();
        const mainCheck = checks[0];
        setActiveCheck(mainCheck || null);
        if (mainCheck) {
          const histRes = await authFetch(`/api-checks/${mainCheck.id}/history?limit=15`);
          if (histRes.ok) {
            const history = await histRes.json();
            const chartPoints = history.map(h => ({
              time: new Date(h.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              latency: h.response_time_ms || 0
            })).reverse();
            setLatencyData(chartPoints);
            
            const upCount = history.filter(h => h.is_up).length;
            const pct = history.length > 0 ? (upCount / history.length) * 100 : 100;
            setStats(prev => ({ ...prev, apiUptime: pct }));
          }
        } else {
          setLatencyData([]);
          setStats(prev => ({ ...prev, apiUptime: 100 }));
        }
      }

    } catch (err) {
      console.error("Dashboard reload failed:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboardData();
    
    // Listen to scope change
    window.addEventListener("hexamonitor_env_changed", loadDashboardData);
    return () => {
      window.removeEventListener("hexamonitor_env_changed", loadDashboardData);
    };
  }, [selectedEnv]);

  const handleAcknowledge = async (incidentId) => {
    try {
      const res = await authFetch(`/incidents/${incidentId}/acknowledge`, { method: "POST" });
      if (res.ok) loadDashboardData();
    } catch (err) {
      console.error("Error acknowledging incident:", err);
    }
  };

  const getStatusColor = (status) => {
    if (status === "running" || status === "online") return "var(--color-success)";
    if (status === "degraded" || status === "warning") return "var(--color-warning)";
    return "var(--color-critical)";
  };

  return (
    <div className="page-container fade-in">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em" }}>
            {selectedProject ? `${selectedProject.name} Infrastructure Health` : "Infrastructure Health"}
          </h1>
          <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", marginTop: "0.25rem" }}>
            Real-time status overview of {activeMachine ? activeMachine.name : "active host"} server and hosted systems.
          </p>
        </div>
        <button className="btn" onClick={loadDashboardData} disabled={loading}>
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          <span>Refresh Data</span>
        </button>
      </div>

      {/* Overview Cards Row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1.5rem" }}>
        
        {/* Card 1: Agent State */}
        <div className="card">
          <div className="card-title">
            <span>Agent Status</span>
            <Server size={18} color="var(--color-info)" />
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.75rem", fontWeight: 700 }}>
              {stats.agentUptime}
            </span>
          </div>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.5rem", display: "flex", alignItems: "center", gap: "0.375rem" }}>
            <span className={`status-dot ${stats.agentUptime === "Online" ? "success" : "critical"}`} />
            <span>Telemetry link on {activeMachine ? activeMachine.name : "active host"}</span>
          </p>
        </div>

        {/* Card 2: Services Status */}
        <div className="card">
          <div className="card-title">
            <span>Uptime Services</span>
            <Activity size={18} color="var(--color-success)" />
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.75rem", fontWeight: 700 }}>
              {services.filter(s => s.status === "running").length}
            </span>
            <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>/ {services.length} active</span>
          </div>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.5rem" }}>
            launchd system and DB daemons
          </p>
        </div>

        {/* Card 3: Synthetic Ping */}
        <div className="card">
          <div className="card-title">
            <span>API Route Uptime</span>
            <Globe size={18} color="var(--color-success)" />
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.75rem", fontWeight: 700 }}>
              {stats.apiUptime.toFixed(1)}%
            </span>
          </div>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.5rem" }}>
            Synthetic HTTP checks (past 15 runs)
          </p>
        </div>

        {/* Card 4: Active Warnings */}
        <div className="card" style={{ borderColor: stats.activeIncidents > 0 ? "var(--color-critical)" : "var(--border-color)" }}>
          <div className="card-title">
            <span>Active Incidents</span>
            <AlertOctagon size={18} color={stats.activeIncidents > 0 ? "var(--color-critical)" : "var(--text-muted)"} />
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.75rem", fontWeight: 700, color: stats.activeIncidents > 0 ? "var(--color-critical)" : "inherit" }}>
              {stats.activeIncidents}
            </span>
            <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>alerts requiring triage</span>
          </div>
          <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.5rem" }}>
            Slack pages will trigger on crit
          </p>
        </div>

      </div>

      {/* Middle Section: Gauges and Latency Curves */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: "1.5rem", alignItems: "stretch" }}>
        
        {/* Core Hardware Metrics */}
        <div className="card" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div className="card-title">
            <span>Server Utilization</span>
            <Server size={16} color="var(--text-muted)" />
          </div>
          
          <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem", padding: "0.5rem 0" }}>
            {/* CPU Bar */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8125rem", marginBottom: "0.375rem" }}>
                <span style={{ fontWeight: 500 }}>CPU Usage</span>
                <span className="text-mono" style={{ fontWeight: 600 }}>{stats.cpu.toFixed(1)}%</span>
              </div>
              <div style={{ height: "8px", backgroundColor: "var(--bg-tertiary)", borderRadius: "9999px", overflow: "hidden" }}>
                <div style={{ 
                  height: "100%", 
                  width: `${stats.cpu}%`, 
                  backgroundColor: stats.cpu > 80 ? "var(--color-critical)" : "var(--color-info)",
                  transition: "width 0.5s ease-out" 
                }} />
              </div>
            </div>

            {/* RAM Bar */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8125rem", marginBottom: "0.375rem" }}>
                <span style={{ fontWeight: 500 }}>Memory (RAM)</span>
                <span className="text-mono" style={{ fontWeight: 600 }}>{stats.ramPercent.toFixed(1)}%</span>
              </div>
              <div style={{ height: "8px", backgroundColor: "var(--bg-tertiary)", borderRadius: "9999px", overflow: "hidden" }}>
                <div style={{ 
                  height: "100%", 
                  width: `${stats.ramPercent}%`, 
                  backgroundColor: stats.ramPercent > 85 ? "var(--color-critical)" : "var(--color-success)",
                  transition: "width 0.5s ease-out" 
                }} />
              </div>
            </div>

            {/* Disk Space Bar */}
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8125rem", marginBottom: "0.375rem" }}>
                <span style={{ fontWeight: 500 }}>Disk Utilization</span>
                <span className="text-mono" style={{ fontWeight: 600 }}>{stats.diskPercent.toFixed(1)}%</span>
              </div>
              <div style={{ height: "8px", backgroundColor: "var(--bg-tertiary)", borderRadius: "9999px", overflow: "hidden" }}>
                <div style={{ 
                  height: "100%", 
                  width: `${stats.diskPercent}%`, 
                  backgroundColor: stats.diskPercent > 90 ? "var(--color-critical)" : "var(--color-success)",
                  transition: "width 0.5s ease-out" 
                }} />
              </div>
            </div>
          </div>
          
          <div style={{ borderTop: "1px solid var(--border-color)", paddingTop: "0.75rem", fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "0.5rem" }}>
            Host: {activeMachine ? `${activeMachine.os} ${activeMachine.name}` : "No machine configured"}
          </div>
        </div>

        {/* Latency Curve Chart */}
        <div className="card" style={{ display: "flex", flexDirection: "column", height: "300px" }}>
          <div className="card-title">
            <span>Synthetic Latency Timeline</span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", fontWeight: 400 }}>
              Latency (ms) for {activeCheck ? `${activeCheck.name} (${activeCheck.url})` : "No uptime check configured"}
            </span>
          </div>
          
          <div style={{ flex: 1, width: "100%" }}>
            {latencyData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={latencyData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="latencyGlow" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--color-info)" stopOpacity={0.25}/>
                      <stop offset="95%" stopColor="var(--color-info)" stopOpacity={0.01}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" vertical={false} />
                  <XAxis dataKey="time" stroke="var(--text-muted)" fontSize={10} tickLine={false} />
                  <YAxis stroke="var(--text-muted)" fontSize={10} tickLine={false} />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: "var(--bg-secondary)", 
                      borderColor: "var(--border-color)", 
                      borderRadius: "var(--radius-md)",
                      color: "var(--text-primary)",
                      fontFamily: "var(--font-sans)",
                      fontSize: "0.75rem"
                    }} 
                  />
                  <Area 
                    type="monotone" 
                    dataKey="latency" 
                    stroke="var(--color-info)" 
                    strokeWidth={2}
                    fillOpacity={1} 
                    fill="url(#latencyGlow)" 
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex-center" style={{ height: "100%", color: "var(--text-muted)", fontSize: "0.875rem" }}>
                Waiting for synthetic api check history logs...
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Grid Row: Service status & Incident List */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem" }}>
        
        {/* Service Health Matrix */}
        <div className="card">
          <div className="card-title">
            <span>Process Status Matrix</span>
            <span className="badge badge-success">launchd</span>
          </div>
          
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {services.map((svc) => (
              <div key={svc.name} style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "0.75rem 1rem",
                backgroundColor: "rgba(255,255,255,0.01)",
                border: "1px solid var(--border-color)",
                borderRadius: "var(--radius-md)"
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <span className={`status-dot ${svc.status === 'running' ? 'success' : svc.status === 'warning' ? 'warning' : 'critical'}`} />
                  <span style={{ fontWeight: 600, fontSize: "0.875rem" }}>{svc.name}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "1.5rem", fontSize: "0.75rem", color: "var(--text-secondary)" }}>
                  <span className="text-mono">CPU: {svc.cpu || 0}%</span>
                  <span className="text-mono">RAM: {svc.ram || "0 MB"}</span>
                  <span className="badge" style={{
                    backgroundColor: svc.status === 'running' ? 'var(--color-success-glow)' : 'var(--color-critical-glow)',
                    color: svc.status === 'running' ? 'var(--color-success)' : 'var(--color-critical)',
                    padding: '0.125rem 0.375rem',
                    fontSize: '0.6875rem'
                  }}>
                    {svc.status.toUpperCase()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Triage Incidents */}
        <div className="card">
          <div className="card-title">
            <span>Triage & Alerts Center</span>
            <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)" }}>Active Incidents</span>
          </div>

          <div style={{ minHeight: "220px" }}>
            {incidents.length > 0 ? (
              <div className="table-container">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Severity</th>
                      <th>Trigger Time</th>
                      <th style={{ textAlign: "right" }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incidents.map((inc) => (
                      <tr key={inc.id}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600 }}>
                            <AlertTriangle size={14} color="var(--color-critical)" />
                            <span>{inc.title}</span>
                          </div>
                        </td>
                        <td>
                          <span className={`badge ${inc.severity === 'critical' ? 'badge-critical' : 'badge-warning'}`}>
                            {inc.severity}
                          </span>
                        </td>
                        <td className="text-mono" style={{ fontSize: "0.75rem" }}>
                          {new Date(inc.started_at).toLocaleTimeString()}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <button 
                            className="btn" 
                            style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}
                            onClick={() => handleAcknowledge(inc.id)}
                          >
                            Acknowledge
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex-center" style={{ height: "220px", flexDirection: "column", gap: "0.5rem" }}>
                <CheckCircle2 size={36} color="var(--color-success)" />
                <span style={{ color: "var(--text-secondary)", fontSize: "0.875rem" }}>All metrics and services healthy.</span>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
};

export default Dashboard;
