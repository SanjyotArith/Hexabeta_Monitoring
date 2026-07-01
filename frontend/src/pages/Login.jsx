import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Lock, User, Mail, AlertCircle, CheckCircle } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_URL || "/api/v1";

const Login = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (isRegister) {
      if (username.trim().length < 3) {
        setError("Username must be at least 3 characters long.");
        return;
      }
      if (password.length < 8) {
        setError("Password must be at least 8 characters long.");
        return;
      }
    }

    setLoading(true);

    try {
      if (isRegister) {
        // Register administrator account
        const response = await fetch(`${API_BASE}/auth/register`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, email, password }),
        });

        if (!response.ok) {
          const data = await response.json();
          let errMsg = "Registration failed";
          if (data && data.detail) {
            if (Array.isArray(data.detail)) {
              errMsg = data.detail.map(err => err.msg).join(", ");
            } else {
              errMsg = data.detail;
            }
          }
          throw new Error(errMsg);
        }

        setSuccess("Administrator account created successfully! Logging you in...");
        
        // Auto-login after successful registration
        setTimeout(async () => {
          try {
            await login(username, password);
            navigate("/");
          } catch (loginErr) {
            setError("Account created, but auto-login failed. Please sign in manually.");
            setIsRegister(false);
          }
        }, 1500);

      } else {
        // Normal login
        await login(username, password);
        navigate("/");
      }
    } catch (err) {
      setError(err.message || "An error occurred. Please check database connectivity.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page flex-center" style={{ height: "100vh", backgroundColor: "var(--bg-primary)" }}>
      <div className="ambient-glow" style={{
        position: "absolute",
        width: "400px",
        height: "400px",
        background: "radial-gradient(circle, rgba(59, 130, 246, 0.08) 0%, rgba(139, 92, 246, 0.02) 70%)",
        borderRadius: "50%",
        filter: "blur(40px)",
        zIndex: 0
      }} />

      <div className="card login-card" style={{ width: "100%", maxWidth: "400px", padding: "2.5rem 2rem", zIndex: 1, position: "relative" }}>
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div style={{
            width: "48px",
            height: "48px",
            background: "linear-gradient(135deg, var(--color-info) 0%, #8b5cf6 100%)",
            borderRadius: "var(--radius-lg)",
            color: "#fff",
            fontWeight: 800,
            fontSize: "1.25rem",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: "1rem",
            boxShadow: "0 4px 14px rgba(59, 130, 246, 0.3)"
          }}>
            HM
          </div>
          <h2 style={{ fontSize: "1.5rem", fontWeight: 700, color: "var(--text-primary)" }}>
            {isRegister ? "Setup Administrator" : "Welcome Back"}
          </h2>
          <p style={{ fontSize: "0.875rem", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            {isRegister ? "Register your private credentials" : "HexaMonitor Core Portal"}
          </p>
        </div>

        {error && (
          <div className="flex-center" style={{
            backgroundColor: "var(--color-critical-glow)",
            border: "1px solid rgba(239, 68, 68, 0.2)",
            borderRadius: "var(--radius-md)",
            padding: "0.75rem",
            color: "var(--color-critical)",
            fontSize: "0.875rem",
            gap: "0.5rem",
            marginBottom: "1.5rem",
            justifyContent: "flex-start"
          }}>
            <AlertCircle size={16} style={{ flexShrink: 0 }} />
            <span>{error}</span>
          </div>
        )}

        {success && (
          <div className="flex-center" style={{
            backgroundColor: "var(--color-success-glow)",
            border: "1px solid rgba(16, 185, 129, 0.2)",
            borderRadius: "var(--radius-md)",
            padding: "0.75rem",
            color: "var(--color-success)",
            fontSize: "0.875rem",
            gap: "0.5rem",
            marginBottom: "1.5rem",
            justifyContent: "flex-start"
          }}>
            <CheckCircle size={16} style={{ flexShrink: 0 }} />
            <span>{success}</span>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="label">Username</label>
            <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
              <User size={16} style={{ position: "absolute", left: "12px", color: "var(--text-muted)" }} />
              <input
                type="text"
                className="input"
                style={{ width: "100%", paddingLeft: "36px" }}
                placeholder={isRegister ? "Choose admin username" : "Enter username or email"}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
          </div>

          {isRegister && (
            <div className="form-group">
              <label className="label">Email Address</label>
              <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                <Mail size={16} style={{ position: "absolute", left: "12px", color: "var(--text-muted)" }} />
                <input
                  type="email"
                  className="input"
                  style={{ width: "100%", paddingLeft: "36px" }}
                  placeholder="admin@hexabeta.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
            </div>
          )}

          <div className="form-group" style={{ marginBottom: "2rem" }}>
            <label className="label">Password</label>
            <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
              <Lock size={16} style={{ position: "absolute", left: "12px", color: "var(--text-muted)" }} />
              <input
                type="password"
                className="input"
                style={{ width: "100%", paddingLeft: "36px" }}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: "100%", padding: "0.75rem", fontSize: "0.9375rem", fontWeight: 600 }}
            disabled={loading}
          >
            {loading ? "Processing..." : isRegister ? "Create Account" : "Sign In"}
          </button>
        </form>

        <div style={{ marginTop: "1.5rem", textAlign: "center", fontSize: "0.8125rem" }}>
          <button 
            type="button"
            className="btn" 
            style={{ background: "transparent", border: "none", color: "var(--color-info)", padding: 0 }}
            onClick={() => {
              setIsRegister(!isRegister);
              setError("");
              setSuccess("");
            }}
          >
            {isRegister ? "Already registered? Sign In" : "Setup Initial Admin Account"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Login;
