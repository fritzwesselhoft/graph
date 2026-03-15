1.run agentCoreCollector.py 
        example: python3 agentCoreCollector.py --regions us-east-2

Pre-Requirements: 
        boto3 : pip install boto3
        python3

Output Example:

Run Example: (.venv) fritzwesselhoft@fritzs-MBP SimpleMap_v1 % python3 agentCoreCollector.py --regions us-east-2
INFO Scanning us-east-2
INFO Found credentials in shared credentials file: ~/.aws/credentials
Wrote agentcore_inventory.json
{
  "regions": {
    "us-east-2": {
      "agent_runtimes": 2,
      "memories": 1,
      "gateways": 1,
      "workload_identities": 3,
      "policy_engines": 1
    }
  }
}

File Created on same directory: agentcore_inventory.json


2.run map_agentcore.py
     
Run:
python3 map_agentcore.py 
✨ Architecture map 'agentcore_inventory_map.png' has been created!
(.venv) fritzwesselhoft@fritzs-MBP SimpleMap_v1 % 

Pre-Requirements:
        Update Script to point to your agentCoreCollector.py output file, I'll add --input flag later
        Diagrams: pip install diagrams
        graphviz: brew install graphviz (on Mac)

Output FIle: aws_agentcore_inventory_map.png