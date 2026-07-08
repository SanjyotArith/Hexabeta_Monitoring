import json

def dump(data):
    with open("agent_payload_debug.json", "a") as f:
        f.write(json.dumps(data) + "\n")
