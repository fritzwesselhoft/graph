import json

json_path = "/Users/fritzwesselhoft/APP_GRAPH/agentcore_inventory.json"

with open(json_path, 'r') as f:
    data = json.load(f)
    print("Top level keys in your JSON are:", data.keys())
    
    # Let's peek at the first key to see its structure
    first_key = list(data.keys())[0]
    print(f"Sample data under '{first_key}':", str(data[first_key])[:200])
