# Evidence for ACM-48176

| Claim | Files |
| --- | --- |
| QE helper-setup failures and running StatefulSets | [Analysis](attachment-analysis.json), [provenance](provenance.json) |
| Exact v0.23.4 helper Deployments | [Manifests](repro/original), [exporter](export-deployments.go.txt) |
| Original rejection and corrected SCC admission | [Checker](admission-check.go.txt), [results](admission-check.log) |
| Nettest image users on 0.23.x | [Registry inspection](image-users.json) |
| Real kube-apiserver discovery as an unprivileged user | [Check](real-apiserver-check.go.txt), [devel](real-apiserver-devel.log) |
| The same check on the release-branch helpers | [Results](real-apiserver-release.log) |
| Every branch builds, passes, catches mutants, fails on its original code, and classifies live OpenShift | [branch-verification.log](branch-verification.log) |
| The PR descriptions | [pr-body.txt](pr-body.txt) |

Shipyard first sets `USER 10000` in `Dockerfile.nettest` in v0.22.2, v0.23.3, v0.24.2, and v0.25.0-rc0. Earlier images default to
root.

## Reproducing

- **Deployments:** extract `git archive v0.23.4` of Lighthouse and save the exporter as `cmd/acmexport/main.go`. Then run
  `GOWORK=off go run ./cmd/acmexport <dir>`. The corrected manifests delete only `spec.template.spec.securityContext.runAsUser`.
- **Admission:** check out `openshift/apiserver-library-go` at the pinned commit and copy the check into
  `pkg/securitycontextconstraints/sccadmission/`. Point `ACM_AUDIT_DIR` at a directory with the five pinned SCC policies under
  `scc/` and a copy of `repro/`, then run `go test -mod=vendor -run TestACM48176Admission -v`. Commits and hashes are in
  [provenance.json](provenance.json). The requester is the ReplicaSet controller, and the namespace range is `1001530000/10000`.
- **Real kube-apiserver:** start envtest's etcd and kube-apiserver with [real-apiserver-run.sh.txt](real-apiserver-run.sh.txt).
  Write kubeconfigs for an admin token and a plain-user token, copy the check into Lighthouse `test/e2e/framework` as an internal
  test, and run it with `ADMIN_KUBECONFIG`/`USER_KUBECONFIG` and `GOFLAGS=-mod=mod`. On the release branches, drop the helper's `ctx`
  argument, use `ptr.To(true)` instead of `new(true)`, and drop the zero-budget assertion: `ServerGroups()` takes no context.

## Limits

- The admission check uses fixture grants and namespace allocation. The helper's discovery was also checked against a live
  OpenShift API server, without creating workloads or changing grants. Neither check is an OpenShift workload acceptance run;
  ACM-44539's `FailedCreate` is the live rejection, and QE's run with a fixed Subctl supplies the end-to-end result.
- 4.19 has no restricted-v3. An earlier run with 4.19's policy set gave the same restricted-v2 results.
- Custom SCCs, restricted-v3-only policies, and restricted Pod Security namespaces are not covered.

Earlier exploratory material lives in git history at `9af2ecba` (branch `investigate/acm-48176-nettest`): the first candidate
patch, its test logs, the event collector, Subctl build records, the 4.19 run, and the review write-ups.
