1. run collector

(.venv) fritzwesselhoft@fritzs-MBP SimpleMap_v3_otel % python collect_agentcore.py --regions us-east-2 --output agentcore_inventory_v3.json
INFO Found credentials in shared credentials file: ~/.aws/credentials
INFO Scanning region us-east-2
INFO Collecting agent_runtimes in us-east-2
INFO Collecting memories in us-east-2
INFO Collecting gateways in us-east-2
INFO Collecting workload_identities in us-east-2
INFO Collecting policy_engines in us-east-2
INFO Collecting runtime endpoints for runtime customer_support_agent-XDGSrz7NRI in us-east-2
INFO Collecting runtime endpoints for runtime HealthcareAppt-2K1Z4lCK10 in us-east-2
INFO Collecting gateway targets for gateway customersupport-gw-irxbzczbfi in us-east-2
INFO Collecting gateway target details for gateway customersupport-gw-irxbzczbfi target 2M4Q0D8KKB in us-east-2
INFO Collecting policies for engine customersupport_pe-5iw0xn29kt in us-east-2
Wrote agentcore_inventory_v3.json
{
  "regions": {
    "us-east-2": {
      "top_level_counts": {
        "agent_runtimes": 2,
        "memories": 1,
        "gateways": 1,
        "workload_identities": 3,
        "policy_engines": 1
      },
      "relationship_counts": {
        "runtime_endpoints_by_runtime": {
          "parents_scanned": 2,
          "children_found": 2
        },
        "gateway_targets_by_gateway": {
          "parents_scanned": 1,
          "children_found": 1
        },
        "gateway_target_details_by_gateway": {
          "parents_scanned": 1,
          "children_found": 1
        },
        "policies_by_engine": {
          "parents_scanned": 1,
          "children_found": 2
        }
      },
      "error_count": 0
    }
  }
}
(.venv) fritzwesselhoft@fritzs-MBP SimpleMap_v3_otel % 



2.Build Topology

Run:

(.venv) fritzwesselhoft@fritzs-MBP SimpleMap_v3_otel % python build_topology.py --input agentcore_inventory_v3.json --output agentcore_topology.json

Wrote topology file: agentcore_topology.json
Nodes: 12
Edges: 5
(.venv) fritzwesselhoft@fritzs-MBP SimpleMap_v3_otel % 


3.Render Topology
 % python render_topology.py --input agentcore_topology.json --output agentcore_topology
Rendered diagram: agentcore_topology.png
(.venv) fritzwesselhoft@fritzs-MBP SimpleMap_v3_otel % 


4.Add Otel Stuff