#!/usr/bin/env python3
"""Reconstruct GitHub Actions job-rounded usage with the authenticated gh CLI."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str
    private: bool

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def run_json(command: list[str]) -> Any:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{' '.join(command[:3])} failed: {detail}")
    return json.loads(result.stdout)


def gh_api(endpoint: str, fields: dict[str, str] | None = None) -> Any:
    command = ["gh", "api", "--method", "GET", endpoint]
    for key, value in (fields or {}).items():
        command.extend(["-f", f"{key}={value}"])
    return run_json(command)


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO date: {value}") from exc


def current_owner() -> str:
    data = gh_api("user")
    return str(data["login"])


def discover_repositories(owner: str, include_public: bool) -> list[Repository]:
    data = run_json(
        [
            "gh",
            "repo",
            "list",
            owner,
            "--limit",
            "1000",
            "--json",
            "nameWithOwner,isPrivate,isArchived",
        ]
    )
    repositories = []
    for item in data:
        if item["isArchived"]:
            continue
        if not include_public and not item["isPrivate"]:
            continue
        repo_owner, name = item["nameWithOwner"].split("/", 1)
        repositories.append(Repository(repo_owner, name, bool(item["isPrivate"])))
    return repositories


def resolve_repositories(
    owner: str, names: list[str], include_public: bool
) -> list[Repository]:
    if not names:
        return discover_repositories(owner, include_public)

    repositories = []
    for value in names:
        full_name = value if "/" in value else f"{owner}/{value}"
        data = gh_api(f"repos/{full_name}")
        if data["archived"]:
            continue
        if not include_public and not data["private"]:
            continue
        repo_owner, name = full_name.split("/", 1)
        repositories.append(Repository(repo_owner, name, bool(data["private"])))
    return repositories


def paginate(endpoint: str, fields: dict[str, str], array_key: str) -> list[Any]:
    items: list[Any] = []
    page = 1
    while True:
        page_fields = {**fields, "per_page": "100", "page": str(page)}
        data = gh_api(endpoint, page_fields)
        batch = data[array_key]
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def list_runs(repo: Repository, date_range: str) -> list[dict[str, Any]]:
    return paginate(
        f"repos/{repo.full_name}/actions/runs",
        {"created": date_range},
        "workflow_runs",
    )


def list_jobs(repo: Repository, run: dict[str, Any]) -> list[dict[str, Any]]:
    return paginate(
        f"repos/{repo.full_name}/actions/runs/{run['id']}/jobs",
        {},
        "jobs",
    )


def parse_timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def runner_os(job: dict[str, Any]) -> str:
    labels = {str(label).lower() for label in job.get("labels", [])}
    joined = " ".join(labels)
    if "self-hosted" in labels:
        return "self-hosted"
    if "macos" in joined:
        return "macos"
    if "windows" in joined:
        return "windows"
    if "ubuntu" in joined or "linux" in joined:
        return "linux"
    return "unknown"


def usage_class(repo: Repository, run: dict[str, Any], os_name: str) -> str:
    if os_name == "self-hosted":
        return "free-self-hosted"
    if not repo.private:
        return "free-public"
    actor = str(run.get("actor", {}).get("login", ""))
    path = str(run.get("path", ""))
    if actor == "dependabot[bot]" and (
        path.startswith("dynamic/dependabot") or run.get("event") == "dynamic"
    ):
        return "free-dependabot"
    return "metered-private"


def automation_kind(run: dict[str, Any]) -> str:
    actor = str(run.get("actor", {}).get("login", ""))
    branch = str(run.get("head_branch") or "")
    if actor == "dependabot[bot]" or branch.startswith("dependabot/"):
        return "dependabot"
    if actor == "renovate[bot]" or branch.startswith("renovate/"):
        return "renovate"
    return "other"


def collect_run(
    repo: Repository, run: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    records = []
    for job in list_jobs(repo, run):
        if job.get("conclusion") == "skipped":
            continue
        started = job.get("started_at")
        completed = job.get("completed_at")
        if not started or not completed:
            continue
        seconds = max(
            0,
            int((parse_timestamp(completed) - parse_timestamp(started)).total_seconds()),
        )
        rounded_minutes = math.ceil(seconds / 60)
        os_name = runner_os(job)
        records.append(
            {
                "repo": repo.full_name,
                "workflow": run.get("name") or run.get("path") or "unknown",
                "run_id": run["id"],
                "job": job.get("name") or "unknown",
                "os": os_name,
                "usage_class": usage_class(repo, run, os_name),
                "seconds": seconds,
                "rounded_minutes": rounded_minutes,
                "conclusion": job.get("conclusion") or "unknown",
            }
        )
    return records, automation_kind(run)


def markdown_report(
    owner: str,
    start: dt.date,
    end: dt.date,
    repositories: list[Repository],
    runs_by_repo: dict[str, list[dict[str, Any]]],
    records: list[dict[str, Any]],
) -> str:
    aggregates: dict[tuple[str, str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"run_ids": set(), "jobs": 0, "failures": 0, "minutes": 0, "seconds": 0}
    )
    for record in records:
        key = (
            record["repo"],
            record["workflow"],
            record["os"],
            record["usage_class"],
        )
        row = aggregates[key]
        row["run_ids"].add(record["run_id"])
        row["jobs"] += 1
        row["failures"] += record["conclusion"] == "failure"
        row["minutes"] += record["rounded_minutes"]
        row["seconds"] += record["seconds"]

    output = [
        "# GitHub Actions usage audit",
        "",
        f"- Owner: `{owner}`",
        f"- Period: `{start.isoformat()}` through `{end.isoformat()}`",
        f"- Repositories inspected: {len(repositories)}",
        "- Minutes are reconstructed by rounding each completed job up separately.",
        "",
        "| Repository | Workflow | OS | Usage class | Runs | Jobs | Failed jobs | Rounded minutes |",
        "|---|---|---:|---|---:|---:|---:|---:|",
    ]
    sorted_rows = sorted(
        aggregates.items(),
        key=lambda item: (item[1]["minutes"], item[0]),
        reverse=True,
    )
    for (repo, workflow, os_name, usage), row in sorted_rows:
        output.append(
            f"| {repo} | {workflow} | {os_name} | {usage} | "
            f"{len(row['run_ids'])} | {row['jobs']} | {row['failures']} | "
            f"{row['minutes']} |"
        )

    metered = Counter()
    for record in records:
        if record["usage_class"] == "metered-private":
            metered[record["os"]] += record["rounded_minutes"]
    output.extend(
        [
            "",
            "## Metered private-repository minutes by OS",
            "",
            "| OS | Rounded job-minutes |",
            "|---|---:|",
        ]
    )
    for os_name, minutes in metered.most_common():
        output.append(f"| {os_name} | {minutes} |")
    if not metered:
        output.append("| none | 0 |")

    output.extend(
        [
            "",
            "## Automation-triggered workflow runs",
            "",
            "| Repository | Renovate | Dependabot | Other | Reruns |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for repo in sorted(runs_by_repo):
        kinds = Counter(automation_kind(run) for run in runs_by_repo[repo])
        reruns = sum(int(run.get("run_attempt", 1)) > 1 for run in runs_by_repo[repo])
        output.append(
            f"| {repo} | {kinds['renovate']} | {kinds['dependabot']} | "
            f"{kinds['other']} | {reruns} |"
        )

    output.extend(
        [
            "",
            "> This is a run-history estimate. Use GitHub's billing report for exact",
            "> allowance consumption, runner multipliers, discounts, and blocked jobs.",
        ]
    )
    return "\n".join(output)


def json_report(
    owner: str,
    start: dt.date,
    end: dt.date,
    repositories: list[Repository],
    runs_by_repo: dict[str, list[dict[str, Any]]],
    records: list[dict[str, Any]],
) -> str:
    payload = {
        "owner": owner,
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "repositories": [repo.full_name for repo in repositories],
        "workflow_run_counts": {
            repo: len(runs) for repo, runs in sorted(runs_by_repo.items())
        },
        "jobs": records,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    today = dt.datetime.now(dt.timezone.utc).date()
    parser = argparse.ArgumentParser(
        description="Reconstruct job-rounded GitHub Actions usage with gh."
    )
    parser.add_argument("--owner", help="Repository owner; defaults to the gh user")
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="Repository name or OWNER/NAME; repeat to audit multiple repositories",
    )
    parser.add_argument(
        "--from-date",
        type=parse_date,
        default=today.replace(day=1),
        help="Inclusive UTC date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--to-date",
        type=parse_date,
        default=today,
        help="Inclusive UTC date in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--include-public",
        action="store_true",
        help="Include public repositories, whose standard hosted usage is free",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    if shutil.which("gh") is None:
        parser.error("gh is required and must be authenticated")
    if args.from_date > args.to_date:
        parser.error("--from-date must not be later than --to-date")
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    owner = args.owner or current_owner()
    repositories = resolve_repositories(owner, args.repo, args.include_public)
    date_range = f"{args.from_date.isoformat()}..{args.to_date.isoformat()}"

    runs_by_repo: dict[str, list[dict[str, Any]]] = {}
    for repo in repositories:
        runs_by_repo[repo.full_name] = list_runs(repo, date_range)

    work = [
        (repo, run)
        for repo in repositories
        for run in runs_by_repo[repo.full_name]
    ]
    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(collect_run, repo, run) for repo, run in work]
        for future in concurrent.futures.as_completed(futures):
            run_records, _ = future.result()
            records.extend(run_records)

    records.sort(
        key=lambda record: (
            record["repo"],
            record["workflow"],
            record["run_id"],
            record["job"],
        )
    )
    if args.format == "json":
        print(
            json_report(
                owner,
                args.from_date,
                args.to_date,
                repositories,
                runs_by_repo,
                records,
            )
        )
    else:
        print(
            markdown_report(
                owner,
                args.from_date,
                args.to_date,
                repositories,
                runs_by_repo,
                records,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
