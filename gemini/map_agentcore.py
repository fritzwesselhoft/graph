#!/usr/bin/env python3

# Collect raw Bedrock AgentCore inventory for later topology building.
# This script only collects and stores AWS data.
# It does not infer graph edges or render diagrams.

import argparse
import json
import logging
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError


LOG = logging.getLogger("collect_agentcore")

# Top-level resource list operations
TOP_LEVEL = {
    "agent_runtimes": "list_agent_runtimes",
    "memories": "list_memories",
    "gateways": "list_gateways",
    "workload_identities": "list_workload_identities",
    "policy_engines": "list_policy_engines",
}

# Child collection operations
RUNTIME_ENDPOINTS = "list_agent_runtime_endpoints"
GATEWAY_TARGETS = "list_gateway_targets"
GET_GATEWAY_TARGET = "get_gateway_target"
POLICIES = "list_policies"


def parse_args() -> argparse.Namespace:
    # Parse CLI args
    parser = argparse.ArgumentParser(description="Collect raw Bedrock AgentCore inventory.")
    parser.add_argument("--regions", nargs="+", required=True, help="AWS regions to scan")
    parser.add_argument("--profile", help="Optional AWS profile")
    parser.add_argument("--output", default="agentcore_inventory.json", help="Output JSON file")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Log level",
    )
    return parser.parse_args()


def make_session(profile: Optional[str]) -> boto3.Session:
    # Build boto3 session
    if profile:
        return boto3.Session(profile_name=profile)
    return boto3.Session()


def make_client(session: boto3.Session, region: str):
    # Build AgentCore control client
    return session.client("bedrock-agentcore-control", region_name=region)


def json_default(obj: Any) -> str:
    # Make non-JSON values serializable
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def extract_list(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Find the first list field in an AWS list response
    for value in response.values():
        if isinstance(value, list):
            return value
    return []


def extract_next_token(response: Dict[str, Any]) -> Optional[str]:
    # Handle common next token field names
    for key in ("nextToken", "NextToken", "next_token"):
        token = response.get(key)
        if token:
            return token
    return None


def record_error(
    errors: List[Dict[str, Any]],
    *,
    scope: str,
    region: str,
    operation: str,
    message: str,
    parent_type: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> None:
    # Store structured errors in the output JSON
    errors.append(
        {
            "scope": scope,
            "region": region,
            "operation": operation,
            "parent_type": parent_type,
            "parent_id": parent_id,
            "message": message,
        }
    )


def get_resource_id(item: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    # Try several possible id keys
    for key in candidates:
        value = item.get(key)
        if value:
            return value
    return None


def call_list_all_pages(
    client,
    operation: str,
    *,
    region: str,
    errors: List[Dict[str, Any]],
    parent_type: Optional[str] = None,
    parent_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    # Call list APIs and collect every page
    try:
        fn = getattr(client, operation)
    except AttributeError:
        message = f"Client does not support operation '{operation}'"
        LOG.warning(message)
        record_error(
            errors,
            scope="operation_lookup",
            region=region,
            operation=operation,
            message=message,
            parent_type=parent_type,
            parent_id=parent_id,
        )
        return {
            "ok": False,
            "count": 0,
            "items": [],
            "pages": 0,
            "error": message,
        }

    all_items: List[Dict[str, Any]] = []
    pages = 0
    next_token: Optional[str] = None

    while True:
        request = dict(kwargs)
        if next_token:
            request["nextToken"] = next_token

        try:
            response = fn(**request)
            pages += 1
            all_items.extend(extract_list(response))

            next_token = extract_next_token(response)
            if not next_token:
                break

        except (ClientError, BotoCoreError, Exception) as exc:
            message = str(exc)
            LOG.warning(
                "Failed %s in %s (parent_type=%s, parent_id=%s): %s",
                operation,
                region,
                parent_type,
                parent_id,
                message,
            )
            record_error(
                errors,
                scope="api_call",
                region=region,
                operation=operation,
                message=message,
                parent_type=parent_type,
                parent_id=parent_id,
            )
            return {
                "ok": False,
                "count": len(all_items),
                "items": all_items,
                "pages": pages,
                "error": message,
            }

    return {
        "ok": True,
        "count": len(all_items),
        "items": all_items,
        "pages": pages,
    }


def call_get(
    client,
    operation: str,
    *,
    region: str,
    errors: List[Dict[str, Any]],
    parent_type: Optional[str] = None,
    parent_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    # Call a get API and return the full raw response
    try:
        fn = getattr(client, operation)
        response = fn(**kwargs)
        return {
            "ok": True,
            "item": response,
        }
    except (ClientError, BotoCoreError, Exception) as exc:
        message = str(exc)
        LOG.warning(
            "Failed %s in %s (parent_type=%s, parent_id=%s): %s",
            operation,
            region,
            parent_type,
            parent_id,
            message,
        )
        record_error(
            errors,
            scope="api_call",
            region=region,
            operation=operation,
            message=message,
            parent_type=parent_type,
            parent_id=parent_id,
        )
        return {
            "ok": False,
            "item": {},
            "error": message,
        }


def collect_top_level_resources(
    client,
    *,
    region: str,
    errors: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    # Collect top-level AgentCore resource inventories
    resources: Dict[str, Dict[str, Any]] = {}

    for resource_name, operation in TOP_LEVEL.items():
        LOG.info("Collecting %s in %s", resource_name, region)
        resources[resource_name] = call_list_all_pages(
            client,
            operation,
            region=region,
            errors=errors,
        )

    return resources


def collect_runtime_endpoints(
    client,
    runtimes: List[Dict[str, Any]],
    *,
    region: str,
    errors: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    # Collect runtime endpoints keyed by runtime id
    result: Dict[str, Dict[str, Any]] = {}

    for runtime in runtimes:
        runtime_id = get_resource_id(runtime, ["agentRuntimeId", "id", "arn", "name"])
        if not runtime_id:
            record_error(
                errors,
                scope="relationship_input",
                region=region,
                operation=RUNTIME_ENDPOINTS,
                message="Could not determine runtime ID from runtime item",
                parent_type="agent_runtime",
                parent_id=None,
            )
            continue

        LOG.info("Collecting runtime endpoints for runtime %s in %s", runtime_id, region)
        result[runtime_id] = call_list_all_pages(
            client,
            RUNTIME_ENDPOINTS,
            region=region,
            errors=errors,
            parent_type="agent_runtime",
            parent_id=runtime_id,
            agentRuntimeId=runtime_id,
        )

    return result


def collect_gateway_targets(
    client,
    gateways: List[Dict[str, Any]],
    *,
    region: str,
    errors: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    # Collect gateway target summaries keyed by gateway id
    result: Dict[str, Dict[str, Any]] = {}

    for gateway in gateways:
        gateway_id = get_resource_id(gateway, ["gatewayId", "id", "arn", "name"])
        if not gateway_id:
            record_error(
                errors,
                scope="relationship_input",
                region=region,
                operation=GATEWAY_TARGETS,
                message="Could not determine gateway ID from gateway item",
                parent_type="gateway",
                parent_id=None,
            )
            continue

        LOG.info("Collecting gateway targets for gateway %s in %s", gateway_id, region)
        result[gateway_id] = call_list_all_pages(
            client,
            GATEWAY_TARGETS,
            region=region,
            errors=errors,
            parent_type="gateway",
            parent_id=gateway_id,
            gatewayIdentifier=gateway_id,
        )

    return result


def collect_gateway_target_details(
    client,
    gateway_targets_by_gateway: Dict[str, Dict[str, Any]],
    *,
    region: str,
    errors: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    # Enrich each discovered gateway target with get_gateway_target
    # Shape: gateway_id -> target_id -> full get response
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for gateway_id, target_list_result in gateway_targets_by_gateway.items():
        result[gateway_id] = {}

        if not target_list_result.get("ok"):
            continue

        for target in target_list_result.get("items", []):
            target_id = get_resource_id(target, ["targetId", "id", "name"])
            if not target_id:
                record_error(
                    errors,
                    scope="relationship_input",
                    region=region,
                    operation=GET_GATEWAY_TARGET,
                    message="Could not determine target ID from gateway target item",
                    parent_type="gateway",
                    parent_id=gateway_id,
                )
                continue

            LOG.info(
                "Collecting gateway target details for gateway %s target %s in %s",
                gateway_id,
                target_id,
                region,
            )

            result[gateway_id][target_id] = call_get(
                client,
                GET_GATEWAY_TARGET,
                region=region,
                errors=errors,
                parent_type="gateway_target",
                parent_id=f"{gateway_id}:{target_id}",
                gatewayIdentifier=gateway_id,
                targetId=target_id,
            )

    return result


def collect_policies_by_engine(
    client,
    engines: List[Dict[str, Any]],
    *,
    region: str,
    errors: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    # Collect policies keyed by policy engine id
    result: Dict[str, Dict[str, Any]] = {}

    for engine in engines:
        engine_id = get_resource_id(engine, ["policyEngineId", "id", "arn", "name"])
        if not engine_id:
            record_error(
                errors,
                scope="relationship_input",
                region=region,
                operation=POLICIES,
                message="Could not determine policy engine ID from engine item",
                parent_type="policy_engine",
                parent_id=None,
            )
            continue

        LOG.info("Collecting policies for engine %s in %s", engine_id, region)
        result[engine_id] = call_list_all_pages(
            client,
            POLICIES,
            region=region,
            errors=errors,
            parent_type="policy_engine",
            parent_id=engine_id,
            policyEngineId=engine_id,
        )

    return result


def collect_region(session: boto3.Session, region: str) -> Dict[str, Any]:
    # Collect all raw data for a single region
    LOG.info("Scanning region %s", region)
    client = make_client(session, region)
    errors: List[Dict[str, Any]] = []

    resources = collect_top_level_resources(client, region=region, errors=errors)

    runtimes = resources.get("agent_runtimes", {}).get("items", [])
    gateways = resources.get("gateways", {}).get("items", [])
    engines = resources.get("policy_engines", {}).get("items", [])

    runtime_endpoints_by_runtime = collect_runtime_endpoints(
        client,
        runtimes,
        region=region,
        errors=errors,
    )

    gateway_targets_by_gateway = collect_gateway_targets(
        client,
        gateways,
        region=region,
        errors=errors,
    )

    gateway_target_details_by_gateway = collect_gateway_target_details(
        client,
        gateway_targets_by_gateway,
        region=region,
        errors=errors,
    )

    policies_by_engine = collect_policies_by_engine(
        client,
        engines,
        region=region,
        errors=errors,
    )

    relationships = {
        "runtime_endpoints_by_runtime": runtime_endpoints_by_runtime,
        "gateway_targets_by_gateway": gateway_targets_by_gateway,
        "gateway_target_details_by_gateway": gateway_target_details_by_gateway,
        "policies_by_engine": policies_by_engine,
    }

    return {
        "region": region,
        "collected_at": datetime.now(UTC).isoformat(),
        "resources": resources,
        "relationships": relationships,
        "errors": errors,
    }


def summarize_region(region_data: Dict[str, Any]) -> Dict[str, Any]:
    # Build a compact per-region summary
    summary: Dict[str, Any] = {
        "top_level_counts": {},
        "relationship_counts": {},
        "error_count": len(region_data.get("errors", [])),
    }

    for name, value in region_data.get("resources", {}).items():
        if isinstance(value, dict) and "count" in value:
            summary["top_level_counts"][name] = value["count"]

    relationships = region_data.get("relationships", {})

    for rel_name, rel_map in relationships.items():
        parent_count = 0
        child_count = 0

        if isinstance(rel_map, dict):
            parent_count = len(rel_map)

            if rel_name == "gateway_target_details_by_gateway":
                # Count detailed target records under each gateway
                for target_details in rel_map.values():
                    if isinstance(target_details, dict):
                        child_count += len(target_details)
            else:
                for rel_result in rel_map.values():
                    if isinstance(rel_result, dict):
                        child_count += rel_result.get("count", 0)

        summary["relationship_counts"][rel_name] = {
            "parents_scanned": parent_count,
            "children_found": child_count,
        }

    return summary


def summarize_inventory(inventory: Dict[str, Any]) -> Dict[str, Any]:
    # Build summary across all regions
    result = {"regions": {}}
    for region_data in inventory.get("regions", []):
        result["regions"][region_data["region"]] = summarize_region(region_data)
    return result


def try_get_account_id(session: boto3.Session) -> Optional[str]:
    # Best effort account id lookup
    try:
        sts = session.client("sts")
        return sts.get_caller_identity().get("Account")
    except Exception as exc:
        LOG.debug("Could not determine AWS account ID: %s", exc)
        return None


def main() -> None:
    # Main entry point
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(message)s",
    )

    session = make_session(args.profile)
    account_id = try_get_account_id(session)

    inventory: Dict[str, Any] = {
        "tool": "collect_agentcore.py",
        "schema_version": "2.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "regions_requested": args.regions,
        "profile": args.profile,
        "account_id": account_id,
        "regions": [],
    }

    for region in args.regions:
        inventory["regions"].append(collect_region(session, region))

    inventory["summary"] = summarize_inventory(inventory)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2, default=json_default)

    print(f"Wrote {args.output}")
    print(json.dumps(inventory["summary"], indent=2))


if __name__ == "__main__":
    main()