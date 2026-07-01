import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const PrivateRoute = ({ children }) => {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex-center" style={{ height: "100vh", backgroundColor: "var(--bg-primary)" }}>
        <div 
          className="animate-spin" 
          style={{ 
            width: "36px", 
            height: "36px", 
            border: "3px solid var(--border-color)", 
            borderTopColor: "var(--color-info)", 
            borderRadius: "50%" 
          }}
        />
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  return children;
};

export default PrivateRoute;
