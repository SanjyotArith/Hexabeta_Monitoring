import React from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { 
  LayoutDashboard, 
  FolderKanban, 
  Server, 
  Activity, 
  Globe, 
  LineChart, 
  FileText, 
  AlertTriangle, 
  Settings, 
  LogOut 
} from "lucide-react";

const Sidebar = () => {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const menuItems = [
    { name: "Dashboard", path: "/", icon: <LayoutDashboard size={18} /> },
    { name: "Projects", path: "/projects", icon: <FolderKanban size={18} /> },
    { name: "Machines", path: "/machines", icon: <Server size={18} /> },
    { name: "Services", path: "/services", icon: <Activity size={18} /> },
    { name: "API Monitor", path: "/api-monitor", icon: <Globe size={18} /> },
    { name: "Metrics", path: "/metrics", icon: <LineChart size={18} /> },
    { name: "Logs", path: "/logs", icon: <FileText size={18} /> },
    { name: "Alerts & Incidents", path: "/alerts", icon: <AlertTriangle size={18} /> },
    { name: "Settings", path: "/settings", icon: <Settings size={18} /> },
  ];

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-icon">HM</div>
        <span className="brand-name">HexaMonitor</span>
      </div>
      
      <nav className="sidebar-nav">
        {menuItems.map((item) => (
          <NavLink 
            key={item.path} 
            to={item.path} 
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            {item.icon}
            <span className="nav-label">{item.name}</span>
          </NavLink>
        ))}
      </nav>
      
      <div className="sidebar-footer">
        <button className="nav-item logout-btn" onClick={handleLogout}>
          <LogOut size={18} />
          <span className="nav-label">Sign Out</span>
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
