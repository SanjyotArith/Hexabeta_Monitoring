import React, { useState, useEffect } from "react";
import { useAuth } from "../context/AuthContext";
import { ChevronDown, Bell, CheckCircle2, User } from "lucide-react";

const Header = ({ selectedEnv, setSelectedEnv, selectedProject, setSelectedProject }) => {
  const { authFetch, user } = useAuth();
  const [projects, setProjects] = useState([]);
  const [environments, setEnvironments] = useState([]);
  
  // Project creation modal states
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newEnvName, setNewEnvName] = useState("Production");
  const [newCheckName, setNewCheckName] = useState("");
  const [newCheckUrl, setNewCheckUrl] = useState("");
  const [formError, setFormError] = useState("");
  const [formLoading, setFormLoading] = useState(false);

  const resetForm = () => {
    setNewProjectName("");
    setNewEnvName("Production");
    setNewCheckName("");
    setNewCheckUrl("");
    setFormError("");
  };

  const fetchEnvironments = async (forceSelectProjId = null) => {
    try {
      // 1. Fetch Projects list
      const projRes = await authFetch("/projects");
      if (projRes.ok) {
        const projectsData = await projRes.json();
        setProjects(projectsData);
        
        // Find active project
        let currentProj = null;
        if (forceSelectProjId) {
          currentProj = projectsData.find(p => p.id === forceSelectProjId);
        }
        if (!currentProj) {
          const savedProjId = localStorage.getItem("hexamonitor_project_id");
          if (savedProjId) {
            currentProj = projectsData.find(p => p.id === parseInt(savedProjId));
          }
        }
        if (!currentProj && projectsData.length > 0) {
          currentProj = projectsData.find(p => p.name === "HexaBeta") || projectsData[0];
        }
        
        if (currentProj) {
          setSelectedProject(currentProj);
          localStorage.setItem("hexamonitor_project_id", currentProj.id.toString());
          
          // 2. Fetch Environments list for the project
          const envRes = await authFetch(`/projects/${currentProj.id}/environments`);
          if (envRes.ok) {
            const envs = await envRes.json();
            setEnvironments(envs);
            
            // Set default environment
            let currentEnv = null;
            const savedEnvId = localStorage.getItem("hexamonitor_env_id");
            if (savedEnvId) {
              currentEnv = envs.find(e => e.id === parseInt(savedEnvId));
            }
            if (!currentEnv && envs.length > 0) {
              currentEnv = envs.find(e => e.name === "Production") || envs[0];
            }
            
            if (currentEnv) {
              setSelectedEnv(currentEnv);
              localStorage.setItem("hexamonitor_env_id", currentEnv.id.toString());
            } else {
              setSelectedEnv(null);
            }
          }
        }
      }
    } catch (err) {
      console.error("Failed to load header navigation states:", err);
    }
  };

  useEffect(() => {
    fetchEnvironments();
  }, []);

  const handleProjectChange = async (e) => {
    const projId = parseInt(e.target.value);
    const proj = projects.find(item => item.id === projId);
    if (proj) {
      setSelectedProject(proj);
      localStorage.setItem("hexamonitor_project_id", projId.toString());
      
      try {
        const envRes = await authFetch(`/projects/${projId}/environments`);
        if (envRes.ok) {
          const envs = await envRes.json();
          setEnvironments(envs);
          if (envs.length > 0) {
            const defaultEnv = envs.find(e => e.name === "Production") || envs[0];
            setSelectedEnv(defaultEnv);
            localStorage.setItem("hexamonitor_env_id", defaultEnv.id.toString());
          } else {
            setSelectedEnv(null);
            localStorage.removeItem("hexamonitor_env_id");
          }
          window.dispatchEvent(new Event("hexamonitor_env_changed"));
        }
      } catch (err) {
        console.error("Failed to switch project environments:", err);
      }
    }
  };

  const handleEnvChange = (e) => {
    const envId = parseInt(e.target.value);
    const env = environments.find(item => item.id === envId);
    if (env) {
      setSelectedEnv(env);
      localStorage.setItem("hexamonitor_env_id", envId.toString());
      window.dispatchEvent(new Event("hexamonitor_env_changed"));
    }
  };

  const handleCreateProject = async (e) => {
    e.preventDefault();
    setFormError("");
    
    if (newProjectName.trim().length < 3) {
      setFormError("Project name must be at least 3 characters long.");
      return;
    }
    if (!newCheckUrl.trim()) {
      setFormError("Uptime check URL is required.");
      return;
    }

    setFormLoading(true);
    try {
      const response = await authFetch("/projects/setup", {
        method: "POST",
        body: JSON.stringify({
          project_name: newProjectName.trim(),
          environment_name: newEnvName.trim(),
          check_name: newCheckName.trim() || null,
          check_url: newCheckUrl.trim()
        })
      });

      if (!response.ok) {
        const data = await response.json();
        let errMsg = "Failed to create project";
        if (data && data.detail) {
          if (Array.isArray(data.detail)) {
            errMsg = data.detail.map(err => err.msg).join(", ");
          } else {
            errMsg = data.detail;
          }
        }
        throw new Error(errMsg);
      }

      const result = await response.json();
      
      setIsModalOpen(false);
      resetForm();
      
      // Refetch environments and force selection of the new project
      if (result.project) {
        localStorage.setItem("hexamonitor_project_id", result.project.id.toString());
        if (result.environment) {
          localStorage.setItem("hexamonitor_env_id", result.environment.id.toString());
        }
        await fetchEnvironments(result.project.id);
        window.dispatchEvent(new Event("hexamonitor_env_changed"));
      }
    } catch (err) {
      setFormError(err.message || "An error occurred.");
    } finally {
      setFormLoading(false);
    }
  };

  return (
    <header className="top-header">
      <div className="header-scope">
        <div className="scope-selectors">
          <div className="selector-group">
            <span className="selector-label">Project:</span>
            <div className="select-wrapper">
              <select 
                className="header-select" 
                value={selectedProject?.id || ""} 
                onChange={handleProjectChange}
                disabled={projects.length === 0}
              >
                {projects.map((proj) => (
                  <option key={proj.id} value={proj.id}>
                    {proj.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
            
            <button 
              type="button"
              className="btn btn-primary"
              style={{ 
                padding: "0.375rem 0.75rem", 
                fontSize: "0.75rem", 
                fontWeight: 600, 
                display: "inline-flex", 
                alignItems: "center", 
                height: "32px",
                marginLeft: "0.5rem"
              }}
              onClick={() => setIsModalOpen(true)}
            >
              + Add Project
            </button>
          </div>
          
          <div className="selector-group">
            <span className="selector-label">Environment:</span>
            <div className="select-wrapper">
              <select 
                className="header-select" 
                value={selectedEnv?.id || ""} 
                onChange={handleEnvChange}
                disabled={environments.length === 0}
              >
                {environments.map((env) => (
                  <option key={env.id} value={env.id}>
                    {env.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="select-arrow" />
            </div>
          </div>
        </div>
      </div>

      <div className="header-actions">
        <div className="system-health-summary">
          <CheckCircle2 size={16} color="var(--color-success)" />
          <span className="summary-text">System Active</span>
        </div>
        
        <button className="header-action-btn">
          <Bell size={18} />
          <span className="notification-badge-dot"></span>
        </button>
        
        <div className="admin-profile-badge">
          <div className="profile-avatar">
            <User size={14} />
          </div>
          <span className="profile-name">{user?.username || "Admin"}</span>
        </div>
      </div>

      {isModalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <div className="modal-header">
              <h3>Add New Project to Monitor</h3>
              <button 
                type="button" 
                className="modal-close-btn" 
                onClick={() => {
                  setIsModalOpen(false);
                  resetForm();
                }}
              >
                &times;
              </button>
            </div>
            
            {formError && (
              <div className="flex-center" style={{
                backgroundColor: "var(--color-critical-glow)",
                border: "1px solid rgba(239, 68, 68, 0.2)",
                borderRadius: "var(--radius-md)",
                padding: "0.75rem",
                color: "var(--color-critical)",
                fontSize: "0.875rem",
                marginBottom: "1.25rem",
                justifyContent: "flex-start",
                gap: "0.5rem"
              }}>
                <span>{formError}</span>
              </div>
            )}
            
            <form onSubmit={handleCreateProject}>
              <div className="form-group">
                <label className="label">Project Name</label>
                <input 
                  type="text" 
                  className="input" 
                  style={{ width: "100%" }}
                  placeholder="e.g. xyz.com" 
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  required
                />
              </div>
              
              <div className="form-group">
                <label className="label">Environment Name</label>
                <input 
                  type="text" 
                  className="input" 
                  style={{ width: "100%" }}
                  placeholder="e.g. Production" 
                  value={newEnvName}
                  onChange={(e) => setNewEnvName(e.target.value)}
                  required
                />
              </div>
              
              <div className="form-group">
                <label className="label">Uptime Check Name (Optional)</label>
                <input 
                  type="text" 
                  className="input" 
                  style={{ width: "100%" }}
                  placeholder="e.g. Homepage Check" 
                  value={newCheckName}
                  onChange={(e) => setNewCheckName(e.target.value)}
                />
              </div>
              
              <div className="form-group" style={{ marginBottom: "1.5rem" }}>
                <label className="label">Uptime Check URL</label>
                <input 
                  type="text" 
                  className="input" 
                  style={{ width: "100%" }}
                  placeholder="e.g. https://xyz.com" 
                  value={newCheckUrl}
                  onChange={(e) => setNewCheckUrl(e.target.value)}
                  required
                />
              </div>
              
              <div className="modal-actions">
                <button 
                  type="button" 
                  className="btn" 
                  onClick={() => {
                    setIsModalOpen(false);
                    resetForm();
                  }}
                  disabled={formLoading}
                >
                  Cancel
                </button>
                <button 
                  type="submit" 
                  className="btn btn-primary"
                  disabled={formLoading}
                >
                  {formLoading ? "Creating..." : "Create Project"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </header>
  );
};

export default Header;
