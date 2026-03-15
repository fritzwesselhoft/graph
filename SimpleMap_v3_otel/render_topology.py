#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from diagrams import Diagram, Edge, Cluster
from diagrams.aws.compute import Lambda
from diagrams.aws.general import General
from diagrams.aws.ml import Bedrock
from diagrams.aws.security import IAM


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="agentcore_topology")
    return p.parse_args()


def shorten(label, n=26):
    if not label:
        return ""
    return label if len(label) <= n else label[: n - 3] + "..."


def make_node(node):
    t = node["type"]
    label = shorten(node.get("label", node["id"]))

    if t == "policy_engine":
        return IAM(f"Policy\n{label}")
    if t == "gateway":
        return Bedrock(f"Gateway\n{label}")
    if t == "gateway_target":
        return General(f"Target\n{label}")
    if t == "lambda":
        return Lambda(label)
    if t == "runtime":
        return Bedrock(label)
    if t == "memory":
        return Bedrock(f"Memory\n{label}")
    if t == "runtime_endpoint":
        return General(f"Endpoint\n{label}")

    return General(label)


def edge_style(rel):
    # Support both old and new relation names
    if rel in ("applies_to", "uses"):
        return Edge(label="uses", style="dashed")
    if rel in ("invokes", "routes_to"):
        return Edge(label="routes")
    if rel in ("executes", "implements"):
        return Edge(label="implements")
    if rel == "exposes":
        return Edge(label="exposes")
    return Edge(label=rel)


def connected_ids(edges):
    ids = set()
    for e in edges:
        ids.add(e["source"])
        ids.add(e["target"])
    return ids


def render(topology, output):
    nodes = topology["nodes"]
    edges = topology["edges"]

    connected = connected_ids(edges)
    connected_nodes = [n for n in nodes if n["id"] in connected]
    unlinked_nodes = [n for n in nodes if n["id"] not in connected]

    rendered = {}

    with Diagram(
        "AgentCore Topology",
        filename=output,
        show=False,
        direction="LR",
        graph_attr={
            "splines": "ortho",
            "nodesep": "1.0",
            "ranksep": "1.1",
            "fontsize": "18",
            "pad": "0.4",
        },
    ):
        with Cluster("AgentCore"):
            # Show active behavior first
            with Cluster("Control Path"):
                for n in connected_nodes:
                    if n["type"] in (
                        "runtime",
                        "runtime_endpoint",
                        "policy_engine",
                        "gateway",
                        "gateway_target",
                    ):
                        rendered[n["id"]] = make_node(n)

            # Show discovered resources second
            inventory_rendered = []
            if unlinked_nodes:
                with Cluster("Discovered / Unlinked"):
                    for n in unlinked_nodes:
                        if n["type"] in ("runtime", "memory"):
                            node = make_node(n)
                            rendered[n["id"]] = node
                            inventory_rendered.append(node)

                # Keep unlinked resources grouped visually
                for i in range(len(inventory_rendered) - 1):
                    inventory_rendered[i] - Edge(style="invis") - inventory_rendered[i + 1]

        # AWS resources stay outside AgentCore
        with Cluster("AWS Resources"):
            for n in connected_nodes:
                if n["type"] == "lambda":
                    rendered[n["id"]] = make_node(n)

        # Draw actual edges
        for e in edges:
            s = rendered.get(e["source"])
            t = rendered.get(e["target"])
            if not s or not t:
                continue
            s >> edge_style(e["relation"]) >> t


def main():
    args = parse_args()

    with open(args.input) as f:
        topology = json.load(f)

    render(topology, str(Path(args.output)))
    print(f"Rendered diagram: {args.output}.png")


if __name__ == "__main__":
    main()