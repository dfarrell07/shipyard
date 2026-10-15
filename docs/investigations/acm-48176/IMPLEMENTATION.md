# Implementation plan for ACM-48176

Deliver the [Lighthouse v0.23.4 candidate](evidence/lighthouse-scc.patch) through Subctl's compiled discovery tests.
Use isolated checkouts and `GOWORK=off` throughout Go checks and builds.

## 1. Change and test the Lighthouse builders

In `test/e2e/framework/deployments.go`, call a private `nettestRunAsUser(cluster) *int64` helper at the start of
`NewNginxDeployment` and `NewNetShootDeploymentInNS`, before creating the Deployment. `NewNetShootDeployment` delegates to the latter.

The helper must:

1. Create and defer cancellation of a context using `framework.TestContext.OperationTimeoutToDuration()`.
2. GET `/apis` through the target's authenticated `Discovery().RESTClient()`, with `Accept: application/json` and `Do(ctx).Get()`.
   Require an actual `*metav1.APIGroupList`; use Gomega to stop on HTTP, decoding, or type errors before any Deployment POST.
3. Return `nil` when a group is named `security.openshift.io`, otherwise `ptr.To(int64(10000))`.
   Assign this to the existing pod-level `SecurityContext.RunAsUser`.

Make the lookup per invocation and target, without a shared cache. SCC admission owns namespace UID selection.
Retain the image, commands, labels, resources, token setting, `runAsNonRoot`, seccomp, read-only root, dropped capabilities,
and privilege-escalation setting. The StatefulSet builder needs no change.

The caller needs GET `/apis`, normally provided by the default discovery role. Context-aware requests, rate-limit waits, and
retries obey the operation budget; zero budget fails immediately. Credential programs can ignore cancellation. Discovery identifies
the platform, not SCC grants or policy selection; the OpenShift path assumes restricted-v2 access and valid namespace UID/MCS allocation.
See the [audited implementation limits](evidence/RELEVANT-CASES-AUDIT.md).

Place regression tests in `test/unit/framework`; the shared unit runner prunes the entire `test/e2e` subtree.
Exercise the public builders through an HTTP fixture that captures Deployment requests and supplies a Running Pod to finish
the waiter. This verifies builder output; admission and controller behavior need separate checks. Cover:

- Correct UID and unchanged hardening on mixed A/B/C targets, with only the requested target's discovery counter incremented.
- HTTP 403/503, invalid/missing/wrong-type bodies, canceled requests, and zero budget: expected failure and zero Deployment POSTs.
  A correctly typed empty APIGroupList is valid and retains UID 10000.
- Authentication, legacy JSON negotiation, and the operation deadline; retain the proxy-prefix fixture check.
- Serial, synchronized fixtures that restore clients and globals. Copy TestContext before changing its primitive fields; install a
  fresh Gomega instance and restore the saved instance afterward. Return typed Status errors and assert the intended failure.

Run the shuffled repeated package tests with `-race`, lint/format both changed packages, and run normal `make unit` and applicable
e2e CI. Confirm unit logs include `./test/unit/framework`. Re-export both platforms after any candidate change: OpenShift output
must match the admission-checked no-UID templates; Kubernetes output must match the original templates.
The [candidate checks](evidence/candidate-provenance.json) and [complete host unit run](evidence/full-unit-provenance.json) pass;
landing CI/container validation remains required.

## 2. Pin and deliver a fresh Subctl executable

Land the Lighthouse fix on `release-0.23` through the normal upstream/backport process. Record its commit and publish an immutable
tag or canonical Go pseudo-version. Update Subctl's direct Lighthouse requirement and required `go.sum` entries; review any
transitive changes separately. The release must use the published dependency rather than a local replacement.

In Subctl's corresponding release checkout:

1. Check `go list -m -json github.com/submariner-io/lighthouse` for the intended version and unexpected replacements.
2. Run Subctl unit/build checks with normal version flags, and repeat builder exports under Subctl's selected module graph.
3. Record the source revision and build environment, then deliver through the applicable path below.

Prefer a fresh checkout. At inspected Subctl commit `4b44caa4`, the binary rule omits module files as prerequisites and checksum
output is appended. A reused tree therefore needs its relevant binaries, archives, and `dist/subctl-checksums.txt` removed;
`make clean` alone leaves the checksum file.

| Delivery path | Required evidence |
| --- | --- |
| Upstream standalone client | Exact source commit and rebuilt artifact checksum; the branch prerelease name is mutable |
| Downstream Konflux image | Successful prefetch/build at the dependency-update revision, image index, tested child digest/architecture |

The downstream Dockerfile builds `./cmd` into `/usr/local/bin/subctl` with the Red Hat toolset, `CGO_ENABLED=1`, and
`strictfipsruntime`. The local [Subctl build proof](evidence/subctl-validated-build-provenance.json) does not qualify that pipeline.

Inspect the **downloaded or extracted executable QE will run**: record its path/checksum and `go version -m` output, require the
correct Lighthouse identity, and reject unexplained replacements. A hermetic rewrite needs an explicit source/checksum mapping.
Version text or a prebuild module listing alone is insufficient. For containers, also retain the immutable image/platform identity.

Pinned delivery sources: [module requirements](https://github.com/submariner-io/subctl/blob/4b44caa4/go.mod),
[Makefile](https://github.com/submariner-io/subctl/blob/4b44caa4/Makefile),
[upstream workflow](https://github.com/submariner-io/subctl/blob/4b44caa4/.github/workflows/release_subctl_on_push.yml),
[Konflux pipeline](https://github.com/submariner-io/subctl/blob/4b44caa4/.tekton/subctl-0-23-push.yaml),
[Dockerfile](https://github.com/submariner-io/subctl/blob/4b44caa4/package/Dockerfile.subctl.konflux).
Recheck these against the landing revision.

## 3. Qualify on the failing clusters

Follow the [QE procedure](QE-VALIDATION.md) for the original/fixed comparison. Establish the original controller failure first;
UID 10000 rejection confirms this diagnosis, while a different failure requires revisiting it.
Keep the actual QE image digest, cluster configuration, namespace labels, and service-account grants unchanged.

Require controller-created Running helpers with the expected SCC/UID and all 14 original cases passed in both directions using
the inspected delivered artifact. The QE procedure defines capture, image overrides, exit-status checks, and exact-case acceptance.
Use the [case matrix](evidence/RELEVANT-CASES-AUDIT.md#coverage-and-its-practical-limits) for the plain-Kubernetes/older-image
controller regression and applicable three-cluster, IP-family, and feature CI. Restricted PSA and custom-policy behavior require
separate qualification.
