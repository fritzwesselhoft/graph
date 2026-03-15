#!/usr/bin/env python3

# Merge CloudWatch OTEL spans into the existing topology as observed edges.
# Input 1: topology JSON from build_topology.py
# Input 2: spans JSON from aws logs filter-log-events on aws/spans
# Output: updated topology JSON with observed edges added

import argparse
import json
import re
from urllib.parse import urlparse


def parse_args():
    parser = argparse.ArgumentParser(description="Merge OTEL spans into topology")
    parser.add_argument("--topology", required=True, help="Existing topology JSON")
    parser.add_argument("--spans", required=True, help="CloudWatch aws/spans export JSON")
    parser.add_argument(
        "--output",
        default="agentcore_topology_observed.json",
        help="Output merged topology JSON",
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


def add_or_merge_edge(edges, edge_index, source, target, relation, edge_kind, metadata):
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

    if existing.get("edge_kind") != "observed" and edge_kind == "observed":
        existing["edge_kind"] = "observed"

    merge_dict(existing.setdefault("metadata", {}), metadata or {})


def parse_log_events(spans_payload):
    # CloudWatch Logs filter-log-events output uses events[] or searchedLogStreams + events[]
    events = spans_payload.get("events", [])
    parsed = []

    for event in events:
        raw_message = event.get("message")
        if not raw_message:
            continue

        try:
            span = json.loads(raw_message)
        except Exception:
            continue

        span["_cw_timestamp"] = event.get("timestamp")
        span["_cw_log_stream"] = event.get("logStreamName")
        parsed.append(span)

    return parsed


def extract_runtime_and_endpoint(span):
    # Example service.name / aws.local.service:
    # customer_support_agent.DEFAULT
    resource_attrs = span.get("resource", {}).get("attributes", {})
    attrs = span.get("attributes", {})

    service_name = (
        resource_attrs.get("service.name")
        or resource_attrs.get("aws.local.service")
        or attrs.get("aws.local.service")
    )

    cloud_resource_id = resource_attrs.get("cloud.resource_id", "")

    runtime_id = None
    endpoint_name = None
    endpoint_node_id = None

    # Strongest source: runtime endpoint ARN-like cloud.resource_id
    # arn:...:runtime/customer_support_agent-XDGSrz7NRI/runtime-endpoint/DEFAULT:DEFAULT
    if ":runtime/" in cloud_resource_id and "/runtime-endpoint/" in cloud_resource_id:
        try:
            runtime_part = cloud_resource_id.split(":runtime/")[1]
            runtime_id = runtime_part.split("/runtime-endpoint/")[0]

            endpoint_part = runtime_part.split("/runtime-endpoint/")[1]
            endpoint_name = endpoint_part.split(":")[0]
        except Exception:
            pass

    # Fallback: service name ending in .DEFAULT
    if not endpoint_name and service_name and "." in service_name:
        endpoint_name = service_name.split(".")[-1]

    if runtime_id and endpoint_name:
        endpoint_node_id = f"runtime_endpoint:{runtime_id}:{endpoint_name}"

    return runtime_id, endpoint_name, endpoint_node_id


def extract_gateway_id_from_span(span):
    resource_attrs = span.get("resource", {}).get("attributes", {})
    attrs = span.get("attributes", {})

    # Best explicit field
    gateway_id = attrs.get("gateway.id")
    if gateway_id:
        return gateway_id

    # Gateway ARN in resource attrs
    gateway_arn = attrs.get("aws.resource.arn") or resource_attrs.get("cloud.resource_id")
    if gateway_arn and ":gateway/" in gateway_arn:
        return gateway_arn.split(":gateway/")[-1]

    # Gateway hostname in outbound HTTP url
    http_url = attrs.get("http.url")
    if http_url:
        try:
            host = urlparse(http_url).netloc
            # customersupport-gw-irxbzczbfi.gateway.bedrock-agentcore.us-east-2.amazonaws.com
            if ".gateway.bedrock-agentcore." in host:
                return host.split(".gateway.bedrock-agentcore.")[0]
        except Exception:
            pass

    aws_remote_service = attrs.get("aws.remote.service")
    if aws_remote_service and ".gateway.bedrock-agentcore." in aws_remote_service:
        return aws_remote_service.split(".gateway.bedrock-agentcore.")[0]

    return None


def summarize_span(span):
    attrs = span.get("attributes", {})
    return {
        "traceId": span.get("traceId"),
        "spanId": span.get("spanId"),
        "parentSpanId": span.get("parentSpanId"),
        "name": span.get("name"),
        "kind": span.get("kind"),
        "session.id": attrs.get("session.id"),
        "http.url": attrs.get("http.url"),
        "gateway.id": attrs.get("gateway.id"),
    }


def merge_traces(topology, spans_payload):
    nodes = topology.get("nodes", [])
    edges = topology.get("edges", [])
    edge_index = build_edge_index(edges)

    node_ids = {node["id"] for node in nodes}
    spans = parse_log_events(spans_payload)

    for span in spans:
        trace_id = span.get("traceId")
        if not trace_id:
            continue

        runtime_id, endpoint_name, endpoint_node_id = extract_runtime_and_endpoint(span)
        gateway_id = extract_gateway_id_from_span(span)

        span_meta = {
            "observed_in": [
                summarize_span(span)
            ]
        }

        # Add observed runtime -> endpoint if both sides exist in topology
        if runtime_id and endpoint_node_id and runtime_id in node_ids and endpoint_node_id in node_ids:
            add_or_merge_edge(
                edges,
                edge_index,
                runtime_id,
                endpoint_node_id,
                "exposes",
                "observed",
                span_meta,
            )

        # Add observed endpoint -> gateway if both exist
        if endpoint_node_id and gateway_id and endpoint_node_id in node_ids and gateway_id in node_ids:
            add_or_merge_edge(
                edges,
                edge_index,
                endpoint_node_id,
                gateway_id,
                "calls",
                "observed",
                span_meta,
            )

        # Optional shortcut edge runtime -> gateway for easier rendering/querying
        if runtime_id and gateway_id and runtime_id in node_ids and gateway_id in node_ids:
            add_or_merge_edge(
                edges,
                edge_index,
                runtime_id,
                gateway_id,
                "calls",
                "observed",
                span_meta,
            )

    topology["trace_ready"] = True
    topology["observed_traces_merged"] = True
    return topology


def main():
    args = parse_args()

    topology = load_json(args.topology)
    spans_payload = load_json(args.spans)

    merged = merge_traces(topology, spans_payload)
    save_json(args.output, merged)

    print(f"Wrote merged topology: {args.output}")
    print(f"Nodes: {len(merged.get('nodes', []))}")
    print(f"Edges: {len(merged.get('edges', []))}")


if __name__ == "__main__":
    main()