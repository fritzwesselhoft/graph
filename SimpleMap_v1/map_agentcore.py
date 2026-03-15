import json
import os
from diagrams import Diagram, Cluster, Edge
from diagrams.aws.ml import Bedrock
from diagrams.aws.security import IdentityAndAccessManagementIamPermissions as IAM
from diagrams.aws.compute import Lambda
from diagrams.aws.storage import S3

json_path = "/Users/fritzwesselhoft/APP_GRAPH/SimpleMap_v1/agentcore_inventory.json"

def load_data():
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    # Navigating your specific JSON hierarchy
    res = data['regions'][0]['resources']
    
    return {
        "runtimes": res['agent_runtimes'].get('items', []),
        "memories": res['memories'].get('items', []),
        "gateways": res['gateways'].get('items', []),
        "policy_engines": res['policy_engines'].get('items', []),
        "policies": res['policies_by_engine'],
        "targets": res['gateway_targets_by_gateway']
    }

def draw():
    inventory = load_data()
    
    graph_attr = {
        "fontsize": "16",
        "bgcolor": "transparent",
        "pad": "0.5"
    }

    with Diagram("AWS AgentCore Inventory Map", show=False, direction="LR", graph_attr=graph_attr):
        
        # 1. Security Layer (Policies)
        with Cluster("Security & Governance"):
            pe_nodes = {}
            for pe in inventory["policy_engines"]:
                name = pe['name']
                pe_nodes[pe['policyEngineId']] = IAM(f"Engine: {name}")

        # 2. Control Plane (Agents)
        with Cluster("Agent Runtimes"):
            rt_nodes = []
            for rt in inventory["runtimes"]:
                # Color code: Red for failed, Green for ready
                color = "black" if rt['status'] == "READY" else "red"
                rt_nodes.append(Bedrock(rt['agentRuntimeName']))

        # 3. Managed Infrastructure (Gateway & Memory)
        with Cluster("Infrastructure Resources"):
            gw_nodes = {}
            for gw in inventory["gateways"]:
                gw_nodes[gw['gatewayId']] = Bedrock(f"GW: {gw['name']}")
            
            mem_nodes = [Bedrock(m['id'][:15]) for m in inventory["memories"]]

        # 4. Action Layer (Tools/Targets)
        with Cluster("Tool Targets"):
            target_nodes = []
            for gw_id, target_info in inventory["targets"].items():
                for t in target_info['items']:
                    target_nodes.append(Lambda(t['name']))

        # --- DRAWING THE RELATIONSHIPS ---
        
        # Connect Agents to Memory and Gateway
        for rt in rt_nodes:
            for mem in mem_nodes:
                rt >> Edge(label="Context", color="blue") >> mem
            for gw in gw_nodes.values():
                rt >> Edge(label="Invoke", color="darkgreen") >> gw

        # Connect Policy Engines to Gateways (Governance)
        for pe_id, node in pe_nodes.items():
            # In your JSON, the policy engine governs the gateway
            for gw in gw_nodes.values():
                node >> Edge(style="dashed", color="firebrick", label="Cedar Policy") >> gw

        # Connect Gateway to Lambda Targets
        for gw in gw_nodes.values():
            for target in target_nodes:
                gw >> target

    print("✨ Architecture map 'agentcore_inventory_map.png' has been created!")

if __name__ == "__main__":
    draw()