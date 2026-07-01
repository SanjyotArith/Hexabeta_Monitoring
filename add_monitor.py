import os
import sys
import psycopg2
from datetime import datetime, timezone

def load_env_file(filepath=".env"):
    """Loads environment variables from a local .env file if it exists."""
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    os.environ[key] = val

# Load config
load_env_file()

DB_HOST = os.environ.get("PGHOST", "127.0.0.1")
DB_PORT = os.environ.get("PGPORT", "5432")
DB_USER = os.environ.get("PGUSER", "postgres")
DB_PASS = os.environ.get("PGPASSWORD", "")
DB_NAME = os.environ.get("PGDATABASE", "hexa_monitor")
SCHEMA_NAME = os.environ.get("PGSCHEMA", "hexa")

def main():
    print("=== HexaMonitor: Add Project & Domain to Monitor ===")
    
    # Inputs
    project_name = input("Enter Project Name (e.g., abc.com): ").strip()
    if not project_name:
        print("Project name cannot be empty.")
        return

    env_name = input("Enter Environment Name (default: Production): ").strip() or "Production"
    
    check_name = input(f"Enter Uptime Check Name (default: {project_name} Homepage): ").strip() or f"{project_name} Homepage"
    
    check_url = input("Enter Uptime Check URL (e.g., https://abc.com): ").strip()
    if not check_url:
        print("URL cannot be empty.")
        return
    if not check_url.startswith("http://") and not check_url.startswith("https://"):
        check_url = "https://" + check_url

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME
        )
        conn.autocommit = False
        cursor = conn.cursor()
        cursor.execute(f"SET search_path TO {SCHEMA_NAME}, public;")

        # 1. Create or Get Project
        cursor.execute("SELECT id FROM projects WHERE name = %s;", (project_name,))
        project_row = cursor.fetchone()
        if project_row:
            project_id = project_row[0]
            print(f"Project '{project_name}' already exists (ID: {project_id}).")
        else:
            cursor.execute(
                "INSERT INTO projects (name, description, created_at, updated_at) VALUES (%s, %s, NOW(), NOW()) RETURNING id;",
                (project_name, f"Infrastructure monitoring for {project_name}")
            )
            project_id = cursor.fetchone()[0]
            print(f"Created new Project: {project_name} (ID: {project_id}).")

        # 2. Create or Get Environment
        cursor.execute("SELECT id FROM environments WHERE project_id = %s AND name = %s;", (project_id, env_name))
        env_row = cursor.fetchone()
        if env_row:
            env_id = env_row[0]
            print(f"Environment '{env_name}' already exists (ID: {env_id}).")
        else:
            cursor.execute(
                "INSERT INTO environments (project_id, name, created_at, updated_at) VALUES (%s, %s, NOW(), NOW()) RETURNING id;",
                (project_id, env_name)
            )
            env_id = cursor.fetchone()[0]
            print(f"Created new Environment: {env_name} (ID: {env_id}).")

        # 3. Create Uptime Check
        cursor.execute(
            "SELECT id FROM api_checks WHERE environment_id = %s AND url = %s;",
            (env_id, check_url)
        )
        check_row = cursor.fetchone()
        if check_row:
            print(f"Uptime check for URL '{check_url}' already exists.")
        else:
            cursor.execute(
                """
                INSERT INTO api_checks 
                (environment_id, name, url, request_method, is_active, created_at, updated_at) 
                VALUES (%s, %s, %s, 'GET', TRUE, NOW(), NOW()) 
                RETURNING id;
                """,
                (env_id, check_name, check_url)
            )
            check_id = cursor.fetchone()[0]
            print(f"Created new Uptime Check: {check_name} -> {check_url} (ID: {check_id}).")

        # 4. Create Mock Machine if none exists (to populate server utilization charts)
        cursor.execute("SELECT id FROM machines WHERE environment_id = %s;", (env_id,))
        machine_row = cursor.fetchone()
        if not machine_row:
            cursor.execute(
                """
                INSERT INTO machines 
                (environment_id, name, hostname, ip_address, os, cpu_cores, ram_total_bytes, created_at, updated_at) 
                VALUES (%s, 'Mac Mini #1', 'mac-mini-1.local', '192.168.1.10', 'macOS', 8, 17179869184, NOW(), NOW()) 
                RETURNING id;
                """,
                (env_id,)
            )
            machine_id = cursor.fetchone()[0]
            print(f"Added default host 'Mac Mini #1' for server performance metrics.")

            # Create default services
            services = [
                ("Backend API", "launchd"),
                ("Nginx", "process"),
                ("PostgreSQL", "process"),
                ("Cloudflare Tunnel", "process")
            ]
            for svc_name, svc_type in services:
                cursor.execute(
                    """
                    INSERT INTO services (machine_id, name, service_type, is_active, created_at, updated_at)
                    VALUES (%s, %s, %s, TRUE, NOW(), NOW());
                    """,
                    (machine_id, svc_name, svc_type)
                )
            
            # Create starting metrics
            cursor.execute(
                """
                INSERT INTO machine_metrics 
                (machine_id, timestamp, cpu_usage, ram_used_bytes, ram_total_bytes, disk_used_bytes, disk_total_bytes, 
                 network_in_bytes_sec, network_out_bytes_sec, load_avg_1m, uptime_seconds) 
                VALUES (%s, NOW(), 12.5, 6442450944, 17179869184, 125000000000, 500000000000, 45000, 25000, 1.1, 86400);
                """,
                (machine_id,)
            )
            print("Populated default status matrix services and initial system metrics.")

        conn.commit()
        print("\nSuccessfully added project and configured monitoring!")
        print(f"You can now open the dashboard and select the '{project_name}' project.")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"\nError connecting/executing database transaction: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
            conn.close()

if __name__ == "__main__":
    main()
