# ACM-48176: nettest discovery failure

Fix the UID selection in Lighthouse's `NewNginxDeployment` and `NewNetShootDeploymentInNS`, then rebuild Subctl with that change.
The [candidate patch](evidence/lighthouse-scc.patch) is ready for review against Lighthouse v0.23.4.
This branch contains the plan, candidate, and evidence; the release change and live QE qualification remain outstanding.

## Proposed fix

Choose the pod's `RunAsUser` separately for each target cluster:

| Target | UID selection |
| --- | --- |
| API discovery advertises `security.openshift.io` | Omit the UID; let SCC admission assign it |
| Other Kubernetes clusters | Retain UID 10000 |

Use authenticated discovery with the operation timeout and reject invalid responses and request errors.
Preserve the other hardening settings.
The explicit UID remains necessary for older nettest images, including 0.23.2, which default to root and would otherwise fail
`runAsNonRoot` on plain Kubernetes. See the [image compatibility evidence](evidence/release-image-platform-audit.json).

These builders are compiled into Subctl. Updating an image or Shipyard YAML does not deliver this correction.

## Why this fits the report

The attached `e2e.zip` shows 14 failures during helper Deployment setup, before DNS assertions: ten find zero `nginx-demo` pods,
and four find zero `netshoot` pods. A StatefulSet using the same configured image is already Running in the local case's namespace.
This points toward helper pod creation rather than an image-wide failure. See the [attachment analysis](evidence/attachment-analysis.json).

Glasswing hardening fixed these builders' UID at 10000. OpenShift SCC admission can reject that UID outside the namespace range;
the offline admission checks reproduce rejection and successful SCC defaulting after the correction. Passing directly created
connectivity Pods do not validate the ReplicaSet controller's SCC permissions.

**UID rejection remains the leading explanation, not a confirmed QE admission event.** The archive lacks ReplicaSet events,
selected SCCs, namespace allocations, the exact nettest digest, and the executable checksum.

## Validation so far

| Check | Result and evidence |
| --- | --- |
| OpenShift admission and namespace allocation | 66 expected outcomes on pinned 4.19/4.20 code: [admission audit](evidence/EXPERT-AUDIT.md) |
| Current and legacy images | 18 local runtime cases, 72 HTTP responses: [coverage and limits](evidence/RELEVANT-CASES-AUDIT.md) |
| Shared unit runner | Six packages pass with race detection, 291 Ginkgo specs plus builder regressions: [summary](evidence/full-unit-summary.log) |
| Subctl integration | Fresh build, module inspection, CLI smoke, and template comparisons pass: [provenance](evidence/subctl-validated-build-provenance.json) |

These checks support restricted-v2 access with valid namespace allocation. Custom SCCs, v3-only policies, and native
runtime/feature coverage are detailed in the [case matrix](evidence/RELEVANT-CASES-AUDIT.md#coverage-and-its-practical-limits).
Local checks do not establish controller behavior or end-to-end DNS success on the failing clusters.

## Remaining steps

1. Capture the original helper Deployments' controller events and establish the actual failure cause.
2. Land the Lighthouse correction on `release-0.23`, pin it in Subctl, and build the delivered artifact.
3. Verify Running helpers under the expected SCC/UID, then require all 14 original cases to pass in both cluster directions.

Follow the [implementation plan](IMPLEMENTATION.md) for code and delivery, and the [QE procedure](QE-VALIDATION.md) for capture,
commands, and acceptance. Detailed review history and reproductions remain in the [audit evidence](evidence/RELEVANT-CASES-AUDIT.md).
