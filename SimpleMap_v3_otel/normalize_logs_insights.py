#!/usr/bin/env python3

# Normalize CloudWatch Logs Insights span results into a clean span list.
# Input: logs-insights-results.json
# Output: normalized_spans.json

import argparse
import json


def parse_args():
    parser = argparse.ArgumentParser(description="Normalize Logs Insights span results")
    parser.add_argument("--input", required=True, help="Logs Insights JSON file")
    parser.add_argument(
        "--output",
        default="normalized_spans.json",
        help="Output normalized spans JSON file",
    )
    return parser.parse_args()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def as_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def normalize_record(record):
    # Logs Insights result already has some promoted fields at the top level.
    # The full raw span lives under @message.
    raw = record.get("@message", {}) or {}

    resource_attrs = raw.get("resource", {}).get("attributes", {}) or {}
    span_attrs = raw.get("attributes", {}) or {}
    scope = raw.get("scope", {}) or {}
    status = raw.get("status", {}) or {}

    trace_id = raw.get("traceId") or record.get("traceId")
    span_id = raw.get("spanId") or record.get("spanId")
    parent_span_id = raw.get("parentSpanId")

    name = raw.get("name") or record.get("name")
    kind = raw.get("kind")
    timestamp = record.get("@timestamp")

    duration_nano = raw.get("durationNano")
    if duration_nano is None:
        duration_nano = record.get("durationNano")

    service = (
        record.get("service")
        or resource_attrs.get("service.name")
        or resource_attrs.get("aws.local.service")
        or span_attrs.get("aws.local.service")
    )

    environment = (
        record.get("environment")
        or resource_attrs.get("deployment.environment.name")
        or span_attrs.get("aws.local.environment")
    )

    status_code = (
        status.get("code")
        or record.get("statusCode")
        or span_attrs.get("http.status_code")
        or span_attrs.get("http.response.status_code")
    )

    normalized = {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": parent_span_id,
        "name": name,
        "kind": kind,
        "timestamp": timestamp,
        "durationNano": as_int(duration_nano),
        "service": service,
        "environment": environment,
        "statusCode": str(status_code) if status_code is not None else None,
        "scope": {
            "name": scope.get("name"),
            "version": scope.get("version"),
        },
        "resource_attributes": resource_attrs,
        "attributes": span_attrs,
    }

    return normalized


def main():
    args = parse_args()

    data = load_json(args.input)

    if not isinstance(data, list):
        raise ValueError("Expected input file to contain a JSON list")

    normalized_spans = []
    skipped = 0

    for record in data:
        if not isinstance(record, dict):
            skipped += 1
            continue

        span = normalize_record(record)

        # Keep only records that are real spans
        if not span["traceId"] or not span["spanId"] or not span["name"]:
            skipped += 1
            continue

        normalized_spans.append(span)

    output = {
        "schema_version": "1.0",
        "source": "logs_insights",
        "span_count": len(normalized_spans),
        "skipped_count": skipped,
        "spans": normalized_spans,
    }

    save_json(args.output, output)

    print(f"Wrote normalized spans: {args.output}")
    print(f"Spans: {len(normalized_spans)}")
    print(f"Skipped: {skipped}")


if __name__ == "__main__":
    main()