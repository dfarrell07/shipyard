# Plan for ACM-48176

## The Lighthouse change

In `test/e2e/framework/deployments.go`, `NewNginxDeployment` and `NewNetShootDeploymentInNS` call a new private helper,
`nettestRunAsUser`, before building the Deployment, and use its result as the pod's `runAsUser`. `NewNetShootDeployment`
delegates to `NewNetShootDeploymentInNS`. The helper:

1. GETs `/apis` with `Accept: application/json` through the target cluster's discovery REST client, inside
   `framework.AwaitUntil`. Like the rest of the file, it retries transient errors within the operation timeout.
2. Requires a `*metav1.APIGroupList`. Any other error fails the test before a Deployment is created.
3. Returns `nil` if a group named `security.openshift.io` is listed, otherwise 10000.

It uses the raw request rather than `Discovery().ServerGroups()` because only the raw request honors a context deadline. The
lookup runs per call and per target cluster, with no cache. Discovery only identifies the platform; the OpenShift path assumes
the default restricted-v2 grant and namespace UID allocation.

Each branch has one commit, "Let OpenShift assign nettest helper pod UIDs" ([patches](evidence/lighthouse-branches)). The code
follows each branch's framework API:

| Branches | Variant |
| --- | --- |
| `devel`, `release-0.25` | Builders take a `ctx`; `AwaitUntil` bounds each request; returns `new(int64(10000))` |
| `release-0.22`–`release-0.24` | No builder `ctx`; the helper bounds its own; generic `AwaitUntil`; returns `ptr.To(int64(10000))` |
| `release-0.19`–`release-0.21` | As above, with the pre-generics `AwaitUntil` and a type assertion |
| `release-0.18` | As above, computing the timeout itself; Shipyard v0.18.5 lacks `OperationTimeoutToDuration()` |

The commit adds a Ginkgo suite in `test/unit/framework`, because the shared unit runner skips `test/e2e`. An HTTP fixture serves
discovery, records created Deployments, and reports a Running pod so the builder's wait completes. For both builders it checks:

- per-cluster selection: UID unset on the OpenShift cluster, 10000 on the other, one lookup each, hardening unchanged;
- a retried transient 503;
- failure without a Deployment on HTTP 403 and on a non-`APIGroupList` response;
- failure within the timeout when discovery stalls.

## Verification

All nine branches build, and the suite passes 10/10 with `-race` and randomized order. Every spec fails against the branch's
original code ([log](evidence/branch-verification.log)). Lint is clean on 0.19–0.25, ignoring pre-existing findings in untouched
files. 0.18 uses a v1 lint config, so its branch CI is the lint check. On `devel` the suite also rejects five plausible wrong
implementations:

- always querying cluster A;
- falling back to 10000 on errors;
- an unbounded request;
- no retry;
- dropping `runAsNonRoot` (from the first version of the suite).

Against a real kube-apiserver, as an unprivileged user, the helper returned 10000 on a plain server and nil once a
`security.openshift.io` group was served (here via a CRD). It failed with `context deadline exceeded` under a zero timeout
([devel](evidence/real-apiserver-devel.log), [0.23](evidence/real-apiserver-0.23.log)). On `release-0.23`, `runAsUser` is the
only field that changes, so the OpenShift output is exactly the [corrected manifest](evidence/repro/corrected) that the
admission check admits.

## Landing

The commits are per-branch ports, not cherry-picks of a merged `devel` commit, so open all nine PRs together and link them.
The original hardening went the same way (#2228–#2235). Merge `release-0.23`, `release-0.22`, and `release-0.24` first: their
downstream releases are waiting on this fix. If review changes the code, apply the change to each variant and re-export the patches.

On `release-0.18`–`0.22`, the shared unit runner also skips any test directory whose test files mention `e2e`. The new suite
imports a `test/e2e` package, so on those branches `make unit` does not run it, and their PRs include an explicit test run
instead. If reviewers would rather not carry a suite that CI cannot run on those branches, drop the test files from those five
PRs; the production change is identical either way.

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

QE should take Subctl from the rebuilt stage image by digest, and `go version -m` on it should show the fixed Lighthouse version.

For local builds, use a fresh checkout. Subctl's Makefile ignores `go.mod`-only changes and appends to
`dist/subctl-checksums.txt`. Konflux builds with `go build`, so it is not affected.

## Follow-ups

- **Known issue:** add a note to the GitHub release notes of upstream Subctl v0.22.2, v0.23.2, v0.23.4, v0.24.2, v0.25.0-rc1,
  and v0.26.0-m0. The note: "`subctl verify --only service-discovery` fails on OpenShift. Upgrade Subctl; deployed Submariner is
  unaffected."
- **Shipyard #2618:** it still sets UID 10000 in `devel`'s CI YAMLs. It is unrelated to `subctl verify`; merge it separately.
- **Custom SCCs:** where an administrator grants anyuid or a custom higher-priority SCC to every user, an unset `runAsUser` leaves
  the image's user in effect. Root-default images (0.23.2 and earlier) then fail `runAsNonRoot`. This is out of scope.

## Publishing commands (developer)

The branches are already pushed to `dfarrell_lh`; the loop's push only matters if a commit changes. The loop uses the
[shared PR body](evidence/lighthouse-branches/pr-body.txt), appends the explicit test run on `release-0.18`–`0.22`, and stops at
the first failure.

~~~bash
ev=~/go/src/submariner-io/shipyard/docs/investigations/acm-48176/evidence/lighthouse-branches
session=https://claude.ai/code/session_01YTdbc3vVeY8XMVvhVmqgWD
for b in devel release-0.25 release-0.24 release-0.23 release-0.22 release-0.21 release-0.20 release-0.19 release-0.18; do
  cd ~/go/src/submariner-io/.worktrees/acm-48176-exec/$b || break
  body=$(mktemp)
  grep -v "^$session" "$ev/pr-body.txt" > "$body"
  case $b in
  release-0.1[89] | release-0.2[012])
    out=$(GOWORK=off go test -v -race -count=1 ./test/unit/framework/ --ginkgo.no-color 2>&1) || { echo "$b: tests failed"; break; }
    printf '\nOn this branch the shared unit runner skips test directories whose `_test.go` files mention `e2e`,\n'
    printf 'so `make unit` does not run `test/unit/framework`. Explicit run:\n\n```text\n%s\n```\n' "$(grep -E '^Ran |^SUCCESS|^ok' <<<"$out")"
    ;;
  esac >> "$body"
  printf '\n%s\n' "$session" >> "$body"
  git push dfarrell_lh "nettest-scc-uid-$b" &&
    gh pr create --repo submariner-io/lighthouse --base "$b" --head "dfarrell07:nettest-scc-uid-$b" \
      --title "Let OpenShift assign nettest helper pod UIDs" --body-file "$body" --assignee "@me" || break
done
~~~

After the PRs merge, remove each worktree with
`git -C ~/go/src/submariner-io/lighthouse worktree remove ~/go/src/submariner-io/.worktrees/acm-48176-exec/<branch>`.
