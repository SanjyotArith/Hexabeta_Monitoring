import React, { useState } from "react";
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import PrivateRoute from "./components/PrivateRoute";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";

// Inline functional placeholder components for other dashboard pages
const PlaceholderPage = ({ title }) => (
  <div className="page-container fade-in">
    <h1 style={{ fontSize: "1.75rem", fontWeight: 700, letterSpacing: "-0.02em" }}>{title}</h1>
    <div className="card" style={{ padding: "3rem 2rem", textAlign: "center", color: "var(--text-secondary)" }}>
      <p style={{ fontSize: "0.9375rem" }}>The {title} dashboard view is configured and waiting for agent metrics.</p>
    </div>
  </div>
);

const App = () => {
  const [selectedEnv, setSelectedEnv] = useState(null);
  const [selectedProject, setSelectedProject] = useState(null);

  return (
    <AuthProvider>
      <Router>
        <Routes>
          {/* Public login route */}
          <Route path="/login" element={<Login />} />

          {/* Secured administrative dashboard routes */}
          <Route
            path="/*"
            element={
              <PrivateRoute>
                <div className="app-layout">
                  <Sidebar />
                  <main className="main-content">
                    <Header 
                      selectedEnv={selectedEnv} 
                      setSelectedEnv={setSelectedEnv} 
                      selectedProject={selectedProject}
                      setSelectedProject={setSelectedProject}
                    />
                    <Routes>
                      <Route path="/" element={<Dashboard selectedEnv={selectedEnv} selectedProject={selectedProject} />} />
                      <Route path="/projects" element={<PlaceholderPage title="Projects" />} />
                      <Route path="/machines" element={<PlaceholderPage title="Machines" />} />
                      <Route path="/services" element={<PlaceholderPage title="Services" />} />
                      <Route path="/api-monitor" element={<PlaceholderPage title="API Monitor" />} />
                      <Route path="/metrics" element={<PlaceholderPage title="Metrics Explorer" />} />
                      <Route path="/logs" element={<PlaceholderPage title="Logs Console" />} />
                      <Route path="/alerts" element={<PlaceholderPage title="Alerts & Incidents" />} />
                      <Route path="/settings" element={<PlaceholderPage title="Settings" />} />
                    </Routes>
                  </main>
                </div>
              </PrivateRoute>
            }
          />
        </Routes>
      </Router>
    </AuthProvider>
  );
};

export default App;
