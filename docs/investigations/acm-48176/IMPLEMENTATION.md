# Implementation plan for ACM-48176

Implement the correction in Lighthouse's discovery-test builders, then deliver it through Subctl's compiled dependency.
The [candidate patch](evidence/lighthouse-scc.patch) already implements and tests the proposed behavior against Lighthouse v0.23.4.
This document describes how to turn that candidate into a release change. No upstream code, dependency release, or QE deployment
has been changed by this notes branch.

## 1. Change the two Lighthouse builders

| File | Change |
| --- | --- |
| `test/e2e/framework/deployments.go` | Add private `nettestRunAsUser(cluster) *int64`; use its result in both Deployment templates |
| `test/unit/framework/deployments_uid_test.go` | Add regression coverage through the actual public builders |

Call the helper at the start of `NewNginxDeployment` and `NewNetShootDeploymentInNS`, before submitting any Deployment.
`NewNetShootDeployment` already delegates to the latter, so it needs no independent policy implementation.

The helper creates a context with `framework.TestContext.OperationTimeoutToDuration()` and defers its cancellation.
Use the passed target cluster's authenticated `Discovery().RESTClient()` to GET `/apis`, set `Accept: application/json`,
and decode with `Do(ctx).Get()`. Require the returned object to be an actual `*metav1.APIGroupList` before inspecting it.
Assert success using the framework's existing Gomega failure convention and the message
`discover API groups for nettest UID selection`. A failure must stop the builder before its Deployment POST.
Scan the returned groups by name: `security.openshift.io` means return `nil`; otherwise return `ptr.To(int64(10000))`.
Assign that pointer to the existing pod-level `SecurityContext.RunAsUser` field. A nil pointer omits the field in the request.

This reuses authentication without requiring SCC-list or authorization-review permissions. Context-aware HTTP requests,
rate-limit waits, and retries obey the existing operation budget; a zero budget fails immediately rather than disabling it.
Client-go credential programs and arbitrary transport hooks can ignore request cancellation; this helper does not repair that
preexisting limitation. Force legacy JSON so the reply is an APIGroupList even with aggregated discovery support.
HTTP/decode/type errors must fail explicitly rather than select UID 10000. In particular, decoding directly into a preallocated
APIGroupList silently accepts `{}` or `null`; independent decoding rejects these invalid discovery replies.
The caller needs GET access to the non-resource URL `/apis`. Upstream's default discovery role grants this to authenticated
users, but verify the actual identity on a customized cluster; a denial remains an explicit failure. See the pinned
[discovery role and binding](https://github.com/kubernetes/kubernetes/blob/v1.32.13/plugin/pkg/auth/authorizer/rbac/bootstrappolicy/policy.go#L202).

Do not use the earlier unbounded `ServerGroups()` candidate. Its assumed 32-second timeout does not hold for the framework's
actual clientset construction: the supplied shared HTTP client can have timeout zero. The second audit reproduced a stalled
`/apis` request still blocked after 33 seconds. Do not mutate that shared client or abandon a timed-out goroutine.
The [second audit](evidence/PLAN-AUDIT.md) records the finding and the replacement's deadline tests.

Do not cache a result globally or infer the remote platform from cluster A, the local machine, or the nettest image.
The small per-builder discovery lookup keeps mixed cluster pairs correct without cache invalidation or shared mutable state.
Do not infer the platform from a just-created namespace's UID annotation: allocation can arrive asynchronously.
Do not copy the namespace range minimum into the template; SCC admission owns policy selection and UID defaulting.

Keep every other template field unchanged, including the image, command, labels, resources, token mounting, `runAsNonRoot`,
seccomp, read-only root, privilege escalation setting, and dropped capabilities. Keep the StatefulSet builder unchanged.
The OpenShift branch assumes ordinary restricted-v2 access and valid namespace UID/MCS allocation. Group discovery identifies
the platform; it does not prove which SCC will be selected. The existing v3-only/custom-policy limits still apply.

## 2. Keep the regression in the actual unit gate

Use `test/unit/framework`, outside the e2e subtree pruned by Shipyard's shared unit script. No Makefile workaround is needed.
The candidate test fixture serves discovery, captures real Deployment POST bodies, and returns a synthetic Running Pod only to
finish the existing waiter. It does not simulate SCC admission; that is checked separately using the real admission code.

The committed regression should retain these checks:

- Both builders omit UID on OpenShift and retain UID 10000 on plain Kubernetes, with all other hardening preserved.
- Alternating and repeated target indices select the target's policy, catching an accidental global cache or cluster-A lookup.
  Include ClusterC because the supported third-context cases use these builders too.
- HTTP 403 and 503 produce the expected discovery failure and zero Deployment POSTs for both builders.
- Invalid HTTP 200 bodies, absent type metadata, and wrong object types fail with zero Deployment POSTs; a correctly typed
  empty APIGroupList remains a valid Kubernetes response.
- A stalled `/apis` request is canceled within the configured budget for both builders, with zero Deployment POSTs; zero budget
  also fails immediately. Assert the requested path and legacy JSON Accept header.
- HTTP capture is synchronized; tests restore clients, TestContext, and `gomega.Default` and do not mutate them in parallel.
  TestContext is a pointer: assign a separate struct copy before changing fields, then restore the original pointer.
  Install a fresh Gomega instance for the panic handler instead of modifying the saved instance's handler.

The fixture must request JSON explicitly and return typed Kubernetes Status errors; the real client can otherwise send protobuf
or decode an untyped fixture error differently. Verify the expected failure text/status, not just that some panic occurred.

Run the targeted package with `-race`, lint both changed packages, and run the repository's normal `make unit` gate when landing
the Lighthouse change. Confirm its log includes `./test/unit/framework`. The candidate's targeted tests, lint, and formatting pass.
The actual shared unit script also passed on a complete exact-base Git worktree: all six packages, including the new regression
and nested CoreDNS modules, with race detection and 291 Ginkgo specs. See [provenance](evidence/full-unit-provenance.json) and
[summary](evidence/full-unit-summary.log). This host execution does not replace the normal landing CI/container gate.
Export both platforms again after any implementation adjustment. OpenShift output must equal the admission-checked no-UID
templates; Kubernetes output must equal the original v0.23.4 templates. This detects unintended manifest changes.

## 3. Pin the fix in Subctl and force a fresh build

Land the Lighthouse change on the release line used by the failing executable (`release-0.23`), following the project's normal
upstream/backport process. Record the actual fix commit. Use an immutable published tag or canonical Go pseudo-version for it;
do not assume a future version number or ship a local `replace` directive.

In Subctl's corresponding release checkout, update the direct Lighthouse requirement in `go.mod` and the required `go.sum` entries.
Review the module diff and selected versions: do not bulk-upgrade all Submariner modules to obtain this builder fix.
If the chosen Lighthouse revision requires transitive changes, review those changes explicitly before accepting that revision.
Set `GOWORK=off` for the entire precheck, test, and build sequence, not just one inspection command. Confirm
`go list -m -json github.com/submariner-io/lighthouse` selects the intended immutable version without an unexpected replacement.
Record relevant Go environment settings and run the Subctl unit/build checks; repeat builder exports under **Subctl's** graph.

Build in a fresh isolated checkout, or remove the relevant existing Subctl build outputs first. At inspected Subctl commit
`4b44caa4`, the binary Makefile rule lists `.go` files as prerequisites but not `go.mod`/`go.sum`. Merely changing the dependency
and invoking `make build` in a previously built tree can reuse an old executable. For a reused release tree, remove the relevant
binaries, archives, and `dist/subctl-checksums.txt`: `make clean` leaves that checksum file, while its generation recipe appends.
A fresh checkout avoids both traps without changing unrelated build infrastructure.

The earlier local-replacement experiment proves compilation and dependency integration; it is not the release artifact.
Use the project's normal build/version flags for delivery, then record the source commit, resolved Lighthouse version, binary
checksum, and `go version -m` output. A `release-0.23` version string alone cannot distinguish old and corrected executables.
Published binaries may be stripped, so do not require `go tool nm` symbol inspection as the delivery gate.

## 4. Deliver the executable QE actually uses

For an upstream standalone client, rebuild the Subctl release artifact. The inspected release-0.23 workflow recreates the
mutable `subctl-release-0.23` prerelease on branch pushes; identify the exact source commit and downloaded binary checksum.
For downstream QE, run the corresponding Subctl Konflux build from the dependency-update commit and use its immutable image
digest. The existing pipeline prefetches the root Go module hermetically; the corrected dependency must be available to that
prefetch. `package/Dockerfile.subctl.konflux` compiles `./cmd` and installs `/usr/local/bin/subctl`.
Require successful prefetch and build results from that exact PipelineRun revision. The downstream build uses the Red Hat
toolset, `CGO_ENABLED=1`, and `strictfipsruntime`; the local compile does not qualify that build. Record the output image index,
tested child image digest/architecture, and embedded executable checksum/module metadata before running QE.

Confirm QE uses that binary/container, rather than an older client already on PATH. Record the actual executable path and
checksum, or the Subctl container digest and embedded binary/module identity. Inspect `go version -m` on that downloaded or
extracted executable itself: require the intended Lighthouse module and reject unexpected replacements. Any hermetic tooling
rewrite needs a recorded source/checksum mapping, not an assumption that a prebuild graph describes the final binary.
Updating Lighthouse agent/CoreDNS images,
nettest images, or Shipyard YAML alone does not update these compiled builders. No image security-setting change is required.

Sources for this delivery sequence are pinned to the inspected Subctl baseline:
[module requirements](https://github.com/submariner-io/subctl/blob/4b44caa4/go.mod),
[binary build rule](https://github.com/submariner-io/subctl/blob/4b44caa4/Makefile#L115),
[branch artifact workflow](https://github.com/submariner-io/subctl/blob/4b44caa4/.github/workflows/release_subctl_on_push.yml),
[Konflux pipeline](https://github.com/submariner-io/subctl/blob/4b44caa4/.tekton/subctl-0-23-push.yaml),
[downstream build](https://github.com/submariner-io/subctl/blob/4b44caa4/package/Dockerfile.subctl.konflux).
Recheck these files against the chosen landing revision before executing the release steps.

## 5. Qualify the delivered fix on the failing clusters

Start capture of namespace allocations, Deployment/ReplicaSet state, pod metadata, and events **before** the tests run.
Require successful LISTs and established WATCH responses on both contexts before starting tests; merely starting background
processes does not prove capture works. Preserve stderr, process status, resource versions, and owner UIDs. A collector error
or unexplained gap leaves the evidence incomplete. See the concrete [capture/run procedure](QE-VALIDATION.md).
Shipyard v0.23.4 deletes test namespaces immediately afterward; Subctl has no implemented preservation flag.
First establish why the original controller-created helper pods fail. FailedCreate events showing UID 10000 outside the
namespace range confirm the proposed cause; a different admission/controller failure requires revisiting that attribution.

Keep the nettest image digest, cluster configuration, and service-account grants unchanged for the original/fixed comparison.
Record `RELATED_IMAGE_submariner-nettest` if set: it takes precedence over Subctl's
`--image-override 'submariner-nettest=<image>@sha256:<digest>'`. Confirm the emitted image reference and the running pod's imageID.

Require both helper Deployments to produce Running pods through the real controllers, with the selected SCC and admitted
UID recorded. Then run all 14 previously failing discovery cases with the delivered executable in both cluster directions;
they must execute and pass, not disappear behind skips. Retain events and pod specs during execution, including any new failure.
Use two invocations with swapped `--context`/`--tocontext` and distinct JUnit reports. Require both command exit codes to be zero
and run the [case-identity checker](evidence/check_discovery_junit.py) against both reports. It checks each original case exactly
once, rejects skips/failures/errors, dry runs, declared suite retries, and new reported failures.
The pinned Ginkgo JUnit format omits per-case attempt counts. Audit the landed discovery sources and invocation wrappers for
per-spec retries, or retain independent per-case attempt evidence; JUnit alone cannot rule them out.
Use the [relevant-case matrix](evidence/RELEVANT-CASES-AUDIT.md) for applicable three-cluster, IP-family, and feature e2e gates.
Preserve the framework's actual namespace PSA labels; SCC checks do not qualify a restricted-PSA suite.
The plain-Kubernetes/older-image regression remains covered by the candidate and legacy-image tests; a target rerun should
also confirm that branch when a plain Kubernetes test cluster is available.

Closure requires both correct artifact delivery and successful QE discovery. The completed offline admission, local container,
race, and build checks support this implementation; they do not replace that final controller-path qualification.
