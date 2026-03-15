#!/usr/bin/env python3

import json
from datetime import datetime, UTC


def node_id(kind, name):
    return f"{kind}:{name}"


def add_node(graph, node):
    if node["id"] not in graph["node_index"]:
        graph["node_index"][node["id"]] = node
        graph["nodes"].append(node)


def add_edge(graph, from_id, to_id, relationship, confidence, reason):
    graph["edges"].append({
        "from": from_id,
        "to": to_id,
        "relationship": relationship,
        "confidence": confidence,
        "reason": reason,
    })


def get_name(obj, *keys):
    for key in keys:
        value = obj.get(key)
        if value:
            return value
    return None


def normalize_status(obj):
    return obj.get("status") or obj.get("runtimeStatus") or obj.get("gatewayStatus") or "UNKNOWN"


with open("agentcore_inventory.json", "r") as f:
    inventory = json.load(f)

graph = {
    "metadata": {
        "source": "agentcore_inventory.json",
        "generated_at": datetime.now(UTC).isoformat(),
        "regions": [r["region"] for r in inventory["regions"]],
    },
    "nodes": [],
    "edges": [],
    "node_index": {},
}

for region_data in inventory["regions"]:
    region = region_data["region"]
    resources = region_data["resources"]

    # Runtimes
    for runtime in resources.get("agent_runtimes", {}).get("items", []):
        name = get_name(runtime, "name", "agentRuntimeName", "agentRuntimeId")
        if not name:
            continue
        add_node(graph, {
            "id": node_id("runtime", name),
            "kind": "runtime",
            "name": name,
            "region": region,
            "status": normalize_status(runtime),
        })

    # Memories
    for memory in resources.get("memories", {}).get("items", []):
        name = get_name(memory, "name", "memoryName", "memoryId")
        if not name:
            continue
        add_node(graph, {
            "id": node_id("memory", name),
            "kind": "memory",
            "name": name,
            "region": region,
            "status": normalize_status(memory),
        })

    # Gateways
    for gateway in resources.get("gateways", {}).get("items", []):
        name = get_name(gateway, "name", "gatewayId")
        if not name:
            continue
        add_node(graph, {
            "id": node_id("gateway", name),
            "kind": "gateway",
            "name": name,
            "region": region,
            "status": normalize_status(gateway),
        })

    # Identities
    for identity in resources.get("workload_identities", {}).get("items", []):
        name = get_name(identity, "name", "workloadIdentityId")
        if not name:
            continue
        add_node(graph, {
            "id": node_id("identity", name),
            "kind": "identity",
            "name": name,
            "region": region,
            "status": normalize_status(identity),
        })

    # Policy engines
    for engine in resources.get("policy_engines", {}).get("items", []):
        name = get_name(engine, "name", "policyEngineId")
        if not name:
            continue
        add_node(graph, {
            "id": node_id("policy_engine", name),
            "kind": "policy_engine",
            "name": name,
            "region": region,
            "status": normalize_status(engine),
        })

    # Endpoints + confirmed runtime->endpoint edges
    for runtime_id, result in resources.get("runtime_endpoints_by_runtime", {}).items():
        for endpoint in result.get("items", []):
            ep_name = get_name(endpoint, "name", "agentRuntimeEndpointName", "agentRuntimeEndpointId", "endpointName")
            if not ep_name:
                continue

            add_node(graph, {
                "id": node_id("endpoint", ep_name),
                "kind": "endpoint",
                "name": ep_name,
                "region": region,
                "status": normalize_status(endpoint),
            })

            runtime_name = runtime_id
            add_edge(
                graph,
                node_id("runtime", runtime_name),
                node_id("endpoint", ep_name),
                "has_endpoint",
                "confirmed",
                "Listed under runtime_endpoints_by_runtime"
            )

    # Targets + confirmed gateway->target edges
    for gateway_id, result in resources.get("gateway_targets_by_gateway", {}).items():
        for target in result.get("items", []):
            target_name = get_name(target, "name", "targetName", "targetId")
            if not target_name:
                continue

            add_node(graph, {
                "id": node_id("target", target_name),
                "kind": "target",
                "name": target_name,
                "region": region,
                "status": normalize_status(target),
            })

            add_edge(
                graph,
                node_id("gateway", gateway_id),
                node_id("target", target_name),
                "has_target",
                "confirmed",
                "Listed under gateway_targets_by_gateway"
            )

    # Policies + confirmed engine->policy edges
    for engine_id, result in resources.get("policies_by_engine", {}).items():
        for policy in result.get("items", []):
            policy_name = get_name(policy, "name", "policyName", "policyId")
            if not policy_name:
                continue

            add_node(graph, {
                "id": node_id("policy", policy_name),
                "kind": "policy",
                "name": policy_name,
                "region": region,
                "status": normalize_status(policy),
            })

            add_edge(
                graph,
                node_id("policy_engine", engine_id),
                node_id("policy", policy_name),
                "has_policy",
                "confirmed",
                "Listed under policies_by_engine"
            )

# very simple inference rules
runtime_nodes = [n for n in graph["nodes"] if n["kind"] == "runtime"]
gateway_nodes = [n for n in graph["nodes"] if n["kind"] == "gateway"]
memory_nodes = [n for n in graph["nodes"] if n["kind"] == "memory"]
identity_nodes = [n for n in graph["nodes"] if n["kind"] == "identity"]
engine_nodes = [n for n in graph["nodes"] if n["kind"] == "policy_engine"]

for runtime in runtime_nodes:
    rname = runtime["name"].lower().replace("_", "").replace("-", "")

    for gateway in gateway_nodes:
        gname = gateway["name"].lower().replace("_", "").replace("-", "")
        if "customer" in rname and "customer" in gname:
            add_edge(graph, runtime["id"], gateway["id"], "uses_gateway", "inferred", "Names suggest same stack")

    for memory in memory_nodes:
        mname = memory["name"].lower().replace("_", "").replace("-", "")
        if "customer" in rname and "customer" in mname:
            add_edge(graph, runtime["id"], memory["id"], "uses_memory", "inferred", "Names suggest same stack")

    for identity in identity_nodes:
        iname = identity["name"].lower().replace("_", "").replace("-", "")
        if rname in iname or iname.startswith(rname):
            add_edge(graph, runtime["id"], identity["id"], "uses_identity", "inferred", "Identity name matches runtime")

for gateway in gateway_nodes:
    gname = gateway["name"].lower().replace("_", "").replace("-", "")
    for identity in identity_nodes:
        iname = identity["name"].lower().replace("_", "").replace("-", "")
        if gname in iname or iname.startswith(gname):
            add_edge(graph, gateway["id"], identity["id"], "uses_identity", "inferred", "Identity name matches gateway")

    for engine in engine_nodes:
        ename = engine["name"].lower().replace("_", "").replace("-", "")
        if "customer" in gname and "customer" in ename:
            add_edge(graph, gateway["id"], engine["id"], "protected_by", "inferred", "Names suggest same stack")

del graph["node_index"]

with open("/Users/fritzwesselhoft/APP_GRAPH/gentcore_graph.json", "w") as f:
    json.dump(graph, f, indent=2)

print("Wrote agentcore_graph.json")
