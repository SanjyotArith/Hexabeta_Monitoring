import React, { useState, useEffect, useCallback } from "react";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import {
  Settings as SettingsIcon, User, Shield, Sun, Moon,
  Search, Trash2, CheckCircle, XCircle, UserX, UserCheck,
  ChevronLeft, ChevronRight, AlertCircle, RefreshCw
} from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "/api/v1";

// ─── Confirm Dialog ─────────────────────────────────────────────────────────
const ConfirmDialog = ({ title, body, danger, onConfirm, onCancel }) => (
  <div className="modal-backdrop" onClick={onCancel}>
    <div className="modal" onClick={e => e.stopPropagation()}>
      <div className="modal-title">{title}</div>
      <div className="modal-body">{body}</div>
      <div className="modal-footer">
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
        <button className={`btn btn-sm ${danger ? "btn-danger" : "btn-primary"}`} onClick={onConfirm}>
          Confirm
        </button>
      </div>
    </div>
  </div>
);

// ─── Toast ──────────────────────────────────────────────────────────────────
const Toast = ({ msg, type, onClose }) => {
  useEffect(() => {
    const t = setTimeout(onClose, 3500);
    return () => clearTimeout(t);
  }, [onClose]);
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 9999,
      background: "var(--bg-card)", border: `1px solid ${type === "error" ? "rgba(239,68,68,0.4)" : "rgba(34,197,94,0.4)"}`,
      borderRadius: "var(--radius-md)", padding: "12px 18px",
      boxShadow: "var(--shadow-lg)", display: "flex", alignItems: "center", gap: 10,
      fontSize: "0.8rem", color: "var(--text-primary)", minWidth: 240,
      animation: "fadeIn 0.2s ease"
    }}>
      {type === "error"
        ? <AlertCircle size={16} color="var(--danger)" />
        : <CheckCircle size={16} color="var(--success)" />
      }
      {msg}
    </div>
  );
};

// ─── Status Badge ───────────────────────────────────────────────────────────
const ApprovalBadge = ({ status }) => {
  const map = {
    approved: "badge-green",
    pending:  "badge-yellow",
    rejected: "badge-red",
  };
  return <span className={`badge ${map[status] || "badge-gray"}`} style={{ textTransform: "capitalize" }}>{status}</span>;
};

const RoleBadge = ({ role }) => (
  <span className={`badge ${role === "admin" ? "badge-purple" : "badge-blue"}`} style={{ textTransform: "capitalize" }}>{role}</span>
);

const ActiveBadge = ({ active }) => (
  <span className={`badge ${active ? "badge-green" : "badge-gray"}`}>{active ? "Active" : "Disabled"}</span>
);

// ─── User Management Table ──────────────────────────────────────────────────
const UserManagement = () => {
  const { authFetch, user: me } = useAuth();
  const [users, setUsers]         = useState([]);
  const [loading, setLoading]     = useState(true);
  const [search, setSearch]       = useState("");
  const [filter, setFilter]       = useState("all");
  const [page, setPage]           = useState(1);
  const [toast, setToast]         = useState(null);
  const [confirm, setConfirm]     = useState(null);
  const PER_PAGE = 8;

  const showToast = (msg, type = "success") => setToast({ msg, type });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await authFetch("/auth/users");
      if (res.ok) setUsers(await res.json());
    } catch (_) {}
    setLoading(false);
  }, [authFetch]);

  useEffect(() => { load(); }, [load]);

  const doAction = async (endpoint, method = "POST", successMsg) => {
    try {
      const res = await authFetch(endpoint, { method });
      if (!res.ok) {
        const d = await res.json();
        showToast(d.detail || "Action failed", "error");
      } else {
        showToast(successMsg);
        load();
      }
    } catch (_) {
      showToast("Network error", "error");
    }
    setConfirm(null);
  };

  const confirmAnd = (cfg) => setConfirm(cfg);

  const filtered = users.filter(u => {
    const matchSearch = !search ||
      u.username.toLowerCase().includes(search.toLowerCase()) ||
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      (u.full_name || "").toLowerCase().includes(search.toLowerCase());
    const matchFilter =
      filter === "all" ? true :
      filter === "pending"  ? u.approval_status === "pending" :
      filter === "active"   ? u.is_active && u.approval_status === "approved" :
      filter === "disabled" ? !u.is_active :
      true;
    return matchSearch && matchFilter;
  });

  const pages = Math.ceil(filtered.length / PER_PAGE);
  const visible = filtered.slice((page - 1) * PER_PAGE, page * PER_PAGE);

  return (
    <div>
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}
      {confirm && (
        <ConfirmDialog
          title={confirm.title}
          body={confirm.body}
          danger={confirm.danger}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}

      <div className="table-toolbar" style={{ justifyContent: "space-between" }}>
        <div className="flex items-center gap-2">
          <div className="search-box">
            <Search size={13} className="search-icon" />
            <input className="form-input" placeholder="Search users…" value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
              style={{ paddingLeft: 30, width: 200 }} />
          </div>
          <select className="form-select" value={filter}
            onChange={e => { setFilter(e.target.value); setPage(1); }}
            style={{ width: 130 }}>
            <option value="all">All Users</option>
            <option value="pending">Pending</option>
            <option value="active">Active</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>
          <RefreshCw size={13} />
        </button>
      </div>

      <table>
        <thead>
          <tr>
            <th>User</th>
            <th>Role</th>
            <th>Status</th>
            <th>Approval</th>
            <th>Joined</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr><td colSpan={6}>
              <div style={{ display: "flex", justifyContent: "center", padding: "24px 0" }}>
                <span className="spinner" />
              </div>
            </td></tr>
          ) : visible.length === 0 ? (
            <tr><td colSpan={6}>
              <div className="empty-state" style={{ padding: "32px 0" }}>
                <User size={28} className="empty-state-icon" />
                <p>No users found</p>
              </div>
            </td></tr>
          ) : visible.map(u => (
            <tr key={u.id}>
              <td>
                <div style={{ fontWeight: 600, color: "var(--text-primary)", fontSize: "0.8rem" }}>
                  {u.full_name || u.username}
                </div>
                <div style={{ fontSize: "0.68rem", color: "var(--text-muted)" }}>{u.email}</div>
                {u.full_name && <div style={{ fontSize: "0.68rem", color: "var(--text-muted)" }}>@{u.username}</div>}
              </td>
              <td><RoleBadge role={u.role} /></td>
              <td><ActiveBadge active={u.is_active} /></td>
              <td><ApprovalBadge status={u.approval_status} /></td>
              <td style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>
                {new Date(u.created_at).toLocaleDateString()}
              </td>
              <td>
                {u.id !== me?.id ? (
                  <div className="flex items-center gap-2">
                    {u.approval_status === "pending" && (
                      <>
                        <button className="btn btn-success btn-sm" title="Approve"
                          onClick={() => confirmAnd({
                            title: "Approve User",
                            body: `Approve ${u.username}? They will be able to log in.`,
                            onConfirm: () => doAction(`/auth/users/${u.id}/approve`, "POST", `${u.username} approved`),
                          })}>
                          <CheckCircle size={12} />
                        </button>
                        <button className="btn btn-danger btn-sm" title="Reject"
                          onClick={() => confirmAnd({
                            title: "Reject User",
                            body: `Reject ${u.username}'s registration?`,
                            danger: true,
                            onConfirm: () => doAction(`/auth/users/${u.id}/reject`, "POST", `${u.username} rejected`),
                          })}>
                          <XCircle size={12} />
                        </button>
                      </>
                    )}
                    {u.approval_status === "approved" && (
                      u.is_active ? (
                        <button className="btn btn-warning btn-sm" title="Disable"
                          onClick={() => confirmAnd({
                            title: "Disable User",
                            body: `Disable ${u.username}? They won't be able to log in.`,
                            danger: true,
                            onConfirm: () => doAction(`/auth/users/${u.id}/disable`, "POST", `${u.username} disabled`),
                          })}>
                          <UserX size={12} />
                        </button>
                      ) : (
                        <button className="btn btn-success btn-sm" title="Enable"
                          onClick={() => doAction(`/auth/users/${u.id}/enable`, "POST", `${u.username} enabled`)}>
                          <UserCheck size={12} />
                        </button>
                      )
                    )}
                    <button className="btn btn-danger btn-sm" title="Delete"
                      onClick={() => confirmAnd({
                        title: "Delete User",
                        body: `Permanently delete ${u.username}? This cannot be undone.`,
                        danger: true,
                        onConfirm: () => doAction(`/auth/users/${u.id}`, "DELETE", `${u.username} deleted`),
                      })}>
                      <Trash2 size={12} />
                    </button>
                  </div>
                ) : (
                  <span style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>You</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {pages > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8, padding: "10px 16px" }}>
          <button className="btn btn-ghost btn-sm" disabled={page === 1} onClick={() => setPage(p => p - 1)}>
            <ChevronLeft size={13} />
          </button>
          <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            {page} / {pages}
          </span>
          <button className="btn btn-ghost btn-sm" disabled={page === pages} onClick={() => setPage(p => p + 1)}>
            <ChevronRight size={13} />
          </button>
        </div>
      )}
    </div>
  );
};

// ─── Settings Page ───────────────────────────────────────────────────────────
const SettingsPage = () => {
  const { user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [activeTab, setActiveTab] = useState("general");

  const isAdmin = user?.role === "admin";

  const tabs = [
    { id: "general",    label: "General",    icon: <SettingsIcon size={14} /> },
    { id: "appearance", label: "Appearance",  icon: <Sun size={14} /> },
    { id: "profile",    label: "Profile",     icon: <User size={14} /> },
    ...(isAdmin ? [{ id: "users", label: "User Management", icon: <Shield size={14} /> }] : []),
  ];

  return (
    <div className="page-container fade-in">
      <div className="page-header">
        <div>
          <div className="page-title">Settings</div>
          <div className="page-subtitle">Manage your preferences and account</div>
        </div>
      </div>

      <div className="settings-layout">
        {/* Tabs */}
        <div className="settings-tabs">
          {tabs.map(t => (
            <button key={t.id}
              className={`settings-tab${activeTab === t.id ? " active" : ""}`}
              onClick={() => setActiveTab(t.id)}>
              {t.icon}{t.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="settings-content">

          {/* General */}
          {activeTab === "general" && (
            <div className="settings-section">
              <div className="settings-section-header">
                <SettingsIcon size={15} color="var(--primary)" />
                <span className="settings-section-title">General</span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Application Name</div>
                  <div className="settings-row-desc">HexaMonitor</div>
                </div>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Dashboard Refresh</div>
                  <div className="settings-row-desc">Auto-refreshes every 30 seconds</div>
                </div>
                <span className="badge badge-blue">30s</span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Log Retention</div>
                  <div className="settings-row-desc">Per-service log tables retain 24 hours</div>
                </div>
                <span className="badge badge-purple">24h</span>
              </div>
            </div>
          )}

          {/* Appearance */}
          {activeTab === "appearance" && (
            <div className="settings-section">
              <div className="settings-section-header">
                <Sun size={15} color="var(--primary)" />
                <span className="settings-section-title">Appearance</span>
              </div>
              <div className="settings-row">
                <div>
                  <div className="settings-row-label">Theme</div>
                  <div className="settings-row-desc">
                    Currently using {theme === "dark" ? "Dark" : "Light"} mode
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    className={`btn btn-sm ${theme === "dark" ? "btn-primary" : "btn-ghost"}`}
                    onClick={() => theme !== "dark" && toggleTheme()}
                    style={{ display: "flex", alignItems: "center", gap: 5 }}
                  >
                    <Moon size={13} />Dark
                  </button>
                  <button
                    className={`btn btn-sm ${theme === "light" ? "btn-primary" : "btn-ghost"}`}
                    onClick={() => theme !== "light" && toggleTheme()}
                    style={{ display: "flex", alignItems: "center", gap: 5 }}
                  >
                    <Sun size={13} />Light
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Profile */}
          {activeTab === "profile" && (
            <div className="settings-section">
              <div className="settings-section-header">
                <User size={15} color="var(--primary)" />
                <span className="settings-section-title">Profile</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-label">Username</div>
                <span style={{ fontSize: "0.8rem", color: "var(--text-primary)", fontWeight: 600 }}>
                  {user?.username}
                </span>
              </div>
              <div className="settings-row">
                <div className="settings-row-label">Email</div>
                <span style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>{user?.email}</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-label">Role</div>
                <RoleBadge role={user?.role} />
              </div>
              <div className="settings-row">
                <div className="settings-row-label">Account Status</div>
                <span className="badge badge-green">Active</span>
              </div>
              <div className="settings-row">
                <div className="settings-row-label">Member Since</div>
                <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                  {user?.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
                </span>
              </div>
            </div>
          )}

          {/* Admin: User Management */}
          {activeTab === "users" && isAdmin && (
            <div className="table-wrap">
              <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "var(--text-primary)", display: "flex", alignItems: "center", gap: 8 }}>
                  <Shield size={15} color="var(--primary)" />
                  User Management
                </div>
                <div style={{ fontSize: "0.72rem", color: "var(--text-muted)", marginTop: 3 }}>
                  Approve, reject, disable, or delete user accounts
                </div>
              </div>
              <UserManagement />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
