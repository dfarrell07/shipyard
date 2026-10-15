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

The helper calls `framework.KubeClients[cluster].Discovery().ServerGroups()` with the passed target cluster index.
Assert success using the framework's existing Gomega failure convention and the message
`discover API groups for nettest UID selection`. A failure must stop the builder before its Deployment POST.
Scan the returned groups by name: `security.openshift.io` means return `nil`; otherwise return `ptr.To(int64(10000))`.
Assign that pointer to the existing pod-level `SecurityContext.RunAsUser` field. A nil pointer omits the field in the request.

This uses the existing authenticated client and its timeout; it does not need SCC-list or authorization-review permissions.
In the inspected client-go v0.35.8 implementation, discovery reads `/api` and `/apis` and defaults to 32 seconds **per request**
when no timeout was configured. An HTTP/decode/transport error returned by discovery must not be interpreted as absence of OpenShift.
Use group discovery rather than fetching every group's resources: an unrelated aggregated API's resource failure should not
become an assertion that the OpenShift group is absent.

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
- HTTP 403 and 503 produce the expected discovery failure and zero Deployment POSTs for both builders.
- HTTP capture is synchronized; tests restore modified global clients/context and do not run those mutations in parallel.

The fixture must request JSON explicitly and return typed Kubernetes Status errors; the real client can otherwise send protobuf
or decode an untyped fixture error differently. Verify the expected failure text/status, not just that some panic occurred.

Run the targeted package with `-race`, lint both changed packages, and run the repository's normal `make unit` gate when landing
the Lighthouse change. Confirm its log includes `./test/unit/framework`. The candidate's targeted tests, lint, formatting, and
actual shared-runner package selection have already passed; see the [audit](evidence/EXPERT-AUDIT.md).
Export both platforms again after any implementation adjustment. OpenShift output must equal the admission-checked no-UID
templates; Kubernetes output must equal the original v0.23.4 templates. This detects unintended manifest changes.

## 3. Pin the fix in Subctl and force a fresh build

Land the Lighthouse change on the release line used by the failing executable (`release-0.23`), following the project's normal
upstream/backport process. Record the actual fix commit. Use an immutable published tag or canonical Go pseudo-version for it;
do not assume a future version number or ship a local `replace` directive.

In Subctl's corresponding release checkout, update the direct Lighthouse requirement in `go.mod` and the required `go.sum` entries.
Review the module diff and selected versions: do not bulk-upgrade all Submariner modules to obtain this builder fix.
If the chosen Lighthouse revision requires transitive changes, review those changes explicitly before accepting that revision.
Confirm `GOWORK=off go list -m -json github.com/submariner-io/lighthouse` selects the intended immutable version without a local
replacement. Run the Subctl unit/build checks and repeat the builder exports under **Subctl's** resolved module graph.

Build in a fresh isolated checkout, or remove the relevant existing Subctl build outputs first. At inspected Subctl commit
`4b44caa4`, the binary Makefile rule lists `.go` files as prerequisites but not `go.mod`/`go.sum`. Merely changing the dependency
and invoking `make build` in a previously built tree can reuse an old executable. This is a delivery precaution, not a request
to change unrelated build infrastructure in this fix.

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

Confirm QE uses that binary/container, rather than an older client already on PATH. Record the actual executable path and
checksum, or the Subctl container digest and embedded binary/module identity. Updating Lighthouse agent/CoreDNS images,
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
Shipyard v0.23.4 deletes test namespaces immediately afterward; Subctl has no implemented preservation flag.
First establish why the original controller-created helper pods fail. FailedCreate events showing UID 10000 outside the
namespace range confirm the proposed cause; a different admission/controller failure requires revisiting that attribution.

Keep the nettest image digest, cluster configuration, and service-account grants unchanged for the original/fixed comparison.
Record `RELATED_IMAGE_submariner-nettest` if set: it takes precedence over Subctl's
`--image-override 'submariner-nettest=<image>@sha256:<digest>'`. Confirm the emitted image reference and the running pod's imageID.

Require both helper Deployments to produce Running pods through the real controllers, with the selected SCC and admitted
UID recorded. Then run all 14 previously failing discovery cases with the delivered executable in both cluster directions;
they must execute and pass, not disappear behind skips. Retain events and pod specs during execution, including any new failure.
The plain-Kubernetes/older-image regression remains covered by the candidate and legacy-image tests; a target rerun should
also confirm that branch when a plain Kubernetes test cluster is available.

Closure requires both correct artifact delivery and successful QE discovery. The completed offline admission, local container,
race, and build checks support this implementation; they do not replace that final controller-path qualification.
