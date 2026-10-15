# Execution runbook for ACM-48176

Everything below is prepared locally and nothing has been pushed or opened. Commands that publish anything are listed for a person
to run. The [implementation plan](IMPLEMENTATION.md) explains the design; this page tracks the concrete commits and their order.

## Prepared Lighthouse commits

Each branch has one commit, "Let OpenShift assign nettest helper pod UIDs", in a worktree under
`~/go/src/submariner-io/.worktrees/acm-48176-exec/<branch>` on local branch `nettest-scc-uid-<branch>`. The exported
[patches](evidence/lighthouse-branches) are the review copies. Every commit changes `test/e2e/framework/deployments.go` and adds
`test/unit/framework/{framework_suite_test.go,deployments_test.go}`. The production change has three variants:

| Branches | Variant |
| --- | --- |
| `devel`, `release-0.25` | `nettestRunAsUser(ctx, cluster)`, timeout derived from the builder's `ctx`, `new(int64(10000))` |
| `release-0.19`–`release-0.24` | `nettestRunAsUser(cluster)`, `OperationTimeoutToDuration()`; the reviewed candidate, new comment |
| `release-0.18` | As above, with `time.Duration(OperationTimeout) * time.Second`, because Shipyard v0.18.5 lacks the helper |

Verification with `GOWORK=off`, local Go 1.26.8, and local golangci-lint 2.11.3:

| Branch | Base | Build | Lint | Ginkgo `-race` | Original code fails the tests | Real kube-apiserver |
| --- | --- | --- | --- | --- | --- | --- |
| `devel` | `db375046` | Pass | 0 issues | 8/8, five randomized runs | Yes, plus four more mutants | [Pass](evidence/real-apiserver-devel.log) |
| `release-0.25` | `8666ce11` | Pass | 0 issues | 8/8 | Not run; tree identical to `devel` | — |
| `release-0.24` | `228b141c` | Pass | 0 issues | 8/8 | Yes | — |
| `release-0.23` | `3a3dc0eb` | Pass | 1 pre-existing (`service_discovery.go`) | 8/8 | Yes | [Pass](evidence/real-apiserver-0.23.log) |
| `release-0.22` | `2cd528f6` | Pass | 2 pre-existing (`framework.go`) | 8/8 | Yes | — |
| `release-0.21` | `ae581412` | Via `go test` | Not run (disk) | 8/8 | Not run | — |
| `release-0.20` | `0337133a` | Via `go test` | Not run (disk) | 8/8 | Output lost (disk) | — |
| `release-0.19` | `f1198a32` | Via `go test` | Not run (disk) | 8/8 | Output lost (disk) | — |
| `release-0.18` | `25c76b23` | `go vet` pass | Not run: v1 config | 8/8 | Yes | — |

The mutants on `devel` were: always query cluster A, fall back to 10000 on discovery errors, unbounded discovery, and dropped
`runAsNonRoot`. All were caught. The real kube-apiserver check ran as an unprivileged token user with default RBAC. It returned
UID 10000 on a plain server and nil once a `security.openshift.io` group was served (here via a CRD), and failed before any
Deployment with a zero budget ([source](evidence/real-apiserver-check.go.txt), [server setup](evidence/real-apiserver-run.sh.txt)).
Pre-existing lint findings are in files the commits do not touch; the branch CI linter is authoritative, especially on `0.18`.

On `release-0.18`–`0.22`, the shared unit runner skips `test/unit/framework` because the test imports a `test/e2e` path.
Those PRs must include an explicit run, for example:
`GOWORK=off go test -race -count=1 ./test/unit/framework/ --ginkgo.v`.

## Order of operations

1. **QE, now and in parallel:** run [QE step 1](QE-VALIDATION.md#1-reproduce-the-controller-failure-in-scratch-namespaces) on both
   clusters. If the ReplicaSet message is not the UID 10000 range rejection, stop and revisit the diagnosis before merging anything.
2. **Lighthouse PRs, all at once:** these are per-branch ports, not cherry-picks of a merged `devel` commit, so open all nine
   PRs together and link them to each other. The original hardening did the same: #2228–#2235 were opened within 45 minutes,
   and the release branches merged before `devel`. Each PR gets CI on its own branch (unit, lint, kind e2e exercising the UID 10000 path).
   There are three code variants (`devel`/`0.25`, `0.19`–`0.24`, `0.18`). If review changes one, apply the same change to every
   PR and re-export the patches. Merge `release-0.23` first if possible; it blocks QE.
3. **Release decision for 0.23:** the Subctl component is the only artifact to rebuild.
   - Respin 0.23.4: after the `release-0.23` merge, in a fresh Subctl `release-0.23` checkout run
     `GOWORK=off go get github.com/submariner-io/lighthouse@<merged-sha> && GOWORK=off go mod tidy`. Expect a
     `v0.23.5-0.<timestamp>-<sha12>` pseudo-version. Lighthouse's `go.mod` is unchanged since v0.23.4, so only that line and
     `go.sum` should change. Merge, let Konflux build `subctl-0-23`, and re-release only that component.
   - Ship 0.23.5: tag through the normal release process; Subctl gets "Update Submariner dependencies to v0.23.5".
   Either way, inspect the delivered executable as [section 3](IMPLEMENTATION.md#3-pin-and-deliver-a-fresh-subctl-executable) requires.
   Downstream Subctl reports `release-0.23` as its version, so version text cannot distinguish a respin.
4. **QE acceptance:** QE steps 3–5 with the new Subctl, both directions, with no SCC grant in place. Close ACM-48176 and ACM-48194.
5. **Follow-ups:** known-issue note for Subctl v0.22.2, v0.23.2/v0.23.4, v0.24.2; Shipyard #2618 for `devel` YAMLs.

## Publishing commands

Review each worktree's commit first. The loop uses the [shared PR body](evidence/lighthouse-branches/pr-body.txt).
For `release-0.18`–`0.22` it appends that branch's explicit test run. It stops at the first failure.

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

Remove the worktrees after the PRs merge:
`git -C ~/go/src/submariner-io/lighthouse worktree remove ~/go/src/submariner-io/.worktrees/acm-48176-exec/<branch>`.
