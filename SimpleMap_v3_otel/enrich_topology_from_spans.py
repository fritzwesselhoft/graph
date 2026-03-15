#!/usr/bin/env python3

# Enrich topology with observed edges from normalized OTEL spans.
# Input:
#   1. agentcore_topology.json
#   2. normalized_spans.json
# Output:
#   agentcore_topology_observed.json

import argparse
import json
from urllib.parse import urlparse


def parse_args():
    parser = argparse.ArgumentParser(description="Enrich topology with observed edges from spans")
    parser.add_argument("--topology", required=True, help="Topology JSON file")
    parser.add_argument("--spans", required=True, help="Normalized spans JSON file")
    parser.add_argument(
        "--output",
        default="agentcore_topology_observed.json",
        help="Output enriched topology JSON file",
    )
    return parser.parse_args()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


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


def build_edge_index(edges):
    index = {}
    for edge in edges:
        key = (edge["source"], edge["target"], edge["relation"])
        index[key] = edge
    return index


def add_or_merge_edge(edges, edge_index, source, target, relation, edge_kind="observed", metadata=None):
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

    # Observed evidence should win over configured when same edge exists
    if edge_kind == "observed":
        existing["edge_kind"] = "observed"

    merge_dict(existing.setdefault("metadata", {}), metadata or {})


def build_node_index(nodes):
    return {node["id"]: node for node in nodes}


def extract_runtime_and_endpoint(span):
    # Pull runtime id and endpoint from cloud.resource_id
    # Example:
    # arn:aws:bedrock-agentcore:us-east-2:...:runtime/customer_support_agent-XDGSrz7NRI/runtime-endpoint/DEFAULT:DEFAULT
    resource_attrs = span.get("resource_attributes", {}) or {}
    cloud_resource_id = resource_attrs.get("cloud.resource_id", "")

    runtime_id = None
    endpoint_name = None
    endpoint_node_id = None

    if ":runtime/" in cloud_resource_id and "/runtime-endpoint/" in cloud_resource_id:
        try:
            runtime_part = cloud_resource_id.split(":runtime/")[1]
            runtime_id = runtime_part.split("/runtime-endpoint/")[0]

            endpoint_part = runtime_part.split("/runtime-endpoint/")[1]
            endpoint_name = endpoint_part.split(":")[0]
        except Exception:
            pass

    if runtime_id and endpoint_name:
        endpoint_node_id = f"runtime_endpoint:{runtime_id}:{endpoint_name}"

    return runtime_id, endpoint_name, endpoint_node_id


def extract_gateway_id(span):
    attrs = span.get("attributes", {}) or {}

    gateway_id = attrs.get("gateway.id")
    if gateway_id:
        return gateway_id

    http_url = attrs.get("http.url")
    if http_url:
        try:
            host = urlparse(http_url).netloc
            if ".gateway.bedrock-agentcore." in host:
                return host.split(".gateway.bedrock-agentcore.")[0]
        except Exception:
            pass

    remote_service = attrs.get("aws.remote.service")
    if remote_service and ".gateway.bedrock-agentcore." in remote_service:
        return remote_service.split(".gateway.bedrock-agentcore.")[0]

    resource_arn = attrs.get("aws.resource.arn")
    if resource_arn and ":gateway/" in resource_arn:
        return resource_arn.split(":gateway/")[-1]

    return None


def summarize_span(span):
    attrs = span.get("attributes", {}) or {}

    return {
        "traceId": span.get("traceId"),
        "spanId": span.get("spanId"),
        "parentSpanId": span.get("parentSpanId"),
        "name": span.get("name"),
        "kind": span.get("kind"),
        "timestamp": span.get("timestamp"),
        "service": span.get("service"),
        "session.id": attrs.get("session.id"),
        "http.url": attrs.get("http.url"),
        "gateway.id": attrs.get("gateway.id"),
    }


def enrich_topology(topology, spans_doc):
    nodes = topology.get("nodes", [])
    edges = topology.get("edges", [])
    node_index = build_node_index(nodes)
    edge_index = build_edge_index(edges)

    spans = spans_doc.get("spans", [])
    observed_summary = {
        "runtime_to_endpoint_edges": 0,
        "endpoint_to_gateway_edges": 0,
        "runtime_to_gateway_edges": 0,
    }

    for span in spans:
        trace_id = span.get("traceId")
        if not trace_id:
            continue

        runtime_id, endpoint_name, endpoint_node_id = extract_runtime_and_endpoint(span)
        gateway_id = extract_gateway_id(span)

        span_meta = {
            "observed_in": [summarize_span(span)]
        }

        # Observed runtime -> endpoint
        if runtime_id and endpoint_node_id and runtime_id in node_index and endpoint_node_id in node_index:
            before = len(edges)
            add_or_merge_edge(
                edges,
                edge_index,
                runtime_id,
                endpoint_node_id,
                "exposes",
                edge_kind="observed",
                metadata=span_meta,
            )
            if len(edges) > before:
                observed_summary["runtime_to_endpoint_edges"] += 1

        # Observed endpoint -> gateway
        if endpoint_node_id and gateway_id and endpoint_node_id in node_index and gateway_id in node_index:
            before = len(edges)
            add_or_merge_edge(
                edges,
                edge_index,
                endpoint_node_id,
                gateway_id,
                "calls",
                edge_kind="observed",
                metadata=span_meta,
            )
            if len(edges) > before:
                observed_summary["endpoint_to_gateway_edges"] += 1

        # Observed runtime -> gateway shortcut
        if runtime_id and gateway_id and runtime_id in node_index and gateway_id in node_index:
            before = len(edges)
            add_or_merge_edge(
                edges,
                edge_index,
                runtime_id,
                gateway_id,
                "calls",
                edge_kind="observed",
                metadata=span_meta,
            )
            if len(edges) > before:
                observed_summary["runtime_to_gateway_edges"] += 1

    topology["trace_ready"] = True
    topology["observed_traces_merged"] = True
    topology["observed_summary"] = observed_summary

    return topology


def main():
    args = parse_args()

    topology = load_json(args.topology)
    spans_doc = load_json(args.spans)

    enriched = enrich_topology(topology, spans_doc)
    save_json(args.output, enriched)

    print(f"Wrote enriched topology: {args.output}")
    print(f"Nodes: {len(enriched.get('nodes', []))}")
    print(f"Edges: {len(enriched.get('edges', []))}")
    print("Observed summary:")
    print(json.dumps(enriched.get("observed_summary", {}), indent=2))


if __name__ == "__main__":
    main()