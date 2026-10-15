# Plan for ACM-48176

## The Lighthouse change

In `test/e2e/framework/deployments.go`, `NewNginxDeployment` and `NewNetShootDeploymentInNS` call a new private helper,
`nettestRunAsUser`, before building the Deployment, and use its result as the pod's `runAsUser`. `NewNetShootDeployment`
delegates to `NewNetShootDeploymentInNS`. The helper:

1. Bounds the request with `framework.TestContext.OperationTimeoutToDuration()`.
2. GETs `/apis` with `Accept: application/json` through the target cluster's discovery REST client, and requires a
   `*metav1.APIGroupList`. Any error stops the test through Gomega before a Deployment is created.
3. Returns `nil` if a group named `security.openshift.io` is listed, otherwise 10000.

The lookup runs per call and per target cluster, with no cache. Discovery only identifies the platform; the OpenShift path
assumes the usual restricted-v2 grant and namespace UID allocation. Legacy `/apis` lists every registered APIService group
whether or not it is available, so a degraded openshift-apiserver does not change the classification.

Each branch has one commit, "Let OpenShift assign nettest helper pod UIDs" ([patches](evidence/lighthouse-branches)). The
production code has three variants:

| Branches | Variant |
| --- | --- |
| `devel`, `release-0.25` | Builders take a `ctx`: `nettestRunAsUser(ctx, cluster)`, returning `new(int64(10000))` |
| `release-0.19`–`release-0.24` | `nettestRunAsUser(cluster)`, returning `ptr.To(int64(10000))` |
| `release-0.18` | As above, but computes the timeout itself; Shipyard v0.18.5 lacks `OperationTimeoutToDuration()` |

The commit adds a Ginkgo suite in `test/unit/framework`, because the shared unit runner skips `test/e2e`. An HTTP fixture serves
discovery, records created Deployments, and reports a Running pod so the builder's wait completes. For both builders it checks:

- per-cluster selection: UID unset on the OpenShift cluster, 10000 on the other, one lookup each, hardening unchanged;
- failure without a Deployment on HTTP 403 and on a non-`APIGroupList` response;
- failure within the timeout when discovery stalls.

## Verification

Run locally with `GOWORK=off`, Go 1.26.8, and golangci-lint 2.11.3 in worktrees under
`~/go/src/submariner-io/.worktrees/acm-48176-exec/<branch>` (local branches `nettest-scc-uid-<branch>`):

| Branch | Build | Lint | Suite with `-race` | Fails on original code |
| --- | --- | --- | --- | --- |
| `devel` | Pass | Clean | 8/8, five randomized runs | Yes |
| `release-0.25` | Pass | Clean | 8/8 | Not run; same code as `devel` |
| `release-0.24` | Pass | Clean | 8/8 | Yes |
| `release-0.23` | Pass | Pre-existing finding only | 8/8 | Yes |
| `release-0.22` | Pass | Pre-existing findings only | 8/8 | Yes |
| `release-0.19`–`release-0.21` | Pass | Not run | 8/8 | Not recorded |
| `release-0.18` | Pass | Not run (v1 lint config) | 8/8 | Yes |

The pre-existing findings are in files the commit does not touch. Lint on 0.18–0.21 was skipped for local disk space and lint-version
reasons; branch CI covers it. On `devel` the suite also catches four plausible wrong implementations:

- always querying cluster A;
- falling back to 10000 on errors;
- unbounded discovery;
- dropping `runAsNonRoot`.

A run against a real kube-apiserver, as an unprivileged user, returned 10000 on a plain server and nil once a
`security.openshift.io` group was served, and failed before any Deployment with a zero timeout
([devel](evidence/real-apiserver-devel.log), [0.23](evidence/real-apiserver-0.23.log)). Since `runAsUser` is the only field that
changes, the OpenShift output is exactly the [corrected manifest](evidence/repro/corrected) that the admission check admits.

## Landing

The commits are per-branch ports, not cherry-picks of a merged `devel` commit, so open all nine PRs together and link them. The
original hardening went the same way (#2228–#2235). Merge `release-0.23` first; it blocks QE. If review changes the code, apply
the change to each variant and re-export the patches.

On `release-0.18`–`0.22`, the shared unit runner also skips any test directory whose test files mention `e2e`. The new suite
imports a `test/e2e` package, so on those branches `make unit` does not run it. Their PRs include an explicit test run instead;
the publishing loop below adds it.

## Delivering Subctl

Only the Subctl component needs rebuilding. Its image is not in the operator bundle, so the bundle, catalogs, and operands are
unaffected. 0.23.4 is staged, not released, so the release owner chooses:

- **Respin 0.23.4:** after the `release-0.23` merge, in a fresh Subctl `release-0.23` checkout, run
  `GOWORK=off go get github.com/submariner-io/lighthouse@<merged-sha> && GOWORK=off go mod tidy`. Only the Lighthouse line
  (a `v0.23.5-0.<timestamp>-<sha12>` pseudo-version) and `go.sum` should change, because Lighthouse's `go.mod` is unchanged
  since v0.23.4. Konflux then rebuilds `subctl-0-23`; re-release only that component.
- **Ship 0.23.5:** the normal release; Subctl gets "Update Submariner dependencies to v0.23.5".

Downstream Subctl reports `release-0.23` as its version, so check the executable QE will run, not its version text.
`go version -m` must show the fixed Lighthouse version and no unexpected `replace`. For an image, also record its digest.
A reused upstream checkout can keep a stale binary and checksum: Subctl's Makefile does not rebuild on module changes, and it
appends to `dist/subctl-checksums.txt`. Build from a fresh checkout.

## Follow-ups

- Known-issue note: `subctl verify --only service-discovery` fails on OpenShift with Subctl v0.22.2, v0.23.2, v0.23.4, and
  v0.24.2. Upgrading Subctl fixes it; deployed Submariner is unaffected.
- Shipyard #2618 still sets UID 10000 in `devel`'s CI YAMLs. It is unrelated to `subctl verify`; merge it separately.

## Publishing commands

Review each worktree's commit first. The loop uses the [shared PR body](evidence/lighthouse-branches/pr-body.txt). For
`release-0.18`–`0.22` it appends that branch's explicit test run. It stops at the first failure.

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
