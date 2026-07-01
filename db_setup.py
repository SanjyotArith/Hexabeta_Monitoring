#!/usr/bin/env python3
"""
HexaMonitor Database Setup Script
Creates the 'hexa_monitor' PostgreSQL database, 'hexa' schema, and all required monitoring tables,
along with optimized indexes on all foreign keys, status fields, and time-series columns.
"""

import os
import sys

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

# Load environment configuration from workspace .env
load_env_file()

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
except ImportError:
    print("Error: The 'psycopg2' library is required to run this script.")
    print("Please install it using: pip install psycopg2-binary")
    sys.exit(1)

# Default PostgreSQL connection configurations (overridden by environment variables)
DB_HOST = os.environ.get("PGHOST", "localhost")
DB_PORT = os.environ.get("PGPORT", "5432")
DB_USER = os.environ.get("PGUSER", "postgres")
DB_PASS = os.environ.get("PGPASSWORD", "")
DB_NAME = os.environ.get("PGDATABASE", "hexa_monitor")
SCHEMA_NAME = os.environ.get("PGSCHEMA", "hexa")


SQL_CREATION_STATEMENTS = [
    # 1. Create Schema
    f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};",
    f"SET search_path TO {SCHEMA_NAME}, public;",

    # 2. Users Table
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        email VARCHAR(255) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """,

    # 3. Sessions Table
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        refresh_token VARCHAR(255) NOT NULL UNIQUE,
        ip_address VARCHAR(45) NULL,
        user_agent TEXT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """,

    # 4. Projects Table
    """
    CREATE TABLE IF NOT EXISTS projects (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE,
        description TEXT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """,

    # 5. Environments Table
    """
    CREATE TABLE IF NOT EXISTS environments (
        id SERIAL PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name VARCHAR(50) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT unique_project_env UNIQUE (project_id, name)
    );
    """,

    # 6. Machines Table
    """
    CREATE TABLE IF NOT EXISTS machines (
        id SERIAL PRIMARY KEY,
        environment_id INTEGER NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        hostname VARCHAR(255) NULL,
        ip_address VARCHAR(45) NULL,
        os VARCHAR(100) NOT NULL DEFAULT 'macOS',
        cpu_cores INTEGER NULL,
        ram_total_bytes BIGINT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT unique_env_machine UNIQUE (environment_id, name)
    );
    """,

    # 7. Agents Table
    """
    CREATE TABLE IF NOT EXISTS agents (
        id SERIAL PRIMARY KEY,
        machine_id INTEGER NOT NULL UNIQUE REFERENCES machines(id) ON DELETE CASCADE,
        token_hash VARCHAR(255) NOT NULL UNIQUE,
        version VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'inactive',
        last_connected_at TIMESTAMP WITH TIME ZONE NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """,

    # 8. Heartbeats Table (BIGSERIAL for time-series log)
    """
    CREATE TABLE IF NOT EXISTS heartbeats (
        id BIGSERIAL PRIMARY KEY,
        agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        latency_ms INTEGER NULL
    );
    """,

    # 9. Machine Metrics Table (BIGSERIAL for high frequency logs)
    """
    CREATE TABLE IF NOT EXISTS machine_metrics (
        id BIGSERIAL PRIMARY KEY,
        machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        cpu_usage DOUBLE PRECISION NOT NULL,
        ram_used_bytes BIGINT NOT NULL,
        ram_total_bytes BIGINT NOT NULL,
        disk_used_bytes BIGINT NOT NULL,
        disk_total_bytes BIGINT NOT NULL,
        network_in_bytes_sec DOUBLE PRECISION NOT NULL,
        network_out_bytes_sec DOUBLE PRECISION NOT NULL,
        temperature_celsius DOUBLE PRECISION NULL,
        swap_used_bytes BIGINT NULL,
        swap_total_bytes BIGINT NULL,
        load_avg_1m DOUBLE PRECISION NULL,
        load_avg_5m DOUBLE PRECISION NULL,
        load_avg_15m DOUBLE PRECISION NULL,
        uptime_seconds BIGINT NULL
    );
    """,

    # 10. Services Table
    """
    CREATE TABLE IF NOT EXISTS services (
        id SERIAL PRIMARY KEY,
        machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        service_type VARCHAR(50) NOT NULL,
        process_identifier VARCHAR(255) NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT unique_machine_service UNIQUE (machine_id, name)
    );
    """,

    # 11. Service Status History
    """
    CREATE TABLE IF NOT EXISTS service_status_history (
        id BIGSERIAL PRIMARY KEY,
        service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        status VARCHAR(20) NOT NULL,
        cpu_usage DOUBLE PRECISION NULL,
        ram_used_bytes BIGINT NULL,
        details TEXT NULL
    );
    """,

    # 12. API Checks Table (Synthetic endpoints monitoring configuration)
    """
    CREATE TABLE IF NOT EXISTS api_checks (
        id SERIAL PRIMARY KEY,
        environment_id INTEGER NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        url TEXT NOT NULL,
        request_method VARCHAR(10) NOT NULL DEFAULT 'GET',
        headers JSONB NULL,
        request_payload TEXT NULL,
        expected_status_code INTEGER NOT NULL DEFAULT 200,
        expected_response_match TEXT NULL,
        check_interval_seconds INTEGER NOT NULL DEFAULT 60,
        timeout_seconds INTEGER NOT NULL DEFAULT 10,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """,

    # 13. API Check History
    """
    CREATE TABLE IF NOT EXISTS api_check_history (
        id BIGSERIAL PRIMARY KEY,
        api_check_id INTEGER NOT NULL REFERENCES api_checks(id) ON DELETE CASCADE,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        is_up BOOLEAN NOT NULL,
        response_time_ms INTEGER NULL,
        status_code INTEGER NULL,
        error_message TEXT NULL
    );
    """,

    # 14. Logs Table
    """
    CREATE TABLE IF NOT EXISTS logs (
        id BIGSERIAL PRIMARY KEY,
        machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
        service_id INTEGER NULL REFERENCES services(id) ON DELETE SET NULL,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        log_type VARCHAR(50) NOT NULL,
        severity VARCHAR(20) NOT NULL,
        message TEXT NOT NULL,
        metadata JSONB NULL
    );
    """,

    # 15. Scheduler Jobs Table (For tracking background tasks status)
    """
    CREATE TABLE IF NOT EXISTS scheduler_jobs (
        id SERIAL PRIMARY KEY,
        machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        schedule_cron VARCHAR(100) NULL,
        last_run_at TIMESTAMP WITH TIME ZONE NULL,
        last_run_status VARCHAR(20) NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        CONSTRAINT unique_machine_job UNIQUE (machine_id, name)
    );
    """,

    # 16. Scheduler Runs History
    """
    CREATE TABLE IF NOT EXISTS scheduler_runs (
        id BIGSERIAL PRIMARY KEY,
        job_id INTEGER NOT NULL REFERENCES scheduler_jobs(id) ON DELETE CASCADE,
        started_at TIMESTAMP WITH TIME ZONE NOT NULL,
        finished_at TIMESTAMP WITH TIME ZONE NULL,
        status VARCHAR(20) NOT NULL,
        duration_ms INTEGER NULL,
        output_log TEXT NULL
    );
    """,

    # 17. Alert Rules Table
    """
    CREATE TABLE IF NOT EXISTS alert_rules (
        id SERIAL PRIMARY KEY,
        environment_id INTEGER NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        check_type VARCHAR(50) NOT NULL,
        metric_name VARCHAR(50) NULL,
        operator VARCHAR(10) NULL,
        threshold_value DOUBLE PRECISION NULL,
        duration_seconds INTEGER NOT NULL DEFAULT 300,
        severity VARCHAR(20) NOT NULL DEFAULT 'warning',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """,

    # 18. Incidents Table
    """
    CREATE TABLE IF NOT EXISTS incidents (
        id SERIAL PRIMARY KEY,
        environment_id INTEGER NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
        title VARCHAR(255) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        severity VARCHAR(20) NOT NULL,
        started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        acknowledged_at TIMESTAMP WITH TIME ZONE NULL,
        resolved_at TIMESTAMP WITH TIME ZONE NULL
    );
    """,

    # 19. Alerts Table
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id SERIAL PRIMARY KEY,
        incident_id INTEGER NULL REFERENCES incidents(id) ON DELETE SET NULL,
        alert_rule_id INTEGER NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
        machine_id INTEGER NULL REFERENCES machines(id) ON DELETE CASCADE,
        service_id INTEGER NULL REFERENCES services(id) ON DELETE CASCADE,
        api_check_id INTEGER NULL REFERENCES api_checks(id) ON DELETE CASCADE,
        message TEXT NOT NULL,
        value_triggered DOUBLE PRECISION NULL,
        started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        resolved_at TIMESTAMP WITH TIME ZONE NULL
    );
    """,

    # 20. Settings Table
    """
    CREATE TABLE IF NOT EXISTS settings (
        id SERIAL PRIMARY KEY,
        key VARCHAR(100) NOT NULL UNIQUE,
        value TEXT NOT NULL,
        description TEXT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """
]

INDEX_CREATION_STATEMENTS = [
    # Schema-wide Search Path setting
    f"SET search_path TO {SCHEMA_NAME}, public;",

    # Users
    "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);",
    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);",

    # Sessions
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_refresh_token ON sessions(refresh_token);",

    # Environments
    "CREATE INDEX IF NOT EXISTS idx_environments_project_id ON environments(project_id);",

    # Machines
    "CREATE INDEX IF NOT EXISTS idx_machines_environment_id ON machines(environment_id);",

    # Agents
    "CREATE INDEX IF NOT EXISTS idx_agents_machine_id ON agents(machine_id);",
    "CREATE INDEX IF NOT EXISTS idx_agents_token_hash ON agents(token_hash);",

    # Heartbeats
    "CREATE INDEX IF NOT EXISTS idx_heartbeats_agent_id ON heartbeats(agent_id);",
    "CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp_desc ON heartbeats(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_heartbeats_agent_timestamp ON heartbeats(agent_id, timestamp DESC);",

    # Machine Metrics (Performance-critical)
    "CREATE INDEX IF NOT EXISTS idx_metrics_machine_id ON machine_metrics(machine_id);",
    "CREATE INDEX IF NOT EXISTS idx_metrics_timestamp_desc ON machine_metrics(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_metrics_composite ON machine_metrics(machine_id, timestamp DESC);",

    # Services
    "CREATE INDEX IF NOT EXISTS idx_services_machine_id ON services(machine_id);",

    # Service Status History
    "CREATE INDEX IF NOT EXISTS idx_svc_hist_service_id ON service_status_history(service_id);",
    "CREATE INDEX IF NOT EXISTS idx_svc_hist_timestamp ON service_status_history(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_svc_hist_composite ON service_status_history(service_id, timestamp DESC);",

    # API Checks
    "CREATE INDEX IF NOT EXISTS idx_api_checks_environment_id ON api_checks(environment_id);",

    # API Check History (Performance-critical)
    "CREATE INDEX IF NOT EXISTS idx_api_check_history_fk ON api_check_history(api_check_id);",
    "CREATE INDEX IF NOT EXISTS idx_api_check_history_timestamp ON api_check_history(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_api_check_history_composite ON api_check_history(api_check_id, timestamp DESC);",

    # Logs
    "CREATE INDEX IF NOT EXISTS idx_logs_machine_id ON logs(machine_id);",
    "CREATE INDEX IF NOT EXISTS idx_logs_service_id ON logs(service_id);",
    "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_logs_severity ON logs(severity);",
    "CREATE INDEX IF NOT EXISTS idx_logs_query ON logs(machine_id, log_type, timestamp DESC);",

    # Scheduler Jobs & Runs
    "CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_machine_id ON scheduler_jobs(machine_id);",
    "CREATE INDEX IF NOT EXISTS idx_scheduler_runs_job_id ON scheduler_runs(job_id);",
    "CREATE INDEX IF NOT EXISTS idx_scheduler_runs_composite ON scheduler_runs(job_id, started_at DESC);",

    # Alert Rules
    "CREATE INDEX IF NOT EXISTS idx_alert_rules_environment_id ON alert_rules(environment_id);",

    # Incidents
    "CREATE INDEX IF NOT EXISTS idx_incidents_environment_id ON incidents(environment_id);",
    "CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);",
    "CREATE INDEX IF NOT EXISTS idx_incidents_started ON incidents(started_at DESC);",

    # Alerts
    "CREATE INDEX IF NOT EXISTS idx_alerts_incident_id ON alerts(incident_id);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_alert_rule_id ON alerts(alert_rule_id);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_machine_id ON alerts(machine_id);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_service_id ON alerts(service_id);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_api_check_id ON alerts(api_check_id);",
    "CREATE INDEX IF NOT EXISTS idx_alerts_unresolved ON alerts(resolved_at) WHERE resolved_at IS NULL;",

    # Settings
    "CREATE INDEX IF NOT EXISTS idx_settings_key ON settings(key);"
]


def create_database():
    """Connects to the default postgres database and creates the target database if not exists."""
    print("Connecting to PostgreSQL to check database existence...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database="postgres"
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cursor = conn.cursor()

        # Check if database exists
        cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s;", (DB_NAME,))
        exists = cursor.fetchone()

        if not exists:
            print(f"Database '{DB_NAME}' does not exist. Creating it now...")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            print(f"Database '{DB_NAME}' successfully created.")
        else:
            print(f"Database '{DB_NAME}' already exists.")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Error during database check/creation: {e}", file=sys.stderr)
        sys.exit(1)


def create_schema_and_tables():
    """Connects to the target database and creates the schema, tables, and indexes."""
    print(f"Connecting to database '{DB_NAME}' to configure schema and tables...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME
        )
        cursor = conn.cursor()

        print(f"Creating schema '{SCHEMA_NAME}' and tables...")
        for query in SQL_CREATION_STATEMENTS:
            cursor.execute(query)
        conn.commit()
        print("All tables created successfully.")

        print("Creating indexes on foreign keys and search fields...")
        for index_query in INDEX_CREATION_STATEMENTS:
            cursor.execute(index_query)
        conn.commit()
        print("All indexes created successfully.")

        cursor.close()
        conn.close()
        print("Database configuration completed successfully!")

    except Exception as e:
        print(f"Error during schema/table creation: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    print("=== HexaMonitor Schema Setup Tool ===")
    create_database()
    create_schema_and_tables()
