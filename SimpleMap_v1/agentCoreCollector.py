#!/usr/bin/env python3

"""
Collect AgentCore resources needed to reconstruct the architecture diagram.
"""

import argparse
import json
import logging
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError


LOG = logging.getLogger("agentcore")

TOP_LEVEL = {
    "agent_runtimes": "list_agent_runtimes",
    "memories": "list_memories",
    "gateways": "list_gateways",
    "workload_identities": "list_workload_identities",
    "policy_engines": "list_policy_engines",
}

RUNTIME_ENDPOINTS = "list_agent_runtime_endpoints"
GATEWAY_TARGETS = "list_gateway_targets"
POLICIES = "list_policies"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regions", nargs="+", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--output", default="agentcore_inventory.json")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def make_session(profile: Optional[str]):
    if profile:
        return boto3.Session(profile_name=profile)
    return boto3.Session()


def make_client(session, region):
    return session.client("bedrock-agentcore-control", region_name=region)


def extract_list(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    for v in response.values():
        if isinstance(v, list):
            return v
    return []


def call_list(client, op, **kwargs):
    try:
        fn = getattr(client, op)
        resp = fn(**kwargs)
        items = extract_list(resp)
        return {"ok": True, "count": len(items), "items": items}
    except (ClientError, BotoCoreError, Exception) as e:
        LOG.warning("Failed %s: %s", op, e)
        return {"ok": False, "count": 0, "items": [], "error": str(e)}


def json_default(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def collect_region(session, region):
    LOG.info("Scanning %s", region)

    client = make_client(session, region)

    data = {
        "region": region,
        "collected_at": datetime.now(UTC).isoformat(),
        "resources": {}
    }

    for name, op in TOP_LEVEL.items():
        data["resources"][name] = call_list(client, op)

    runtimes = data["resources"]["agent_runtimes"]["items"]
    endpoints = {}

    for r in runtimes:
        rid = r.get("agentRuntimeId") or r.get("id")
        if rid:
            endpoints[rid] = call_list(
                client,
                RUNTIME_ENDPOINTS,
                agentRuntimeId=rid
            )

    data["resources"]["runtime_endpoints_by_runtime"] = endpoints

    gateways = data["resources"]["gateways"]["items"]
    targets = {}

    for g in gateways:
        gid = g.get("gatewayId") or g.get("id") or g.get("name")
        if gid:
            targets[gid] = call_list(
                client,
                GATEWAY_TARGETS,
                gatewayIdentifier=gid
            )

    data["resources"]["gateway_targets_by_gateway"] = targets

    engines = data["resources"]["policy_engines"]["items"]
    policies = {}

    for e in engines:
        eid = e.get("policyEngineId") or e.get("id")
        if eid:
            policies[eid] = call_list(
                client,
                POLICIES,
                policyEngineId=eid
            )

    data["resources"]["policies_by_engine"] = policies

    return data


def summarize(inventory):
    summary = {"regions": {}}

    for r in inventory["regions"]:
        region = r["region"]
        s = {}

        for k, v in r["resources"].items():
            if isinstance(v, dict) and "count" in v:
                s[k] = v["count"]

        summary["regions"][region] = s

    return summary


def main():
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(message)s"
    )

    session = make_session(args.profile)

    inventory = {
        "tool": "agentcore_diagram_inventory",
        "generated_at": datetime.now(UTC).isoformat(),
        "regions": []
    }

    for region in args.regions:
        inventory["regions"].append(collect_region(session, region))

    inventory["summary"] = summarize(inventory)

    with open(args.output, "w") as f:
        json.dump(inventory, f, indent=2, default=json_default)

    print(f"Wrote {args.output}")
    print(json.dumps(inventory["summary"], indent=2))


if __name__ == "__main__":
    main()