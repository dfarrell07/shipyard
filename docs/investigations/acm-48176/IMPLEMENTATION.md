# Implementation plan for ACM-48176

Deliver the Lighthouse change through Subctl's compiled discovery tests. Commits for every branch are prepared; see the
[execution runbook](EXECUTION.md).
Use isolated checkouts and `GOWORK=off` throughout Go checks and builds.
Every Lighthouse branch has the defect, so land it on `devel` first and backport it to each maintained branch (section 2).

## 1. Change and test the Lighthouse builders

In `test/e2e/framework/deployments.go`, call a private `nettestRunAsUser(cluster) *int64` helper at the start of
`NewNginxDeployment` and `NewNetShootDeploymentInNS`, before creating the Deployment. `NewNetShootDeployment` delegates to the latter.

The helper must:

1. Create and defer cancellation of a context using `framework.TestContext.OperationTimeoutToDuration()`.
2. GET `/apis` through the target's authenticated `Discovery().RESTClient()`, with `Accept: application/json` and `Do(ctx).Get()`.
   Require an actual `*metav1.APIGroupList`; use Gomega to stop on HTTP, decoding, or type errors before any Deployment POST.
3. Return `nil` when a group is named `security.openshift.io`, otherwise `ptr.To(int64(10000))`.
   Assign this to the existing pod-level `SecurityContext.RunAsUser`.

On `devel` and `release-0.25` the builders already take a `ctx`; there the helper is `nettestRunAsUser(ctx, cluster)`, derives
its timeout context from that `ctx`, and returns `new(int64(10000))` in that branch's Go 1.26 style.

Make the lookup per invocation and target, without a shared cache. SCC admission owns namespace UID selection.
Retain the image, commands, labels, resources, token setting, `runAsNonRoot`, seccomp, read-only root, dropped capabilities,
and privilege-escalation setting. The StatefulSet builder needs no change.

The caller needs GET `/apis`, normally provided by the default discovery role. Context-aware requests, rate-limit waits, and
retries obey the operation budget; zero budget fails immediately. Credential programs can ignore cancellation. Discovery identifies
the platform, not SCC grants or policy selection; the OpenShift path assumes restricted-v2 access and valid namespace UID/MCS allocation.
See the [audited implementation limits](evidence/RELEVANT-CASES-AUDIT.md).

Place regression tests in `test/unit/framework`; the shared unit runner prunes the entire `test/e2e` subtree. Every other
Lighthouse unit test is a Ginkgo suite, so the prepared commits use a small Ginkgo suite rather than the earlier 436-line
plain `testing` file. An HTTP fixture serves discovery, captures Deployment POSTs, and returns a Running Pod to finish the waiter.
For both builders it checks:

- UID unset on the cluster serving `security.openshift.io`, UID 10000 on the other, one lookup per target, hardening unchanged.
- HTTP 403 and a non-`APIGroupList` body fail before any Deployment POST.
- A stalled discovery request fails within the operation timeout.

Each test fails against a plausible wrong implementation: the original code, always querying cluster A, falling back to 10000
on errors, unbounded discovery, or dropped `runAsNonRoot`. A real kube-apiserver run covers what a fixture cannot: the
unprivileged default discovery role, real `APIGroupList` decoding, and classification via a served `security.openshift.io` group.
The earlier candidate's exhaustive fixture cases (proxy prefix, malformed bodies, exec credentials) remain reviewable in
[the candidate patch](evidence/lighthouse-scc.patch). The [execution runbook](EXECUTION.md) lists results per branch.

## 2. Land on every affected branch

The [third audit](evidence/THIRD-AUDIT.md#scope-the-earlier-plan-understated) found UID 10000 on all nine Lighthouse branches.
Affected Subctl releases are v0.22.2, v0.23.2, v0.23.4, v0.24.2, v0.25.0-rc1, and v0.26.0-m0. Port per branch:

| Branches | Adaptation |
| --- | --- |
| `devel`, `release-0.25`, `release-0.24` | Port by hand; Go 1.26 `new(...)` forms changed the context lines |
| `release-0.23`–`release-0.19` | Candidate applies cleanly; compile-checked on 0.23 and 0.22 only |
| `release-0.18` | Also replace `OperationTimeoutToDuration()`, which Shipyard v0.18.5 lacks, with `OperationTimeout` seconds |

On `release-0.18`–`0.22`, the shared unit runner prunes test directories whose files mention `e2e`, so `make unit` would skip
`test/unit/framework`. In those PRs, run the package explicitly and attach the output, or keep the test only on branches whose
runner selects it. Do not count a green `make unit` there as regression coverage.

Shipyard #2618 (`devel` CI YAMLs) is still open; merge it separately. It does not affect `subctl verify`.
Add a known-issue/release note for shipped versions: `subctl verify --only service-discovery` fails on OpenShift with those
releases until users upgrade Subctl. Deployed Submariner components are unaffected.

## 3. Pin and deliver a fresh Subctl executable

On each branch, record the Lighthouse fix commit and publish an immutable tag or canonical Go pseudo-version. Update Subctl's direct
Lighthouse requirement and required `go.sum` entries; review any transitive changes separately. The release must use the published
dependency rather than a local replacement.

Only the Subctl component needs rebuilding and re-releasing. Its image is not in the operator bundle's `relatedImages`,
and the change is test-framework code, so bundle, FBC, and operand images are unaffected. 0.23.4 is staged but not in production.
The release owner must decide whether to respin the 0.23.4 Subctl component from `release-0.23` or ship the fix as 0.23.5.

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

## 4. Qualify on the failing clusters

Follow the [QE procedure](QE-VALIDATION.md). Its scratch-namespace reproduction establishes the original controller failure first,
before the fix lands; UID 10000 rejection confirms this diagnosis, while a different failure requires revisiting it.
Keep the actual QE image digest, cluster configuration, namespace labels, and service-account grants unchanged; remove QE step 2's
temporary diagnostic grant before the acceptance run.

Require controller-created Running helpers with the expected SCC/UID and all 14 original cases passed in both directions using
the inspected delivered artifact. The QE procedure defines the reproduction, image overrides, exit-status checks, and
exact-case acceptance.
Use the [case matrix](evidence/RELEVANT-CASES-AUDIT.md#coverage-and-its-practical-limits) for the plain-Kubernetes/older-image
controller regression and applicable three-cluster, IP-family, and feature CI. Restricted PSA and custom-policy behavior require
separate qualification.
