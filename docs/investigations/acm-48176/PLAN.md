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

The commits are per-branch ports, not cherry-picks of a merged `devel` commit, so open all nine PRs together and link them.
The original hardening went the same way (#2228–#2235). Merge `release-0.23`, `release-0.22`, and `release-0.24` first: their
downstream releases are waiting on this fix. If review changes the code, apply the change to each variant.

The `release-0.18`–`0.22` commits change only `deployments.go`. Their shared unit runner skips any test directory whose test files
mention `e2e`, and the suite imports a `test/e2e` package, so CI there could never run it. Their PR bodies point to the `devel`
PR for the regression tests.

The 0.18–0.21 branches carry the bug, but no Subctl built from them includes it: their Subctl branches pin pre-hardening
Lighthouse. Fixing them now keeps the next tag clean; they are lower priority.

## Delivering Subctl

Only Subctl's code changes, and Subctl is not in the operator bundle. Recommended path: **ship 0.23.5**.

- Upstream v0.23.4 is already published with the bug, and a respin cannot replace it. The normal release gives Subctl
  "Update Submariner dependencies to v0.23.5".
- Downstream, retarget ACM-44527 to 0.23.5, as was done for 0.23.2 → 0.23.4.
- A 0.23.4 respin is not a Subctl-only rebuild. Merging Lighthouse `release-0.23` triggers the unfiltered `lighthouse-agent-0-23`
  and `lighthouse-coredns-0-23` push pipelines, so the latest snapshot no longer matches the staged bundle. A respin would need
  either a hand-built snapshot (the staged digests plus the new Subctl) or a bundle SHA update with an FBC re-stage.

Downstream 0.22.2 (ACM-45070, in progress) and 0.24.2 (ACM-47692) pin affected Lighthouse tags. Hold them until Subctl
`release-0.22` and `release-0.24` pick up the fix, and tell their release owners. No downstream production release contains
the bug.

QE should take Subctl from the rebuilt stage image by digest; `go version -m` on it should show the fixed Lighthouse version.

## Follow-ups

- **Known issue:** add a note to the GitHub release notes of upstream Subctl v0.22.2, v0.23.2, v0.23.4, v0.24.2, v0.25.0-rc1,
  and v0.26.0-m0. The note: "`subctl verify --only service-discovery` fails on OpenShift. Upgrade Subctl; deployed Submariner is
  unaffected."
- **Shipyard #2618:** it still sets UID 10000 in `devel`'s CI YAMLs. It is unrelated to `subctl verify`; merge it separately.

## Publishing commands (developer)

The branches are already pushed to `dfarrell_lh`; the loop's push only matters if a commit changes. The loop uses the
[shared PR body](evidence/pr-body.txt), replaces its test line on `release-0.18`–`0.22` with a pointer to the `devel` PR, and
stops at the first failure.

~~~bash
ev=~/go/src/submariner-io/shipyard/docs/investigations/acm-48176/evidence
session=https://claude.ai/code/session_01YTdbc3vVeY8XMVvhVmqgWD
for b in devel release-0.25 release-0.24 release-0.23 release-0.22 release-0.21 release-0.20 release-0.19 release-0.18; do
  cd ~/go/src/submariner-io/.worktrees/acm-48176-exec/$b || break
  body=$(mktemp)
  cp "$ev/pr-body.txt" "$body"
  case $b in
  release-0.1[89] | release-0.2[012])
    sed -i 's|^Tests are in .*|This branch has the code change only; its unit runner cannot run the tests, which are in the `devel` PR.|' "$body"
    ;;
  esac
  printf '\n%s\n' "$session" >> "$body"
  git push dfarrell_lh "nettest-scc-uid-$b" &&
    gh pr create --repo submariner-io/lighthouse --base "$b" --head "dfarrell07:nettest-scc-uid-$b" \
      --title "Let OpenShift assign nettest helper pod UIDs" --body-file "$body" --assignee "@me" || break
done
~~~
