import os
import json
import sys

# Dynamically resolve absolute path of project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INCIDENTS_DIR = os.path.join(PROJECT_ROOT, "incidents")

def save_incident_payload(incident_id: str, payload: dict) -> bool:
    """
    Saves the serialized incident payload atomically to:
    PROJECT_ROOT/incidents/INC-YYYYMMDD-XXXX/incident.json
    """
    try:
        # Create target incidents folder if not exists
        incident_dir = os.path.join(INCIDENTS_DIR, incident_id)
        os.makedirs(incident_dir, exist_ok=True)
        
        tmp_file = os.path.join(incident_dir, "incident.json.tmp")
        dest_file = os.path.join(incident_dir, "incident.json")
        
        # Write to temporary file with UTF-8, pretty-printed, preserving unicode characters
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            
        # Atomically rename/replace tmp with destination
        os.replace(tmp_file, dest_file)
        
        print(f"Successfully persisted incident package atomically to: {dest_file}", flush=True)
        return True
        
    except Exception as e:
        print(f"Error persisting incident package '{incident_id}': {e}", file=sys.stderr, flush=True)
        return False
