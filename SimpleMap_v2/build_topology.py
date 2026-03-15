#!/usr/bin/env python3

# Build a graph topology from the AgentCore inventory JSON.
# This step converts raw inventory into graph nodes and edges.
# No diagrams are created here.

import argparse
import json
import re


def parse_args():
    parser = argparse.ArgumentParser(description="Build topology from AgentCore inventory")
    parser.add_argument("--input", required=True, help="Inventory JSON file")
    parser.add_argument("--output", default="agentcore_topology.json", help="Output topology file")
    return parser.parse_args()


def add_node(nodes, node_id, node_type, label, metadata=None):
    # Add a node only once
    if node_id not in nodes:
        nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "metadata": metadata or {},
        }


def add_edge(edges, edge_keys, source, target, relation, metadata=None):
    # Add an edge only once
    key = (source, target, relation)
    if key in edge_keys:
        return

    edge_keys.add(key)
    edges.append(
        {
            "source": source,
            "target": target,
            "relation": relation,
            "metadata": metadata or {},
        }
    )


def parse_gateway_arn_from_policy(statement):
    # Extract gateway ARN from Cedar policy text
    match = re.search(r'AgentCore::Gateway::"([^"]+)"', statement)
    if match:
        return match.group(1)
    return None


def build_gateway_arn_index(gateways):
    # Map gateway ARN -> gateway ID so policy statements link to real nodes
    index = {}

    for gateway in gateways:
        gateway_id = gateway.get("gatewayId")
        gateway_arn = gateway.get("gatewayArn")

        if gateway_id and gateway_arn:
            index[gateway_arn] = gateway_id

        # Fallback in case list output does not include gatewayArn
        if gateway_id and not gateway_arn:
            inferred_arn = f"arn:aws:bedrock-agentcore:{extract_region_from_gateway_id(gateway_id)}"
            # This fallback is incomplete on purpose and not used unless ARN exists.
            # Real linking depends on the policy statement ARN and list output fields.

    return index


def extract_region_from_gateway_id(gateway_id):
    # Placeholder helper kept minimal; not relied on for linking
    return ""


def build_topology(data):
    nodes = {}
    edges = []
    edge_keys = set()

    for region in data["regions"]:
        resources = region["resources"]
        relationships = region["relationships"]

        runtimes = resources.get("agent_runtimes", {}).get("items", [])
        memories = resources.get("memories", {}).get("items", [])
        gateways = resources.get("gateways", {}).get("items", [])
        policy_engines = resources.get("policy_engines", {}).get("items", [])

        gateway_arn_to_id = {}
        for g in gateways:
            gateway_id = g.get("gatewayId")
            gateway_arn = g.get("gatewayArn")

            add_node(nodes, gateway_id, "gateway", g.get("name", gateway_id), g)

            if gateway_id and gateway_arn:
                gateway_arn_to_id[gateway_arn] = gateway_id

        # Add runtime nodes
        for r in runtimes:
            runtime_id = r.get("agentRuntimeId")
            if runtime_id:
                add_node(nodes, runtime_id, "runtime", r.get("agentRuntimeName", runtime_id), r)

        # Add memory nodes
        for m in memories:
            memory_id = m.get("id")
            if memory_id:
                add_node(nodes, memory_id, "memory", memory_id, m)

        # Add policy engine nodes
        for pe in policy_engines:
            engine_id = pe.get("policyEngineId")
            if engine_id:
                add_node(nodes, engine_id, "policy_engine", pe.get("name", engine_id), pe)

        # Add gateway target nodes and gateway -> target edges
        for gateway_id, targets in relationships.get("gateway_targets_by_gateway", {}).items():
            for target in targets.get("items", []):
                target_id = target.get("targetId")
                if not target_id:
                    continue

                target_node_id = f"target:{target_id}"
                add_node(
                    nodes,
                    target_node_id,
                    "gateway_target",
                    target.get("name", target_id),
                    target,
                )
                add_edge(edges, edge_keys, gateway_id, target_node_id, "invokes")

        # Add lambda nodes and target -> lambda edges
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

                target_node_id = f"target:{target_id}"
                add_edge(edges, edge_keys, target_node_id, lambda_node_id, "executes")

        # Add policy engine -> gateway edges from Cedar statements
        for engine_id, policies in relationships.get("policies_by_engine", {}).items():
            for policy in policies.get("items", []):
                statement = (
                    policy.get("definition", {})
                    .get("cedar", {})
                    .get("statement", "")
                )

                gateway_arn = parse_gateway_arn_from_policy(statement)
                if not gateway_arn:
                    continue

                gateway_id = gateway_arn_to_id.get(gateway_arn)

                # Fallback: gateway ARN ends with gateway/<gatewayId>
                if not gateway_id and ":gateway/" in gateway_arn:
                    gateway_id = gateway_arn.split(":gateway/")[-1]

                if not gateway_id:
                    continue

                edge_metadata = {
                    "policyId": policy.get("policyId"),
                    "policyName": policy.get("name"),
                    "gatewayArn": gateway_arn,
                }

                add_edge(edges, edge_keys, engine_id, gateway_id, "applies_to", edge_metadata)

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
    }


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