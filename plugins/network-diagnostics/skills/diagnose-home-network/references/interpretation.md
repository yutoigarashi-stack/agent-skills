# Interpreting home-network measurements

Use these as conservative diagnostic heuristics, not vendor guarantees.

## Wi-Fi

- Signal of at least -60 dBm and SNR of at least 25 dB make weak radio signal
  less likely. Below -75 dBm or below 15 dB SNR strongly supports a radio issue.
- Link speed is PHY rate, not application throughput. Do not expect throughput
  to equal it.
- Missing RSSI/noise on newer macOS is an instrumentation limitation. It does
  not mean zero signal or noise.
- Placement/channel changes require a controlled before/after run. If signal,
  SNR, gateway latency, and throughput do not improve materially, label them
  ineffective for the observed problem.

## Latency and loss

- Internet loss seen on both `1.1.1.1` and `8.8.8.8` is stronger evidence than
  loss to only one anycast destination.
- A gateway may suppress ICMP. If gateway ping is 100% loss while Internet
  targets respond, do not call that LAN packet loss.
- Compare repeated samples at similar times. Ten packets are a snapshot, not a
  long-term loss estimate.

## DNS

- If public resolvers answer but the router does not, the router may simply not
  expose a DNS listener at its gateway address.
- A few milliseconds of DNS difference does not explain slow bulk transfers.
  Prioritize DNS only when failures or large repeatable delays exist.

## Throughput

- Single and six-connection modes transfer the same total bytes. A parallel to
  single ratio of 1.5 or more suggests a per-flow/path limitation, but does not
  identify its owner.
- Similar low results in both modes, corroborated by `networkQuality`, support a
  WAN/access limitation more than a single-server artifact.
- One remote endpoint cannot prove building-shared congestion. Repeat at busy
  and quiet times and, where possible, compare Ethernet with Wi-Fi.

## Responsiveness and bufferbloat

- `networkQuality` RPM is responsiveness under load; higher is better.
- The script reports `loaded_round_trip_ms_approx = 60000 / RPM`. Compare it
  with idle latency. A repeatable increase above roughly 100 ms supports
  bufferbloat suspicion; several hundred milliseconds is strong evidence of
  poor loaded responsiveness.
- Treat RPM below 200 as a strong warning and 200–400 as worth investigating.
  These are workflow heuristics, not an Apple service-level threshold.

## IPv6 and access technology

- No global address plus no default IPv6 route proves only that this client had
  no usable native IPv6 during the run.
- IPv4-only service can exist over PPPoE or IPoE. IPv6 absence alone cannot
  distinguish them.
- Determine access technology from router WAN status, contract information, or
  the ISP's official support documentation.

## Traceroute hop 2

- RFC1918 (`10/8`, `172.16/12`, `192.168/16`) suggests another private routed
  segment.
- `100.64/10` suggests carrier-grade NAT/shared address space.
- A public address usually indicates an ISP-side routed hop.
- No response means filtered or silent, not absent. Never infer topology from
  `*` alone.
