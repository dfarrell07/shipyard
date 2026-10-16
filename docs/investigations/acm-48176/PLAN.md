# Plan for ACM-48176

## The Lighthouse change

`NewNginxDeployment` and `NewNetShootDeploymentInNS` in `test/e2e/framework/deployments.go` get their pod `runAsUser` from a new
private helper, `nettestRunAsUser`, as the [README](README.md#fix) describes. It asks client-go for the target cluster's API
groups inside `framework.AwaitUntil`, so transient errors retry within the operation timeout and anything else fails the test.

skitt's review of [#2324](https://github.com/submariner-io/lighthouse/pull/2324) rejected the earlier raw `/apis` request and
said the comment applies to every branch, so all nine use client-go's discovery call:

| Branches | Discovery call |
| --- | --- |
| `devel` (client-go v0.37) | `Discovery().ServerGroupsWithContext`, passed straight to `AwaitUntil` |
| `release-0.25` | `ServerGroups()` in a `func(context.Context)` wrapper; its builders take a `ctx` |
| `release-0.22`–`release-0.24` | `Discovery().ServerGroups`, passed straight to the generic `AwaitUntil` |
| `release-0.18`–`release-0.21` | `ServerGroups()` in the pre-generics `AwaitUntil`, with a type assertion |

`ServerGroups()` ignores contexts, as skitt noted; on 0.18–0.24 the neighbouring Deployment create already uses
`context.TODO()`. Each branch has one signed commit, "Let OpenShift assign nettest helper pod UIDs", pushed to
[`dfarrell07/lighthouse`](https://github.com/dfarrell07/lighthouse/branches) as `nettest-scc-uid-<branch>`. The pre-review heads
are kept locally as `backup/codex-scc-before-review/*`.

On `devel` and `release-0.23`–`0.25`, the commit adds a three-spec Ginkgo suite in `test/unit/framework`. It checks both
builders' UID on an OpenShift and a plain fake cluster, and that a discovery failure stops the test before any Deployment is
created. The `release-0.18`–`0.22` unit runner skips every test directory whose test files mention `e2e`, and the suite must
import `test/e2e/framework`, so those commits change only `deployments.go`; fixing that runner is separate work.

## Verification

All nine build, lint clean, and pass the suite with `-race` and randomized order; 0.18–0.22 get it through a `go test`
overlay. Every spec fails on each branch's original code, and both UID-selection mutants are caught everywhere. Each code
shape returned a nil UID against a live OpenShift API server ([log](evidence/branch-verification.log)).

## Landing

skitt asked for `devel` approval before backports. All nine stay drafts: mark `#2324` ready, get it approved and merged, then
mark the backports ready. If review changes the code, apply the change to each variant.

The 0.18–0.21 branches carry the bug, but no Subctl built from them includes it: their Subctl branches pin pre-hardening
Lighthouse. Fixing them keeps the next tag clean; they are lower priority.

## Delivering the fix

Deployed Submariner is unaffected ([impact](README.md#impact)). The current plan is that each branch's next regular release
picks up the fix; release owners decide any exception. Merging alone ships nothing: delivery needs a Lighthouse tag with the
fix, a Subctl bump to that tag, and a fresh Subctl build.

- Downstream 0.23.4 (ACM-44527) is already built and ships with the known-issue note. Merging Lighthouse `release-0.23`
  triggers the `lighthouse-agent-0-23` and `lighthouse-coredns-0-23` push pipelines, so keep the approved snapshot and bundle
  digests rather than the latest snapshot.
- For downstream 0.22.2 (ACM-45070) and 0.24.2 (ACM-47692), check the Lighthouse version in the actual Subctl build before
  claiming the fix is included.

**Optional QE check.** To get a service-discovery result without a rebuild, on disposable test clusters only, run
`oc adm policy add-scc-to-group nonroot-v2 system:serviceaccounts` on both clusters, rerun `subctl verify --only
service-discovery`, then undo it with `oc adm policy remove-scc-from-group nonroot-v2 system:serviceaccounts`. The admission
check admits both original Deployments under that grant ([log](evidence/admission-check.log)). It is not a customer workaround
and does not validate a fixed Subctl.

## Follow-ups

- **Known issue (ACM-48194):** add a note to the GitHub release notes of upstream Subctl v0.22.2, v0.23.2, v0.23.4, v0.24.2,
  v0.25.0-rc1, and v0.26.0-m0, and to any downstream release that ships without the fix: "`subctl verify --only
  service-discovery` fails on OpenShift; deployed Submariner is unaffected." Name the fixing Subctl release once one exists.
- **Shipyard #2618:** it still sets UID 10000 in `devel`'s CI YAMLs. It is unrelated to `subctl verify`; merge it separately.

## Pull requests

All drafts, each from `dfarrell07:nettest-scc-uid-<branch>`; their bodies follow [pr-body.txt](evidence/pr-body.txt):

| Branch | PR | Branch | PR |
| --- | --- | --- | --- |
| `devel` | [#2324](https://github.com/submariner-io/lighthouse/pull/2324) | `release-0.21` | [#2329](https://github.com/submariner-io/lighthouse/pull/2329) |
| `release-0.25` | [#2325](https://github.com/submariner-io/lighthouse/pull/2325) | `release-0.20` | [#2330](https://github.com/submariner-io/lighthouse/pull/2330) |
| `release-0.24` | [#2326](https://github.com/submariner-io/lighthouse/pull/2326) | `release-0.19` | [#2331](https://github.com/submariner-io/lighthouse/pull/2331) |
| `release-0.23` | [#2327](https://github.com/submariner-io/lighthouse/pull/2327) | `release-0.18` | [#2332](https://github.com/submariner-io/lighthouse/pull/2332) |
| `release-0.22` | [#2328](https://github.com/submariner-io/lighthouse/pull/2328) | | |
