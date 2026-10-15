# ACM-48176: nettest hardening regression investigation

Investigated 2026-10-15. Shipyard checkout: `ebd5c514` (devel). Lighthouse fix worktree: `fix/acm-48176-scc`, based on `origin/release-0.23`
at `3871dff3`. Shipyard 0.23 fix worktree: `fix/acm-48176-iperf`, based on `origin/release-0.23` at `380d703f`.

## Findings and confidence

1. **Strong candidate for ACM-48176: Lighthouse still forces UID 10000 in controller-created test pods.** Both `NewNginxDeployment` and
`NewNetShootDeploymentInNS` set `PodSecurityContext.RunAsUser=10000`. This is the same OpenShift admission regression already corrected
in Shipyard's helper YAML. The Lighthouse builders do not use that YAML or Shipyard's shared NetworkPod security context. The fix must
reach Lighthouse and the binaries embedding it. 2. **Separately reproduced regression: throughput tests fail with a read-only root and no
writable `/tmp`.** Both shipped RHEL iperf3 3.9    and community Fedora iperf3 3.22 need temporary stream-buffer files. The Shipyard
hardening added read-only roots but omitted scratch    mounts on both throughput pod types. Fixing just one endpoint is insufficient. 3.
**The image's non-root default and HTTP server work in the tested images.** Both images run `simpleserver`, respond `Hello World`, and
execute `dig` under UID 1000780000 with a read-only root, capability drop ALL, and no privilege escalation. These checks support
preserving `USER 10000` in the Dockerfiles and the other pod hardening.

See the [second-pass review](DEEP-REVIEW.md) for pinned admission/conversion sources, all 14 setup paths, and the failure analysis of
earlier reviews.

The first finding is a source-confirmed admission defect under the normal restricted SCC UID strategy, but attribution of the actual
reported QE run remains **unconfirmed** without its complete timeout output and pod/controller events. The second finding is independently
reproduced and is **not an explanation for the 14 service-discovery failures**, which do not exercise iperf3.

## What the report actually contains

Read via the public [Jira REST API](https://redhat.atlassian.net/rest/api/2/issue/ACM-48176). Snapshot:
[evidence/issue.json](evidence/issue.json).

- Created October 15, 2026; status New at inspection.
- Description says selected version 0.23.4; the affected-version metadata says Submariner 0.23.2. Treat these as distinct until the
  binary/build is identified.
- Summary: 14 service-discovery failures, 15 passing specs, 21 skipped; 3504.408 seconds total.
- Every reported failure cites shipyard v0.23.4 `framework.go:605`.
- **No attachments, comments, or issue links were returned.** There are no attached full logs to analyze in the available report.
- Line 605 is `Expect(err).NotTo(HaveOccurred(), errMsg)` in the generic `AwaitUntil` polling helper. It does not identify DNS, the image, a
  crash, or admission as the failing operation. The omitted `errMsg` and earlier test steps matter.

## Change history and why the follow-up was incomplete

<!-- markdownlint-disable MD013 -->
| Change | Behavior and consequence |
| --- | --- |
| Shipyard `fa19b53c` / release-0.23 `097d3710` | Set community nettest image `USER 10000`. This supplies a non-root fallback on plain Kubernetes and local container runs. |
| Release-0.23 `19353a28` | Set Konflux nettest `USER 10000`, pin UBI digest, and switch the metrics proxy from ncat shell execution to direct execution. The proxy is not the HTTP server used by the failing service-discovery tests. |
| Shipyard `51bf4704` / release-0.23 `e9c422f6` | Add hardening to three helper workload YAML files, including explicit pod UID 10000. That explicit pod identity conflicts with OpenShift namespace UID ranges. |
| Shipyard `e4f20366` / release-0.23 `68d4bf54` | Add read-only root filesystems and resources to NetworkPods. No writable scratch was supplied to the iperf3 pods. The investigation plan in `glasswing-shipyard-report.md` had called for a `/tmp` emptyDir, but that did not reach the implementation. |
| Lighthouse `13d29322`, [PR #2230](https://github.com/submariner-io/lighthouse/pull/2230) | Independently harden nginx and netshoot Deployment builders, also explicitly choosing UID 10000. This creates an additional admission failure path beyond Shipyard YAML. |
| Shipyard release-0.23 `ee1addaf` | Remove YAML UID override but add `hostUsers` under `securityContext`. That field placement is invalid. |
| Shipyard release-0.23 `df6241bf` | Remove invalid `hostUsers`. Combined result: just remove the explicit UID. Both follow-ups precede v0.23.4. The released helper YAML therefore already contains the corrected change. |
| Shipyard [PR #2618](https://github.com/submariner-io/shipyard/pull/2618) | Still open for devel. Its current patch removes only the three helper UID overrides. |
<!-- markdownlint-enable MD013 -->

OpenShift's `restricted-v2` uses `MustRunAsRange` to default and validate UIDs. An explicit 10000 is outside a typical generated namespace's
allocation (the accessible Konflux namespace, for example, has 1000780000/10000). Omitting the UID allows SCC admission to choose it. The
image's `USER` is a fallback, not a requirement to run as exactly that user.

Sources: [OpenShift SCC
documentation](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/authentication_and_authorization/managing-pod-security-policies),
[Kubernetes user namespaces](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/). `hostUsers` belongs to PodSpec. Setting
it to false opts into user namespaces, with runtime requirements; that is not necessary for a restricted-v2-compatible UID correction. A
cluster that only grants restricted-v3 requires separate qualification.

The framework creates namespaces with `pod-security.kubernetes.io/enforce=privileged` and disables SCC-to-PSA label synchronization. These
PSA settings do not grant a service account permission to use a privileged SCC; they do not repair a restricted SCC UID rejection.

The distinction between the builders matters:

- Lighthouse creates Deployments; SCC admission for the subsequent pods considers their service account and the controller request identity.
  Successfully creating the Deployment does not prove its pods were admitted. A denied ReplicaSet repeatedly creates no pods, and the
  framework's pod-count poll times out at the generic assertion.
- Shipyard NetworkPods are created directly by the framework client and already specified UID 10000 before this hardening. Their requesting
  identity and host-network requirements can permit different SCCs. Changing that whole framework identity policy is outside the minimal
  demonstrated regression fix.
- Lighthouse's StatefulSet builder does not set the new UID. However, its three reported test cases subsequently create a **netshoot
  Deployment**, so a working StatefulSet does not prevent the common setup failure.
- Other service-discovery cases create nginx Deployments and then netshoot Deployments. These builders offer a common failure path across
  the reported groups.
- `subctl/internal/verify/verify.go` imports Lighthouse discovery tests. The local Subctl module references both Lighthouse and Shipyard
  v0.23.4. A new nettest image, new helper YAML, or a Shipyard-only dependency bump cannot change a Lighthouse Deployment template already
  compiled into Subctl.

## Corrections prepared locally

### Lighthouse: actual service-discovery test builders

In the isolated [Lighthouse patch](evidence/lighthouse-scc.patch), remove only the two `RunAsUser` fields. Keep non-root execution,
RuntimeDefault seccomp, disabled token mounting, capability drops, no privilege escalation, read-only roots, and resource settings.

Portable patch: [evidence/lighthouse-scc.patch](evidence/lighthouse-scc.patch).

### Shipyard devel: helper workload YAML

Remove the three explicit `runAsUser` fields, matching the existing PR #2618 correction. Semantic YAML comparison confirms those are the
only changes. No `hostUsers` field is introduced. Release 0.23 already has this change.

Portable patch: [evidence/shipyard-helper-uid.patch](evidence/shipyard-helper-uid.patch).

### Shipyard: iperf3 scratch space

Mount a separate default-storage `emptyDir` at `/tmp` in both throughput client and throughput server containers, configured with a 64 MiB
size limit. Preserve the read-only root and throughput resource policy. Default node storage avoids explicitly allocating tmpfs against the
benchmark's memory budget. Kubernetes enforces disk emptyDir limits through its storage accounting/eviction behavior, not a synchronous
filesystem quota.

Do not mount scratch into the HTTP/sleep workloads without a demonstrated need. The existing `netserver -D` latency configuration passed a
local TCP_RR run with the same read-only/capability restrictions.

Portable devel implementation and regression-test patch: [evidence/shipyard-iperf-scratch.patch](evidence/shipyard-iperf-scratch.patch). A
separately adapted [0.23 patch](evidence/shipyard-release-0.23-iperf-scratch.patch) and [0.23
implementation](evidence/shipyard-release-0.23-iperf-scratch.patch) target the reported stream. Both working checkouts also include a
regression test that inspects both pod types through their actual Kubernetes client API requests. The constructor signatures differ between
devel and 0.23, so the test was adapted rather than copied unchanged.

## Further findings from the second pass

The [deep review](DEEP-REVIEW.md) explains the internal/external HostUsers conversion trap and why earlier validation missed these
issues. It also records how the framework regression was initially excluded from `make unit`, and the build-target correction.

The [benchmark follow-up](BENCHMARK-FOLLOWUP.md) documents a pre-existing retry loop that could return success after all iperf3
attempts failed. This branch now corrects that exit status and tests the emitted shell command. Subctl also needs a separate change
to check the pod's finish status in verbose mode; an unapplied candidate patch is retained with the notes. The scratch-only 0.23
patch remains a separate artifact and does not yet include this additional retry fix or the build-target wiring.

## Runtime evidence

[Reproduction script](evidence/runtime_checks.py), [results](evidence/runtime-results.json), and individual logs are in `evidence/`.

Pinned images:

- Konflux 0.23.4:
  `quay.io/redhat-user-workloads/submariner-tenant/nettest-0-23@sha256:a4ca9da9d5e1193a89956f5d5e6db7c1e02297ccb450a6a72a9b228f5ab06ae1`;
  labels identify Shipyard revision `380d703f03f2c00373801c40f0b8cc7ed4186ccd`, built October 1. This is the component's current promoted
  build, **not a verified digest from the failing QE run**.
- Community devel: `quay.io/submariner/nettest@sha256:378d5785fd8c84ed6d0f6bbe64a6245380d6e6de6d1d6a84cef3e692858c9181`.

All throughput checks use separate containers for client and server, read-only roots, UID 10000, dropped capabilities, no privilege
escalation, and `iperf3 -P 10 -w 256K -t 1` over loopback. Podman's implicit writable temporary mounts are explicitly disabled. The writable
variants use an explicit 64 MiB `/tmp` tmpfs as a local runtime reproduction; the Kubernetes patch emits a disk-backed emptyDir. These runs
test functional behavior, not performance or OpenShift admission.

<!-- markdownlint-disable MD013 -->
| Server /tmp writable | Client /tmp writable | Konflux 3.9 | Community 3.22 |
| --- | --- | --- | --- |
| No | No | Fail | Fail |
| Yes | No | Fail in client | Fail in client |
| No | Yes | Fail in server | Fail in server |
| Yes | Yes | Pass | Pass |
<!-- markdownlint-enable MD013 -->

With only the client fixed, RHEL's client reports `unable to initialize stream: Transport endpoint is not connected`; the server log exposes
the underlying read-only filesystem error. This is why looking only at the client can misleadingly suggest a networking fault.

The [image-default check](evidence/image-default-users.json) separately records each pinned image’s configured user and runs
`id -u` without any user override. Both return 10000. The arbitrary-UID checks below establish a different property.

HTTP/DNS checks use UID 1000780000 mapped explicitly into the local rootless container namespace. An initial attempt without that mapping
hit the local Podman UID-map limit; it was not an image permission failure. Both mapped checks pass.

## Verification and release follow-through

Verification completed:

- Shipyard devel `go test -p 2 ./test/e2e/framework`: **PASS**.
- Shipyard release-0.23, same command with the adapted regression test: **PASS**.
- The devel regression test with a Go overlay restoring the original `network_pods.go`: **FAIL as expected**, because the emitted pod has no
  `/tmp` mount.
- Lighthouse release-0.23 `go test -p 2 ./test/e2e/framework`: **compile PASS**; that package has no unit test files.
- Shipyard devel `golangci-lint run --concurrency=2 ./test/e2e/framework`: **0 issues** after simplifying the test fixture and applying
  whitespace fixes.
- YAML lint and parsed semantic comparisons: **PASS**, exactly three UID removals and no other YAML changes.
- Lighthouse source comparison: **PASS**, exactly two UID removals and no other configuration changes.
- `git diff --check`: **PASS** for all three working checkouts. Both complete Shipyard patches (including tests) pass reverse-application
  checks against their working trees.
- Automatic selection caveat: the new framework test was initially run directly, but the shared unit runner prunes its parent subtree. See
  the second-pass review and follow-up build-target correction.
- Local image runtime matrix: **10 expected results**, with the eight throughput combinations and two arbitrary-UID HTTP/DNS checks detailed
  above.

Logs are stored alongside the evidence. The verification list above describes the initial scratch/UID correction; the follow-up
review and benchmark notes identify later corrections and their additional checks. Committed log presentation removes ANSI colors,
expands tabs, and strips trailing blanks. Patch artifacts retain their required context whitespace. Image metadata snapshots omit the
registry's unrelated mutable tag listing. These presentation changes do not alter the recorded statuses, diagnostics, digests, or
measurement values. Initial concurrent Go builds exhausted the per-user `/tmp` quota; reruns with task-specific
`GOTMPDIR` on the home filesystem completed successfully. The available cluster credentials can read the Konflux namespace and image
metadata but cannot create pods there or read SCC definitions, so no actual OpenShift admission or two-cluster QE rerun is claimed.

Before calling ACM-48176 resolved:

1. Obtain the complete failure output, exact Subctl/Lighthouse versions, test image digest, and target OpenShift version. 2. Inspect the
failing namespace's Deployment/ReplicaSet events and pod status. The predicted signature is a FailedCreate event rejecting    UID 10000
under restricted SCCs, followed by a pod-count timeout. A different signature requires revisiting the attribution:    Pending/Unschedulable
points at scheduling and resource requests; CreateContainerError or CrashLoopBackOff requires the runtime error and    container logs;
successful setup followed by a dig assertion requires DNS investigation. The generic assertion alone does not distinguish    them. 3. Apply
the Lighthouse fix to 0.23, update the dependency in Subctl, and rebuild the verification binary. Re-run the 14 discovery cases on    the
intended QE clusters, including the StatefulSet and special-namespace netshoot paths. 4. Independently backport the Shipyard iperf3 scratch
fix and update its consumers; exercise both benchmark endpoints and confirm their    emitted mounts and security context. 5. Carry the
missing Lighthouse UID correction and throughput scratch correction through the other maintained streams as appropriate. Local    remote-ref
inspection found the former in devel and release-0.18 through release-0.25, and found read-only roots without throughput    mounts in each
of those Shipyard refs. Refresh refs before submitting backports. Shipyard's helper UID removal is already present in all    those release
refs; devel remains open in PR #2618.

This investigation and the Shipyard changes are maintained on `investigate/acm-48176-nettest` in the author’s Shipyard fork. The Lighthouse
and Shipyard 0.23 changes are included as portable patches. No PR, Jira comment, image publication, or cluster workload has been submitted.
