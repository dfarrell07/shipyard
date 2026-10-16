# Plan for ACM-48176

## The Lighthouse change

`NewNginxDeployment` and `NewNetShootDeploymentInNS` in `test/e2e/framework/deployments.go` get their pod `runAsUser` from a new
private helper, `nettestRunAsUser`, as the [README](README.md#fix) describes. It GETs `/apis` inside `framework.AwaitUntil`; it
uses the raw request because `Discovery().ServerGroups()` ignores context deadlines. Each branch has one commit, "Let OpenShift
assign nettest helper pod UIDs", pushed to [`dfarrell07/lighthouse`](https://github.com/dfarrell07/lighthouse/branches) as
`nettest-scc-uid-<branch>` and adapted to that branch's framework API:

| Branches | Variant |
| --- | --- |
| `devel`, `release-0.25` | Builders take a `ctx`; `AwaitUntil` bounds each request; returns `new(int64(10000))` |
| `release-0.22`–`release-0.24` | No builder `ctx`; the helper bounds its own; generic `AwaitUntil`; returns `ptr.To(int64(10000))` |
| `release-0.19`–`release-0.21` | As above, with the pre-generics `AwaitUntil` and a type assertion |
| `release-0.18` | As above, computing the timeout itself; Shipyard v0.18.5 lacks `OperationTimeoutToDuration()` |

On `devel` and `release-0.23`–`0.25`, the commit adds a three-spec Ginkgo suite in `test/unit/framework`, outside the `test/e2e`
tree that the unit runner skips. It checks both builders' UID on an OpenShift and a plain fake cluster, and that a discovery
failure stops the test before any Deployment is created.

## Verification

All nine branches build, and lint is clean apart from pre-existing findings in untouched files (0.18's v1 lint config is left to
its CI). The suite passes with `-race` and randomized order, and every spec fails against the branch's original code. On `devel`
it also rejects plausible wrong implementations: querying the wrong cluster, falling back to 10000 on errors, or a builder that
ignores the helper ([log](evidence/branch-verification.log)).

Against a real kube-apiserver, as an unprivileged user, the helper returned 10000 on a plain server and nil once a
`security.openshift.io` group was served (here via a CRD). It failed with `context deadline exceeded` under a zero timeout
([devel](evidence/real-apiserver-devel.log), [0.23](evidence/real-apiserver-0.23.log)). On `release-0.23`, `runAsUser` is the
only field that changes, so the OpenShift output is exactly the [corrected manifest](evidence/repro/corrected) that the
admission check admits.

## Landing

The commits are per-branch ports, not cherry-picks of a merged `devel` commit, so all nine PRs are open together and linked.
The original hardening went the same way (#2228–#2235). If review changes the code, apply the change to each variant.

The `release-0.18`–`0.22` commits change only `deployments.go`. Their shared unit runner skips any test directory whose test files
mention `e2e`, and the suite imports a `test/e2e` package, so CI there could never run it. Their PR bodies point to the `devel`
PR for the regression tests.

The 0.18–0.21 branches carry the bug, but no Subctl built from them includes it: their Subctl branches pin pre-hardening
Lighthouse. Fixing them now keeps the next tag clean; they are lower priority.

## Delivering the fix

Deployed Submariner is unaffected ([impact](README.md#impact)), so no release is held or respun for this. Each branch's next
regular release picks up the fix.

- Downstream 0.23.4 (ACM-44527) ships as built, with the known-issue note. A respin would not be Subctl-only anyway: merging
  Lighthouse `release-0.23` triggers the unfiltered `lighthouse-agent-0-23` and `lighthouse-coredns-0-23` push pipelines, so the
  latest snapshot would no longer match the staged bundle.
- Downstream 0.22.2 (ACM-45070) and 0.24.2 (ACM-47692) take the fix if it merges before their Subctl build, and otherwise ship
  with the note.

**Optional QE check.** To get a service-discovery result for 0.23.4 without a rebuild, on disposable test clusters only, run
`oc adm policy add-scc-to-group nonroot-v2 system:serviceaccounts` on both clusters, rerun `subctl verify --only
service-discovery`, then undo it with `oc adm policy remove-scc-from-group nonroot-v2 system:serviceaccounts`. The admission
check admits both original Deployments under that grant ([log](evidence/admission-check.log)). It is a test-cluster check, not a
customer workaround.

## Follow-ups

- **Known issue:** add a note to the GitHub release notes of upstream Subctl v0.22.2, v0.23.2, v0.23.4, v0.24.2, v0.25.0-rc1,
  and v0.26.0-m0, and to any downstream release that ships without the fix. The note: "`subctl verify --only
  service-discovery` fails on OpenShift; deployed Submariner is unaffected. A later Subctl release fixes it."
- **Shipyard #2618:** it still sets UID 10000 in `devel`'s CI YAMLs. It is unrelated to `subctl verify`; merge it separately.

## Pull requests

All drafts, each from `dfarrell07:nettest-scc-uid-<branch>`:

| Branch | PR | Branch | PR |
| --- | --- | --- | --- |
| `devel` | [#2324](https://github.com/submariner-io/lighthouse/pull/2324) | `release-0.21` | [#2329](https://github.com/submariner-io/lighthouse/pull/2329) |
| `release-0.25` | [#2325](https://github.com/submariner-io/lighthouse/pull/2325) | `release-0.20` | [#2330](https://github.com/submariner-io/lighthouse/pull/2330) |
| `release-0.24` | [#2326](https://github.com/submariner-io/lighthouse/pull/2326) | `release-0.19` | [#2331](https://github.com/submariner-io/lighthouse/pull/2331) |
| `release-0.23` | [#2327](https://github.com/submariner-io/lighthouse/pull/2327) | `release-0.18` | [#2332](https://github.com/submariner-io/lighthouse/pull/2332) |
| `release-0.22` | [#2328](https://github.com/submariner-io/lighthouse/pull/2328) | | |

Their bodies start from [pr-body.txt](evidence/pr-body.txt). The 0.18–0.22 bodies point to #2324 for the tests, and every
body lists the others.
