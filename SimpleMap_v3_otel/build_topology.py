#!/usr/bin/env python3

# Build topology from AgentCore inventory.
# This version is trace-ready:
# - config/inventory edges use edge_kind="configured"
# - future OTEL edges can be added as edge_kind="observed"

import argparse
import json
import re


def parse_args():
    parser = argparse.ArgumentParser(description="Build topology from AgentCore inventory")
    parser.add_argument("--input", required=True, help="Inventory JSON file")
    parser.add_argument("--output", default="agentcore_topology.json", help="Output topology file")
    return parser.parse_args()


def add_node(nodes, node_id, node_type, label, metadata=None):
    if not node_id:
        return

    if node_id not in nodes:
        nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "metadata": metadata or {},
        }


def merge_dict(target, extra):
    if not extra:
        return target

    for key, value in extra.items():
        if key not in target:
            target[key] = value
            continue

        if isinstance(target[key], list) and isinstance(value, list):
            seen = set()
            merged = []
            for item in target[key] + value:
                marker = json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
                if marker not in seen:
                    seen.add(marker)
                    merged.append(item)
            target[key] = merged
        elif isinstance(target[key], dict) and isinstance(value, dict):
            merge_dict(target[key], value)

    return target


def add_edge(edges, edge_index, source, target, relation, edge_kind="configured", metadata=None):
    if not source or not target:
        return

    key = (source, target, relation)

    if key not in edge_index:
        edge = {
            "source": source,
            "target": target,
            "relation": relation,
            "edge_kind": edge_kind,
            "metadata": metadata or {},
        }
        edges.append(edge)
        edge_index[key] = edge
        return

    existing = edge_index[key]

    # Preserve observed edges if they appear later
    if existing.get("edge_kind") != "observed" and edge_kind == "observed":
        existing["edge_kind"] = "observed"

    merge_dict(existing["metadata"], metadata or {})


def parse_gateway_arn_from_policy(statement):
    match = re.search(r'AgentCore::Gateway::"([^"]+)"', statement)
    return match.group(1) if match else None


def build_topology(data):
    nodes = {}
    edges = []
    edge_index = {}

    for region in data.get("regions", []):
        resources = region.get("resources", {})
        relationships = region.get("relationships", {})

        runtimes = resources.get("agent_runtimes", {}).get("items", [])
        memories = resources.get("memories", {}).get("items", [])
        gateways = resources.get("gateways", {}).get("items", [])
        policy_engines = resources.get("policy_engines", {}).get("items", [])
        workload_identities = resources.get("workload_identities", {}).get("items", [])

        gateway_arn_to_id = {}

        # Gateways
        for gateway in gateways:
            gateway_id = gateway.get("gatewayId")
            gateway_label = gateway.get("name", gateway_id)
            add_node(nodes, gateway_id, "gateway", gateway_label, gateway)

            gateway_arn = gateway.get("gatewayArn")
            if gateway_arn:
                gateway_arn_to_id[gateway_arn] = gateway_id

        # Runtimes
        for runtime in runtimes:
            runtime_id = runtime.get("agentRuntimeId")
            runtime_label = runtime.get("agentRuntimeName", runtime_id)
            add_node(nodes, runtime_id, "runtime", runtime_label, runtime)

        # Memories
        for memory in memories:
            memory_id = memory.get("id")
            add_node(nodes, memory_id, "memory", memory_id, memory)

        # Policy engines
        for engine in policy_engines:
            engine_id = engine.get("policyEngineId")
            engine_label = engine.get("name", engine_id)
            add_node(nodes, engine_id, "policy_engine", engine_label, engine)

        # Workload identities as metadata-only nodes for now
        for wi in workload_identities:
            wi_name = wi.get("name")
            wi_arn = wi.get("workloadIdentityArn")
            if wi_name and wi_arn:
                add_node(
                    nodes,
                    f"workload_identity:{wi_name}",
                    "workload_identity",
                    wi_name,
                    wi,
                )

        # Runtime endpoints
        for runtime_id, endpoint_result in relationships.get("runtime_endpoints_by_runtime", {}).items():
            for endpoint in endpoint_result.get("items", []):
                endpoint_id = endpoint.get("id") or endpoint.get("name")
                if not endpoint_id:
                    continue

                endpoint_node_id = f"runtime_endpoint:{runtime_id}:{endpoint_id}"
                endpoint_label = endpoint.get("name", endpoint_id)

                add_node(
                    nodes,
                    endpoint_node_id,
                    "runtime_endpoint",
                    endpoint_label,
                    endpoint,
                )

                add_edge(
                    edges,
                    edge_index,
                    runtime_id,
                    endpoint_node_id,
                    "exposes",
                    edge_kind="configured",
                )

        # Gateway targets
        for gateway_id, targets_result in relationships.get("gateway_targets_by_gateway", {}).items():
            for target in targets_result.get("items", []):
                target_id = target.get("targetId")
                if not target_id:
                    continue

                target_node_id = f"target:{target_id}"
                target_label = target.get("name", target_id)

                add_node(
                    nodes,
                    target_node_id,
                    "gateway_target",
                    target_label,
                    target,
                )

                add_edge(
                    edges,
                    edge_index,
                    gateway_id,
                    target_node_id,
                    "routes_to",
                    edge_kind="configured",
                )

        # Gateway target details -> Lambda
        for gateway_id, target_details in relationships.get("gateway_target_details_by_gateway", {}).items():
            for target_id, detail in target_details.items():
                item = detail.get("item", {})
                lambda_info = (
                    item.get("targetConfiguration", {})
                    .get("mcp", {})
                    .get("lambda", {})
                )

                lambda_arn = lambda_info.get("lambdaArn")
                if not lambda_arn:
                    continue

                lambda_node_id = f"lambda:{lambda_arn}"
                lambda_label = lambda_arn.split(":")[-1]

                lambda_metadata = {
                    "lambdaArn": lambda_arn,
                    "gatewayId": gateway_id,
                    "targetId": target_id,
                    "toolSchema": lambda_info.get("toolSchema", {}),
                }

                add_node(nodes, lambda_node_id, "lambda", lambda_label, lambda_metadata)

                add_edge(
                    edges,
                    edge_index,
                    f"target:{target_id}",
                    lambda_node_id,
                    "implements",
                    edge_kind="configured",
                )

        # Policy engine -> Gateway
        for engine_id, policies_result in relationships.get("policies_by_engine", {}).items():
            for policy in policies_result.get("items", []):
                statement = (
                    policy.get("definition", {})
                    .get("cedar", {})
                    .get("statement", "")
                )

                gateway_arn = parse_gateway_arn_from_policy(statement)
                if not gateway_arn:
                    continue

                gateway_id = gateway_arn_to_id.get(gateway_arn)
                if not gateway_id and ":gateway/" in gateway_arn:
                    gateway_id = gateway_arn.split(":gateway/")[-1]

                if not gateway_id:
                    continue

                add_edge(
                    edges,
                    edge_index,
                    engine_id,
                    gateway_id,
                    "uses",
                    edge_kind="configured",
                    metadata={
                        "policies": [
                            {
                                "policyId": policy.get("policyId"),
                                "policyName": policy.get("name"),
                                "gatewayArn": gateway_arn,
                            }
                        ]
                    },
                )

    topology = {
        "schema_version": "1.1",
        "trace_ready": True,
        "nodes": list(nodes.values()),
        "edges": edges,
    }

    return topology


def main():
    args = parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    topology = build_topology(data)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(topology, f, indent=2)

    print(f"Wrote topology file: {args.output}")
    print(f"Nodes: {len(topology['nodes'])}")
    print(f"Edges: {len(topology['edges'])}")


if __name__ == "__main__":
    main()