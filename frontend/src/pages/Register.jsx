import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import { UserPlus, Eye, EyeOff, Sun, Moon, CheckCircle } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "/api/v1";

const Register = () => {
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  const [form, setForm] = useState({
    full_name: "", username: "", email: "", password: "", confirm: ""
  });
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const validate = () => {
    if (!form.username || !form.email || !form.password || !form.confirm)
      return "All fields are required.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email))
      return "Enter a valid email address.";
    if (form.password.length < 8)
      return "Password must be at least 8 characters.";
    if (form.password !== form.confirm)
      return "Passwords do not match.";
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const err = validate();
    if (err) { setError(err); return; }

    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: form.username,
          email: form.email,
          password: form.password,
          full_name: form.full_name || undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Registration failed");
      setSuccess(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="auth-page">
        <div className="auth-card fade-in" style={{ textAlign: "center" }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 20 }}>
            <CheckCircle size={52} color="var(--success)" />
          </div>
          <h2 style={{ color: "var(--text-primary)", marginBottom: 8, fontSize: "1.15rem", fontWeight: 700 }}>
            Account Created!
          </h2>
          <p style={{ color: "var(--text-muted)", fontSize: "0.82rem", marginBottom: 24, lineHeight: 1.6 }}>
            Your account is <strong style={{ color: "var(--warning)" }}>pending administrator approval</strong>.
            You'll be able to log in once an admin approves your account.
          </p>
          <Link to="/login" className="btn btn-primary" style={{ justifyContent: "center", display: "flex" }}>
            Back to Login
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <button
        onClick={toggleTheme}
        style={{
          position: "fixed", top: 16, right: 16,
          background: "var(--bg-card)", border: "1px solid var(--border)",
          borderRadius: "var(--radius-sm)", padding: "7px 10px",
          color: "var(--text-secondary)", cursor: "pointer",
          display: "flex", alignItems: "center", gap: 6, fontSize: "0.75rem",
        }}
      >
        {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
      </button>

      <div className="auth-card fade-in">
        <div className="auth-logo">
          <div className="auth-logo-icon">HM</div>
          <span className="auth-logo-name">HexaMonitor</span>
        </div>

        <h1 className="auth-title">Create account</h1>
        <p className="auth-subtitle">Register to request access to HexaMonitor</p>

        {error && (
          <div className="alert alert-error">{error}</div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Full Name <span style={{ color: "var(--text-muted)" }}>(optional)</span></label>
            <input className="form-input" type="text" placeholder="John Doe"
              value={form.full_name} onChange={e => setForm(p => ({ ...p, full_name: e.target.value }))} />
          </div>

          <div className="grid-2" style={{ gap: 12 }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Username *</label>
              <input className="form-input" type="text" placeholder="johndoe"
                value={form.username} onChange={e => setForm(p => ({ ...p, username: e.target.value }))}
                autoComplete="username" />
            </div>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label">Email *</label>
              <input className="form-input" type="email" placeholder="john@example.com"
                value={form.email} onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                autoComplete="email" />
            </div>
          </div>
          <div style={{ height: 12 }} />

          <div className="form-group">
            <label className="form-label">Password *</label>
            <div style={{ position: "relative" }}>
              <input className="form-input" type={showPw ? "text" : "password"}
                placeholder="Min. 8 characters"
                value={form.password} onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
                style={{ paddingRight: 36 }} autoComplete="new-password" />
              <button type="button" onClick={() => setShowPw(v => !v)} style={{
                position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
                background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer"
              }}>
                {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Confirm Password *</label>
            <input className="form-input" type="password" placeholder="Repeat password"
              value={form.confirm} onChange={e => setForm(p => ({ ...p, confirm: e.target.value }))}
              autoComplete="new-password" />
          </div>

          <div className="alert alert-info" style={{ marginBottom: 14 }}>
            After registration, an admin must approve your account before you can log in.
          </div>

          <button type="submit" className="btn btn-primary w-full"
            disabled={loading} style={{ justifyContent: "center", padding: "10px 0" }}>
            {loading ? <span className="spinner" /> : <UserPlus size={15} />}
            {loading ? "Creating account…" : "Create Account"}
          </button>
        </form>

        <div className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </div>
      </div>
    </div>
  );
};

export default Register;
