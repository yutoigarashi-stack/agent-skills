# GitHub Actions optimization patterns

Read this reference after measuring usage and before proposing workflow
changes. Savings estimates from different patterns may overlap; do not add them
without accounting for overlap.

## Contents

- Measurement rules
- Path-scope independent components
- Preserve useful default-branch runs
- Cancel stale executions
- Consolidate short jobs
- Move work to a cheaper runner
- Cache dependencies deliberately
- Reduce dependency-bot churn
- Validation checklist

## Measurement rules

- Private hosted-runner jobs consume the repository owner's allowance.
- Public repositories on standard hosted runners, self-hosted runners, and
  Dependabot's own update jobs are free. Normal CI triggered by a dependency
  update PR is not free.
- GitHub rounds billable job execution up to the next whole minute. Three
  parallel 20-second jobs therefore consume approximately three minutes, not
  one.
- Failed time and reruns consume usage.
- Check current details before quoting rates:
  - https://docs.github.com/en/billing/concepts/product-billing/github-actions
  - https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time

## Path-scope independent components

Use separate workflows with event-level `paths` when a monorepo has independent
components. This avoids paying for a change-detector job and lets GitHub skip
the workflow entirely.

Include:

- the component directory;
- shared lockfiles and configuration that affect it;
- the workflow file itself;
- cross-component files that genuinely require all validations.

Do not path-filter required checks without checking branch protection. GitHub
may leave a skipped required workflow pending. Preserve a stable aggregate
check when required checks depend on its name.

## Preserve useful default-branch runs

Default-branch cache warming is intentional when later PRs restore that cache.
PR-created caches are scoped to the PR merge ref and are not reusable by sibling
PRs:

https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching

Keep `push: main` when it:

- protects unreviewed direct pushes;
- warms dependency or build caches;
- publishes artifacts;
- verifies the merged commit;
- feeds deployment or release workflows.

Apply the same component paths to the default-branch trigger so only changed
components validate and refresh their caches.

## Cancel stale executions

Use workflow-specific concurrency so a newer commit to the same PR or branch
cancels its obsolete run:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
```

Measure historical overlaps. This is protective but yields no retrospective
savings when runs never overlapped.

## Consolidate short jobs

Combine short jobs when each one repeats checkout, runtime setup, dependency
installation, and sub-minute validation. Run lint, type checking, tests, and
build sequentially after one setup.

Trade-offs:

- lower setup time and fewer rounded job-minutes;
- less parallel feedback;
- later checks do not run after an early failure;
- status-check names change.

Keep jobs separate when they require different permissions, secrets,
environments, runner images, or independent mandatory status checks.

## Move work to a cheaper runner

Move platform-independent linting and static analysis from macOS or Windows to
Linux. Use an official, version-pinned binary or container and verify that the
rules and output match.

Do not move platform builds or simulator tests when Linux cannot reproduce
them. A self-hosted macOS runner can preserve fidelity but introduces machine
maintenance and a high-impact code-execution boundary.

## Cache dependencies deliberately

Use setup actions' native cache support where possible. Confirm the dependency
path in a monorepo:

```yaml
- uses: actions/setup-node@v6
  with:
    node-version: "22"
    cache: pnpm
    cache-dependency-path: pnpm-lock.yaml
```

Caching a 20-second job may improve latency without reducing quota because the
job still rounds to one minute. Measure before claiming minute savings.

## Reduce dependency-bot churn

Schedule routine dependency updates weekly or group compatible updates when
bot PRs repeatedly trigger ordinary CI. For Renovate, a strict weekly window
can use:

```json
{
  "timezone": "Asia/Tokyo",
  "schedule": ["* 0-3 * * 1"],
  "updateNotScheduled": false
}
```

Renovate vulnerability-alert PRs skip the normal schedule:

https://docs.renovatebot.com/configuration-options/#vulnerabilityalerts

Grouping unrelated dependencies reduces runs but makes failures harder to
isolate. Prefer scheduling before broad grouping.

## Validation checklist

- Validate YAML with actionlint when available.
- Validate Renovate with `renovate-config-validator`.
- Validate JSON with `jq`.
- Run every command retained in a consolidated job.
- Verify workflow paths against representative historical changes.
- Confirm default branch, PR head, file list, mergeability, and check results.
- Record when quota exhaustion prevents hosted CI from starting.
