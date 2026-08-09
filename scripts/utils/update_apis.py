import json
import re

with open("data/omkar.txt", "r") as f:
    lines = f.readlines()

verified_keys = set()
for line in lines:
    if "VERIFIED" in line.upper():
        match = re.search(r'(ok_[a-f0-9]{32})', line)
        if match:
            verified_keys.add(match.group(1))

with open("dashboard/config.json", "r") as f:
    config = json.load(f)

new_keys_added = 0
for key in verified_keys:
    if key not in config.get("omkar_keys", []):
        config.setdefault("omkar_keys", []).append(key)
        config.setdefault("omkar_usage", {})[key] = 200
        new_keys_added += 1

with open("dashboard/config.json", "w") as f:
    json.dump(config, f, indent=2)

print(f"Added {new_keys_added} new verified API keys to config.json")
