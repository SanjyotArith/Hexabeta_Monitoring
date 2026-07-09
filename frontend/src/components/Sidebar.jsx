import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import {
  LayoutDashboard, FileText, Settings, LogOut, Sun, Moon, Activity
} from "lucide-react";

const Sidebar = () => {
  const { logout, user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const menuItems = [
    { name: "Dashboard", path: "/",      icon: <LayoutDashboard size={16} />, end: true },
    { name: "Logs",      path: "/logs",  icon: <FileText size={16} /> },
    { name: "API Monitor", path: "/api-monitor", icon: <Activity size={16} /> },
    { name: "Settings",  path: "/settings", icon: <Settings size={16} /> },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-logo">HM</div>
        <span className="brand-name">HexaMonitor</span>
      </div>

      <nav className="sidebar-nav">
        <div className="nav-section-label">Navigation</div>
        {menuItems.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.end}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            {item.icon}
            <span className="nav-label">{item.name}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="theme-toggle-row">
          <span className="theme-toggle-label">
            {theme === "dark" ? <Moon size={13} /> : <Sun size={13} />}
            {theme === "dark" ? "Dark Mode" : "Light Mode"}
          </span>
          <label className="toggle-switch">
            <input type="checkbox" checked={theme === "light"} onChange={toggleTheme} />
            <span className="toggle-track" />
            <span className="toggle-thumb" />
          </label>
        </div>
        <button className="nav-item logout-btn" onClick={handleLogout} style={{ width: "100%", color: "var(--danger)" }}>
          <LogOut size={16} />
          <span className="nav-label">Sign Out</span>
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
