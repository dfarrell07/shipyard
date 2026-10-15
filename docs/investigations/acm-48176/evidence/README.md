# Evidence for ACM-48176

| Claim | Files |
| --- | --- |
| The attached QE run fails 14 cases at helper setup; every helper Deployment gets zero pods; every StatefulSet runs | [attachment-analysis.json](attachment-analysis.json), [provenance.json](provenance.json) |
| These are the exact Deployments the v0.23.4 builders create | [repro/original](repro/original), from [export-deployments.go.txt](export-deployments.go.txt) |
| SCC admission rejects the original, admits the corrected version, and a nonroot-v2 grant admits the original | [admission-check.go.txt](admission-check.go.txt), [admission-check.log](admission-check.log) |
| The 0.23.2 nettest image defaults to root; 0.23.3 and later use UID 10000 | [image-users.json](image-users.json) |
| The hardened helpers work under an arbitrary UID with a read-only root and no capabilities | [runtime-check.py](runtime-check.py), [runtime-results.json](runtime-results.json) |
| The helper classifies a real kube-apiserver correctly as an unprivileged user | [real-apiserver-check.go.txt](real-apiserver-check.go.txt), [devel log](real-apiserver-devel.log), [0.23 log](real-apiserver-0.23.log) |
| Every branch builds, passes, and fails on its original code | [branch-verification.log](branch-verification.log) |
| The PR body for every branch | [pr-body.txt](pr-body.txt) |

## Reproducing

- **Deployments:** extract `git archive v0.23.4` of Lighthouse and save the exporter as `cmd/acmexport/main.go`. Then run
  `GOWORK=off go run ./cmd/acmexport <dir>`. The corrected manifests delete only `spec.template.spec.securityContext.runAsUser`.
- **Admission:** check out `openshift/apiserver-library-go` at the pinned commit and copy the check into
  `pkg/securitycontextconstraints/sccadmission/`. Point `ACM_AUDIT_DIR` at a directory with the five pinned SCC policies under
  `scc/` and a copy of `repro/`, then run `go test -mod=vendor -run TestACM48176Admission -v`. Commits and hashes are in
  [provenance.json](provenance.json). The requester is the ReplicaSet controller, and the namespace range is `1001530000/10000`.
- **Runtime:** `python3 runtime-check.py` with rootless Podman and the two pinned images it names.
- **Real kube-apiserver:** start envtest's etcd and kube-apiserver with [real-apiserver-run.sh.txt](real-apiserver-run.sh.txt).
  Write kubeconfigs for an admin token and a plain-user token, copy the check into Lighthouse `test/e2e/framework` as an internal
  test, and run it with `ADMIN_KUBECONFIG`/`USER_KUBECONFIG` and `GOFLAGS=-mod=mod`. On `release-0.23`, drop the helper's `ctx`
  argument and use `ptr.To(true)` instead of `new(true)`.

## Limits

- Nothing has run on an OpenShift cluster yet. The admission check uses fixture grants and namespace allocation; QE's rerun
  supplies the live result.
- 4.19 has no restricted-v3. An earlier run with 4.19's policy set gave the same restricted-v2 results.
- The runtime checks used rootless Podman, not CRI-O.
- Custom SCCs, restricted-v3-only policies, and restricted Pod Security namespaces are not covered.

Earlier exploratory material lives in git history at `9af2ecba` (branch `investigate/acm-48176-nettest`): the first candidate
patch, its test logs, the event collector, Subctl build records, the 4.19 run, and the review write-ups.
