import React from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Activity } from "lucide-react";

const PAGE_TITLES = {
  "/":        { title: "Dashboard",    subtitle: "Infrastructure overview" },
  "/logs":    { title: "Logs Console", subtitle: "Real-time log streaming & history" },
  "/settings":{ title: "Settings",     subtitle: "Configuration and preferences" },
};

const Header = () => {
  const { user } = useAuth();
  const { pathname } = useLocation();
  const meta = PAGE_TITLES[pathname] || { title: "HexaMonitor", subtitle: "" };

  const initials = user?.username
    ? user.username.slice(0, 2).toUpperCase()
    : "?";

  return (
    <header className="header">
      <div className="header-left">
        <div>
          <div className="header-title">{meta.title}</div>
          {meta.subtitle && (
            <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "1px" }}>
              {meta.subtitle}
            </div>
          )}
        </div>
      </div>

      <div className="header-right">
        <div className="user-pill">
          <div className="user-avatar">{initials}</div>
          <div>
            <div className="user-name">{user?.username || "—"}</div>
            <div className="user-role" style={{ textTransform: "capitalize" }}>
              {user?.role || "user"}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
