#!/usr/bin/env python3
"""Safety-first macOS home-network measurements with labeled JSON output."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import ipaddress
import json
import os
import platform
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


TOOLS = {
    "route": "/sbin/route",
    "ifconfig": "/sbin/ifconfig",
    "ping": "/sbin/ping",
    "traceroute": "/usr/sbin/traceroute",
    "dig": "/usr/bin/dig",
    "network_quality": "/usr/bin/networkQuality",
    "system_profiler": "/usr/sbin/system_profiler",
    "osascript": "/usr/bin/osascript",
}
PUBLIC_TARGETS = {"cloudflare": "1.1.1.1", "google": "8.8.8.8"}
DNS_NAME = "example.com"
DOWNLOAD_HOST = "speed.cloudflare.com"
DOWNLOAD_ENDPOINT = f"https://{DOWNLOAD_HOST}/__down"
DEFAULT_DOWNLOAD_MB = 25
PARALLEL_CONNECTIONS = 6
PRIVILEGED_WIFI_APPLESCRIPT = (
    'do shell script "/usr/bin/wdutil info" with administrator privileges'
)


def run_command(command: list[str], timeout: int = 30) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "returncode": None,
            "stdout": getattr(exc, "stdout", "") or "",
            "stderr": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }


def error_text(result: dict[str, Any]) -> str | None:
    if result["returncode"] == 0:
        return None
    detail = (result["stderr"] or result["stdout"]).strip()
    return detail[-500:] if detail else f"exit status {result['returncode']}"


def number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def find_dict_with_key(value: Any, key: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if key in value:
            return value
        for child in value.values():
            found = find_dict_with_key(child, key)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_dict_with_key(child, key)
            if found:
                return found
    return None


def default_route(family: str) -> dict[str, Any]:
    measured = run_command([TOOLS["route"], "-n", "get", f"-{family}", "default"])
    gateway = re.search(r"^\s*gateway:\s*(\S+)", measured["stdout"], re.MULTILINE)
    interface = re.search(r"^\s*interface:\s*(\S+)", measured["stdout"], re.MULTILINE)
    return {
        "present": measured["returncode"] == 0 and bool(gateway),
        "gateway": gateway.group(1).split("%", 1)[0] if gateway else None,
        "interface": interface.group(1) if interface else None,
        "error": error_text(measured),
    }


def collect_wifi(interface: str | None, allow_privileged: bool) -> dict[str, Any]:
    output: dict[str, Any] = {
        "interface": interface,
        "signal_dbm": None,
        "noise_dbm": None,
        "snr_db": None,
        "link_speed_mbps": None,
        "standard": None,
        "channel": None,
        "band": None,
        "channel_width_mhz": None,
        "source": None,
        "error": None,
    }
    measured = run_command(
        [TOOLS["system_profiler"], "SPAirPortDataType", "-json"], timeout=45
    )
    try:
        data = json.loads(measured["stdout"])
        parent = find_dict_with_key(data, "spairport_current_network_information")
        info = parent["spairport_current_network_information"] if parent else None
        if not isinstance(info, dict):
            output["error"] = "system_profiler did not expose current Wi-Fi metrics"
            info = {}
        output.update(
            {
                "signal_dbm": number(info.get("spairport_network_signal")),
                "noise_dbm": number(info.get("spairport_network_noise")),
                "link_speed_mbps": number(info.get("spairport_network_rate")),
                "standard": info.get("spairport_network_phymode"),
                "source": "system_profiler",
            }
        )
        channel_text = str(info.get("spairport_network_channel", ""))
        channel = re.search(r"^(\d+)", channel_text)
        band = re.search(r"\(([^,)]+)", channel_text)
        width = re.search(r"(\d+)\s*MHz", channel_text, re.IGNORECASE)
        output["channel"] = int(channel.group(1)) if channel else None
        output["band"] = band.group(1) if band else None
        output["channel_width_mhz"] = int(width.group(1)) if width else None
        if output["signal_dbm"] is not None and output["noise_dbm"] is not None:
            output["snr_db"] = round(output["signal_dbm"] - output["noise_dbm"], 1)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        output["error"] = f"system_profiler parse error: {exc}"

    if allow_privileged and (output["signal_dbm"] is None or output["noise_dbm"] is None):
        privileged = run_command(
            [TOOLS["osascript"], "-e", PRIVILEGED_WIFI_APPLESCRIPT], timeout=120
        )
        if privileged["returncode"] == 0:
            text = privileged["stdout"]
            patterns = {
                "signal_dbm": r"^\s*RSSI\s*:\s*(-?\d+(?:\.\d+)?)",
                "noise_dbm": r"^\s*Noise\s*:\s*(-?\d+(?:\.\d+)?)",
                "link_speed_mbps": r"^\s*Tx Rate\s*:\s*(\d+(?:\.\d+)?)",
            }
            for key, pattern in patterns.items():
                match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
                if match:
                    output[key] = float(match.group(1))
            phy = re.search(r"^\s*PHY Mode\s*:\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
            if phy:
                mode = phy.group(1)
                output["standard"] = f"802.{mode}" if mode.startswith("11") else mode
            channel = re.search(
                r"^\s*Channel\s*:\s*(\d)g(\d+)/(\d+)",
                text,
                re.MULTILINE | re.IGNORECASE,
            )
            if channel:
                output["band"] = f"{channel.group(1)}GHz"
                output["channel"] = int(channel.group(2))
                output["channel_width_mhz"] = int(channel.group(3))
            output["source"] = "system_profiler+privileged_wdutil"
            output["error"] = None
        else:
            output["error"] = "privileged Wi-Fi metrics unavailable: " + (
                error_text(privileged) or "authorization failed"
            )

    if output["signal_dbm"] is not None and output["noise_dbm"] is not None:
        output["snr_db"] = round(output["signal_dbm"] - output["noise_dbm"], 1)
    missing = [
        key
        for key in ("signal_dbm", "noise_dbm", "link_speed_mbps", "standard", "channel")
        if output[key] is None
    ]
    if missing and output["error"] is None:
        output["error"] = "unavailable via non-privileged system_profiler: " + ", ".join(missing)
    return output


def collect_ipv6(interface: str | None, route6: dict[str, Any]) -> dict[str, Any]:
    count = 0
    error = None
    if interface:
        measured = run_command([TOOLS["ifconfig"], interface])
        error = error_text(measured)
        for raw in re.findall(r"^\s*inet6\s+(\S+)", measured["stdout"], re.MULTILINE):
            try:
                if ipaddress.ip_address(raw.split("%", 1)[0]).is_global:
                    count += 1
            except ValueError:
                pass
    else:
        error = "active interface could not be determined"
    return {
        "global_address_present": count > 0,
        "global_address_count": count,
        "global_addresses_stored": False,
        "default_route_present": route6["present"],
        "default_gateway": route6["gateway"],
        "error": error or route6["error"],
    }


def ping_one(target: str, count: int) -> dict[str, Any]:
    measured = run_command(
        [TOOLS["ping"], "-n", "-c", str(count), "-W", "1000", target], timeout=25
    )
    text = measured["stdout"] + "\n" + measured["stderr"]
    loss = re.search(r"([\d.]+)% packet loss", text)
    rtt = re.search(
        r"(?:round-trip|rtt) min/avg/max/(?:stddev|mdev) = "
        r"([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
        text,
    )
    packets = re.search(r"(\d+) packets transmitted, (\d+) packets received", text)
    return {
        "target": target,
        "sent": int(packets.group(1)) if packets else count,
        "received": int(packets.group(2)) if packets else None,
        "loss_percent": float(loss.group(1)) if loss else None,
        "avg_ms": float(rtt.group(2)) if rtt else None,
        "max_ms": float(rtt.group(3)) if rtt else None,
        "error": error_text(measured) if not loss else None,
    }


def collect_latency(gateway: str | None, count: int) -> dict[str, Any]:
    targets = {"default_gateway": gateway, **PUBLIC_TARGETS}
    valid = {name: target for name, target in targets.items() if target}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {name: executor.submit(ping_one, target, count) for name, target in valid.items()}
        output = {name: future.result() for name, future in futures.items()}
    if gateway is None:
        output["default_gateway"] = {
            "target": None,
            "sent": 0,
            "received": None,
            "loss_percent": None,
            "avg_ms": None,
            "max_ms": None,
            "error": "default gateway not found",
        }
    return output


def parse_traceroute(text: str, max_hops: int) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.*)$", line)
        if not match or int(match.group(1)) > max_hops:
            continue
        responders: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        tokens = re.findall(r"\d+(?:\.\d+){3}|\*|\d+(?:\.\d+)?\s*ms", match.group(2))
        for token in tokens:
            if re.fullmatch(r"\d+(?:\.\d+){3}", token):
                current = next((item for item in responders if item["ip"] == token), None)
                if current is None:
                    current = {"ip": token, "rtt_ms": []}
                    responders.append(current)
            elif token != "*" and current is not None:
                current["rtt_ms"].append(float(re.search(r"[\d.]+", token).group(0)))
        hops.append(
            {"hop": int(match.group(1)), "responders": responders, "timed_out": not responders}
        )
    return hops


def traceroute_attempt(method: str, target: str, max_hops: int) -> dict[str, Any]:
    command = [TOOLS["traceroute"]]
    if method == "icmp":
        command.append("-I")
    command.extend(["-n", "-m", str(max_hops), "-q", "3", "-w", "2", target])
    measured = run_command(command, timeout=35)
    return {
        "method": method,
        "hops": parse_traceroute(measured["stdout"], max_hops),
        "error": error_text(measured),
    }


def collect_traceroute() -> dict[str, Any]:
    target = PUBLIC_TARGETS["cloudflare"]
    udp = traceroute_attempt("udp", target, 4)
    selected = udp
    attempts = [udp]
    if not any(hop["responders"] for hop in udp["hops"]):
        icmp = traceroute_attempt("icmp", target, 4)
        attempts.append(icmp)
        if any(hop["responders"] for hop in icmp["hops"]):
            selected = icmp
    return {
        "target": target,
        "selected_method": selected["method"],
        "hops": selected["hops"],
        "attempts": attempts,
        "error": selected["error"],
    }


def dns_query(server: str) -> dict[str, Any]:
    measured = run_command(
        [
            TOOLS["dig"],
            f"@{server}",
            DNS_NAME,
            "A",
            "+tries=1",
            "+time=2",
            "+stats",
        ],
        timeout=5,
    )
    query_time = re.search(r"Query time:\s*(\d+)\s*msec", measured["stdout"])
    status = re.search(r"status:\s*([A-Z]+)", measured["stdout"])
    return {
        "response_ms": float(query_time.group(1)) if query_time else None,
        "dns_status": status.group(1) if status else None,
        "error": error_text(measured) if not query_time else None,
    }


def dns_server_samples(server: str, samples: int) -> dict[str, Any]:
    results = [dns_query(server) for _ in range(samples)]
    timings = [item["response_ms"] for item in results if item["response_ms"] is not None]
    return {
        "server": server,
        "samples_ms": timings,
        "avg_ms": round(sum(timings) / len(timings), 2) if timings else None,
        "max_ms": max(timings) if timings else None,
        "failure_percent": round(100 * (samples - len(timings)) / samples, 1),
        "error": next((item["error"] for item in results if item["error"]), None),
    }


def collect_dns(gateway: str | None, samples: int) -> dict[str, Any]:
    servers = {"router": gateway, **PUBLIC_TARGETS}
    valid = {name: server for name, server in servers.items() if server}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            name: executor.submit(dns_server_samples, server, samples)
            for name, server in valid.items()
        }
        output = {name: future.result() for name, future in futures.items()}
    if gateway is None:
        output["router"] = {
            "server": None,
            "samples_ms": [],
            "avg_ms": None,
            "max_ms": None,
            "failure_percent": 100.0,
            "error": "default gateway not found",
        }
    return {"query": DNS_NAME, "samples_per_server": samples, "servers": output}


class SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname != DOWNLOAD_HOST:
            raise urllib.error.HTTPError(newurl, code, "unsafe cross-host redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_once(byte_count: int) -> dict[str, Any]:
    url = DOWNLOAD_ENDPOINT + "?" + urllib.parse.urlencode({"bytes": byte_count})
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "agent-skills-network-diagnostics/1.0",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
            "Connection": "close",
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        SameHostRedirectHandler(),
    )
    started = time.monotonic()
    received = 0
    try:
        with opener.open(request, timeout=120) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != DOWNLOAD_HOST:
                raise RuntimeError("download endpoint redirected to an unexpected host")
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
        elapsed = time.monotonic() - started
        return {
            "requested_bytes": byte_count,
            "received_bytes": received,
            "elapsed_seconds": round(elapsed, 3),
            "mbps": round(received * 8 / elapsed / 1_000_000, 2),
            "complete": received == byte_count,
            "error": None,
        }
    except Exception as exc:
        elapsed = time.monotonic() - started
        return {
            "requested_bytes": byte_count,
            "received_bytes": received,
            "elapsed_seconds": round(elapsed, 3),
            "mbps": round(received * 8 / elapsed / 1_000_000, 2) if received else None,
            "complete": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def collect_throughput(total_bytes: int) -> dict[str, Any]:
    single = download_once(total_bytes)
    per_connection, remainder = divmod(total_bytes, PARALLEL_CONNECTIONS)
    sizes = [
        per_connection + (1 if index < remainder else 0)
        for index in range(PARALLEL_CONNECTIONS)
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=PARALLEL_CONNECTIONS) as executor:
        connections = list(executor.map(download_once, sizes))
    elapsed = time.monotonic() - started
    received = sum(item["received_bytes"] for item in connections)
    parallel = {
        "connections": PARALLEL_CONNECTIONS,
        "requested_bytes": total_bytes,
        "received_bytes": received,
        "elapsed_seconds": round(elapsed, 3),
        "mbps": round(received * 8 / elapsed / 1_000_000, 2) if received else None,
        "complete": all(item["complete"] for item in connections),
        "connection_errors": [item["error"] for item in connections if item["error"]],
    }
    ratio = None
    if single["mbps"] and parallel["mbps"]:
        ratio = round(parallel["mbps"] / single["mbps"], 2)
    return {
        "endpoint": DOWNLOAD_ENDPOINT,
        "single_connection": single,
        "parallel_6_connections": parallel,
        "parallel_to_single_ratio": ratio,
    }


def collect_network_quality(interface: str | None) -> dict[str, Any]:
    command = [TOOLS["network_quality"], "-c", "-M", "90"]
    if interface:
        command.extend(["-I", interface])
    measured = run_command(command, timeout=110)
    try:
        raw = json.loads(measured["stdout"])
    except json.JSONDecodeError:
        raw = None
    if not isinstance(raw, dict):
        return {
            "rpm": None,
            "idle_latency_ms": None,
            "loaded_round_trip_ms_approx": None,
            "idle_to_loaded_increase_ms_approx": None,
            "download_mbps": None,
            "upload_mbps": None,
            "test_endpoint": None,
            "error": error_text(measured) or "networkQuality returned invalid JSON",
        }
    rpm = number(raw.get("responsiveness"))
    idle = number(raw.get("base_rtt"))
    loaded = 60000 / rpm if rpm and rpm > 0 else None
    return {
        "rpm": round(rpm, 2) if rpm is not None else None,
        "idle_latency_ms": round(idle, 2) if idle is not None else None,
        "loaded_round_trip_ms_approx": round(loaded, 2) if loaded is not None else None,
        "idle_to_loaded_increase_ms_approx": round(loaded - idle, 2)
        if loaded is not None and idle is not None
        else None,
        "download_mbps": round(float(raw["dl_throughput"]) / 1_000_000, 2)
        if raw.get("dl_throughput") is not None
        else None,
        "upload_mbps": round(float(raw["ul_throughput"]) / 1_000_000, 2)
        if raw.get("ul_throughput") is not None
        else None,
        "test_endpoint": raw.get("test_endpoint"),
        "error": error_text(measured),
    }


def safe_label(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip()).strip("-.")
    return cleaned[:80] or "measurement"


def plan(args: argparse.Namespace) -> dict[str, Any]:
    fixed_mb = 0 if args.skip_throughput else args.download_megabytes * 2
    return {
        "will_execute": args.run,
        "label": args.label,
        "output_directory": str(args.output_dir),
        "external_destinations": {
            "ping_traceroute_dns": PUBLIC_TARGETS,
            "dns_query_name": DNS_NAME,
            "throughput": None if args.skip_throughput else DOWNLOAD_ENDPOINT,
            "network_quality": None
            if args.skip_network_quality
            else "Apple-selected networkQuality server",
        },
        "fixed_download_megabytes": fixed_mb,
        "privileged_wifi": {
            "enabled": args.allow_privileged_wifi,
            "scope": "Apple wdutil info only via the macOS administrator dialog"
            if args.allow_privileged_wifi
            else "none",
        },
        "network_quality_additional_traffic": "none"
        if args.skip_network_quality
        else "dynamic download and upload test traffic controlled by Apple",
        "privacy": {
            "stores": ["router IP", "route hop IPs", "radio and performance metrics"],
            "does_not_store": [
                "hostname",
                "SSID",
                "BSSID",
                "MAC address",
                "full global IPv6 address",
            ],
        },
    }


def write_private_json(directory: Path, label: str, started: dt.datetime, data: dict[str, Any]) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = started.strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"{timestamp}-{safe_label(label)}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label", help="comparison label; do not include private information")
    parser.add_argument("--run", action="store_true", help="execute network measurements")
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--download-megabytes", type=int, default=DEFAULT_DOWNLOAD_MB)
    parser.add_argument("--ping-count", type=int, default=10)
    parser.add_argument("--dns-samples", type=int, default=5)
    parser.add_argument("--skip-throughput", action="store_true")
    parser.add_argument("--skip-network-quality", action="store_true")
    parser.add_argument(
        "--allow-privileged-wifi",
        action="store_true",
        help="open the macOS administrator dialog for wdutil radio metrics",
    )
    args = parser.parse_args()
    if not 1 <= args.download_megabytes <= 100:
        parser.error("--download-megabytes must be between 1 and 100")
    if not 1 <= args.ping_count <= 20:
        parser.error("--ping-count must be between 1 and 20")
    if not 1 <= args.dns_samples <= 10:
        parser.error("--dns-samples must be between 1 and 10")
    return args


def main() -> int:
    args = parse_args()
    planned = plan(args)
    print(json.dumps(planned, ensure_ascii=False, indent=2), flush=True)
    if not args.run:
        print("Plan only. Add --run after reviewing destinations and traffic.", flush=True)
        return 0
    if platform.system() != "Darwin":
        print("error: this skill supports macOS only", file=sys.stderr)
        return 2
    if os.geteuid() == 0:
        print("error: do not run network diagnostics as root", file=sys.stderr)
        return 2
    missing_tools = [path for path in TOOLS.values() if not Path(path).is_file()]
    if missing_tools:
        print(f"error: required macOS tools not found: {missing_tools}", file=sys.stderr)
        return 2

    started = dt.datetime.now(dt.timezone.utc)
    route4 = default_route("inet")
    route6 = default_route("inet6")
    interface = route4["interface"]

    print("Measuring Wi-Fi and IPv6...", flush=True)
    wifi = collect_wifi(interface, args.allow_privileged_wifi)
    ipv6 = collect_ipv6(interface, route6)
    print("Measuring latency and the first four route hops...", flush=True)
    latency = collect_latency(route4["gateway"], args.ping_count)
    route_trace = collect_traceroute()
    print("Comparing DNS resolvers...", flush=True)
    dns = collect_dns(route4["gateway"], args.dns_samples)

    if args.skip_throughput:
        throughput: dict[str, Any] = {"skipped": True, "reason": "--skip-throughput"}
    else:
        print("Measuring single and six-connection throughput...", flush=True)
        throughput = collect_throughput(args.download_megabytes * 1_000_000)

    if args.skip_network_quality:
        quality: dict[str, Any] = {"skipped": True, "reason": "--skip-network-quality"}
    else:
        print("Measuring Apple networkQuality...", flush=True)
        time.sleep(3)
        quality = collect_network_quality(interface)

    finished = dt.datetime.now(dt.timezone.utc)
    document = {
        "schema_version": 2,
        "label": args.label,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "host": {
            "platform": platform.platform(),
            "active_interface": interface,
            "hostname_stored": False,
        },
        "measurement_config": {
            "ping_count": args.ping_count,
            "dns_samples": args.dns_samples,
            "throughput_enabled": not args.skip_throughput,
            "network_quality_enabled": not args.skip_network_quality,
            "privileged_wifi_enabled": args.allow_privileged_wifi,
            "download_megabytes_each_mode": None
            if args.skip_throughput
            else args.download_megabytes,
            "parallel_connections": PARALLEL_CONNECTIONS,
        },
        "safety_plan": planned,
        "default_ipv4_route": route4,
        "wifi": wifi,
        "ipv6": ipv6,
        "latency": latency,
        "traceroute": route_trace,
        "dns": dns,
        "throughput": throughput,
        "network_quality": quality,
    }
    output = write_private_json(args.output_dir, args.label, started, document)
    print(output, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
