#!/usr/bin/env python3
"""Compare key metrics from two network_diagnostics.py JSON results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


METRICS = {
    "wifi.signal_dbm": ("wifi", "signal_dbm"),
    "wifi.snr_db": ("wifi", "snr_db"),
    "wifi.link_speed_mbps": ("wifi", "link_speed_mbps"),
    "latency.gateway.avg_ms": ("latency", "default_gateway", "avg_ms"),
    "latency.cloudflare.avg_ms": ("latency", "cloudflare", "avg_ms"),
    "latency.google.avg_ms": ("latency", "google", "avg_ms"),
    "latency.cloudflare.loss_percent": ("latency", "cloudflare", "loss_percent"),
    "latency.google.loss_percent": ("latency", "google", "loss_percent"),
    "dns.router.avg_ms": ("dns", "servers", "router", "avg_ms"),
    "dns.cloudflare.avg_ms": ("dns", "servers", "cloudflare", "avg_ms"),
    "dns.google.avg_ms": ("dns", "servers", "google", "avg_ms"),
    "throughput.single_mbps": ("throughput", "single_connection", "mbps"),
    "throughput.parallel_mbps": ("throughput", "parallel_6_connections", "mbps"),
    "network_quality.rpm": ("network_quality", "rpm"),
    "network_quality.idle_latency_ms": ("network_quality", "idle_latency_ms"),
    "network_quality.loaded_round_trip_ms_approx": (
        "network_quality",
        "loaded_round_trip_ms_approx",
    ),
}


def nested(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        raise ValueError(f"{path}: expected schema_version 2")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    before = load(args.before)
    after = load(args.after)
    rows = []
    for name, path in METRICS.items():
        old = nested(before, path)
        new = nested(after, path)
        delta = round(new - old, 3) if isinstance(old, (int, float)) and isinstance(new, (int, float)) else None
        rows.append({"metric": name, "before": old, "after": new, "delta": delta})
    output = {
        "before": {"file": str(args.before), "label": before.get("label")},
        "after": {"file": str(args.after), "label": after.get("label")},
        "same_measurement_config": before.get("measurement_config") == after.get("measurement_config"),
        "metrics": rows,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
