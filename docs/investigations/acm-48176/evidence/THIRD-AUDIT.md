# Third audit of the nettest plan

This audit re-derived the diagnosis from the Jira attachment, the release history, and the upstream source, without reusing the
earlier conclusions. It agrees with the UID diagnosis and the conditional Lighthouse candidate. It also found gaps in scope,
backports, release delivery, and the QE procedure that the earlier reviews missed. Exact inputs and hashes are in the
[provenance](third-audit-provenance.json).

## Re-derived from the attachment

A fresh authenticated download of attachment 1249936 matches the recorded SHA-256. The console shows every helper Deployment
create in the run failing, on both clusters, while every StatefulSet in the same namespaces reached Running:

| Cluster | Helper Deployments with zero pods | StatefulSets Running |
| --- | --- | --- |
| `submqe-azure` (OpenShift 4.19) | 6 of 6 `nginx-demo` | 3 of 3 |
| `submqe-gcp` (OpenShift 4.20) | 4 of 4 `nginx-demo`, 4 of 4 `netshoot` | 1 of 1 |

The StatefulSet uses the same `NettestImageURL`, the same `/app/simpleserver` command, the same namespace, and the same
`default` service account, but it has no securityContext. The shipyard waiter reports the pod-count mismatch before checking the
phase, so "Actual pod count 0" means no Pod objects existed after 240 seconds. The image was not crashing; the ReplicaSet
never created a Pod. Image pulls, scheduling, and the SCC-assigned UID therefore work for this image on both clusters. Only the
Deployment pod template differs. That template adds runAsUser 10000, runAsNonRoot, RuntimeDefault seccomp, read-only root,
dropped capabilities, resources, and no token.

## History that rules out the obvious counterarguments

- Lighthouse hardening (`13d29322`, PR #2230) first shipped in v0.23.2. ACM-44527 records that 0.23.2 was never shipped to
  production, so QE has never passed discovery with a hardened Lighthouse on OpenShift. No earlier green run contradicts the diagnosis.
- The second attempt (Shipyard #2618–#2626) removed `runAsUser` only from Shipyard's CI YAMLs. Those manifests are not in
  `subctl verify`'s path. The failing code is compiled into Subctl from Lighthouse `test/e2e/framework/deployments.go`, and
  it still has UID 10000 on every branch. Shipyard `devel` still has the YAML UIDs because #2618 is open.
- ACM-48194, filed by the same QE reporter 88 minutes after ACM-48176, describes the same symptom and states
  "Actual service discovery works fine".
  Treat it as a duplicate. The defect is in the verification helpers, not in Lighthouse's product data path.

## Independent admission check, including a no-rebuild confirmation

The [Deployment exporter](export-deployments.go.txt) captured the exact Deployment objects that the real v0.23.4 builders POST.
They are retained as [original](repro/original) manifests. The [corrected](repro/corrected) manifests differ only by the deleted pod `runAsUser`.
[This check](admission-nonroot-check.go.txt) ran them through the pinned OpenShift SCC admission plugin as the ReplicaSet
controller, with the shipped restricted-v2, restricted-v3, anyuid, privileged, and nonroot-v2 policies ([log](admission-nonroot-check.log)):

| Template | Extra grant | Result |
| --- | --- | --- |
| Original | None (stock) | Rejected: `provider restricted-v2: .containers[0].runAsUser: Invalid value: 10000: must be in the ranges` |
| Corrected | None (stock) | Admitted by restricted-v2 with the namespace's first UID |
| Original | nonroot-v2 to the namespace `default` SA, or to group `system:serviceaccounts` | Admitted by nonroot-v2 at UID 10000 |
| Original | nonroot-v2 to the human user only | Rejected as stock: the controller, not the user, creates the Pod |

The last two rows give QE a causal test that needs no rebuild. A temporary nonroot-v2 grant to service accounts should make the
unchanged 0.23.4 artifact's 14 cases reach their DNS assertions. The grant must be removed afterward. It also explains why the
directly created connectivity Pods pass: Shipyard's `NetworkPod` has also used UID 10000 since v0.23.3 (`aac46747`). Those Pods
are admitted through the administrator's own SCC access, which non-administrator `subctl verify` users would lack.

## Scope the earlier plan understated

Every Lighthouse branch carries the fixed UID. These tags and the Subctl releases that embed them are affected:

| Lighthouse branch | Affected tags | Subctl releases embedding them |
| --- | --- | --- |
| `devel` | v0.26.0-m0 | v0.26.0-m0 |
| `release-0.25` | v0.25.0-rc0, v0.25.0-rc1 | v0.25.0-rc1 |
| `release-0.24` | v0.24.2 | v0.24.2 |
| `release-0.23` | v0.23.2, v0.23.3, v0.23.4 | v0.23.2, v0.23.4 |
| `release-0.22` | v0.22.2 | v0.22.2 |
| `release-0.18`–`0.21` | None yet; the next tag will be affected | Next releases |

`subctl verify --only service-discovery` is a user-facing command. Any of these Subctl releases fails on OpenShift for the same
reason. The fix therefore needs a known-issue/release-note decision for shipped versions, not only a 0.23 respin.

## Backport hazards

- The candidate applies cleanly to `release-0.18` through `release-0.23`. On `devel`, `release-0.25`, and `release-0.24` it
  needs a manual port: those branches changed the surrounding lines to Go 1.26 `new(...)` forms.
- `release-0.18` does not compile with the candidate: Shipyard v0.18.5 lacks `TestContext.OperationTimeoutToDuration()`.
  `release-0.22` passes `go vet` for both changed packages.
- On `release-0.18`–`0.22`, the shared unit runner prunes every directory containing a `_test.go` file with the word `e2e`.
  The regression test imports `.../test/e2e/framework`, so `make unit` silently skips it there. Only the `RunE2ETests` rule on
  `release-0.23`+ keeps `test/unit/framework` running. Backport PRs must show the package in the unit log or run it explicitly.

## Delivery facts

- The Subctl image is not in the operator bundle's `relatedImages`, so this fix needs only a rebuilt and re-released Subctl
  component. The bundle, FBC catalogs, and operand images are unaffected. 0.23.4 is in stage and not yet in production,
  so the release owner can either respin Subctl for 0.23.4 or ship the fix in 0.23.5.
- Subctl derives the nettest image from cluster A's Submariner CR (`spec.repository`/`spec.version`/`imageOverrides`), unless
  `RELATED_IMAGE_submariner-nettest` is set. This confirms the older-image compatibility concern on plain Kubernetes.
  A new Subctl run against a deployment of 0.23.2 or earlier uses a root-default image.
- The inspected kube-aggregator v0.30.2 source lists every registered APIService group in legacy `/apis`, whether or not it
  is available. A degraded
  openshift-apiserver therefore does not make an OpenShift cluster look like plain Kubernetes. Subctl's `IsOcpPlatform`
  (`pkg/operator/ocp/ensure.go`) is the project precedent for platform detection. It treats every error as "not OpenShift" and
  needs SCC read access, so the candidate's stricter failure-on-error discovery is preferable in the e2e framework.
