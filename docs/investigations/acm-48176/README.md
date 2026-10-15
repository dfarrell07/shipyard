# ACM-48176: nettest discovery failure

## Proposed fix

Remove `RunAsUser: 10000` from the two Lighthouse Deployment builders:

- `NewNginxDeployment`
- `NewNetShootDeploymentInNS`

Let OpenShift choose an allowed UID. Keep `runAsNonRoot`, read-only roots, dropped capabilities, no privilege escalation,
RuntimeDefault seccomp, disabled token mounting, and resource settings.

The [Lighthouse 0.23 patch](evidence/lighthouse-scc.patch) contains the two removals. Update Subctl to consume the corrected
Lighthouse version and rebuild it: these builders are compiled into its discovery tests. Updating the nettest image alone
will not change them.

This Shipyard branch also removes the fixed UID from its three helper YAML templates, matching
[PR #2618](https://github.com/submariner-io/shipyard/pull/2618). Shipyard 0.23 already has that YAML correction; Lighthouse's
independent Go builders were missed by the follow-up.

## Why this is the leading explanation

The Glasswing hardening added an explicit pod UID of 10000. OpenShift's range-constrained SCCs can reject that UID when it falls
outside the namespace allocation. Omitting it permits SCC defaulting. The image's default USER is a separate setting and should
remain non-root.

All 14 reported discovery cases reach a netshoot Deployment in the inspected Lighthouse 0.23 source; most also create an nginx
Deployment. The StatefulSet cases create netshoot after creating the StatefulSet, so their names do not exclude this failure path.
The [case mapping](evidence/failure-paths.json) records the relevant setup calls.

The earlier Shipyard follow-up briefly added `securityContext.hostUsers`, then removed it before v0.23.4. That is an invalid
external API location. The SCC error path reflects internal Kubernetes types; API conversion places the external field at
`spec.hostUsers`. This UID fix does not need a user-namespace setting.

Sources: [SCC UID defaulting and validation](https://github.com/openshift/apiserver-library-go/blob/f0d44ef6e53b49bd864c035752191a85b293af14/pkg/securitycontextconstraints/user/mustrunasrange.go),
[internal/external API conversion](https://github.com/kubernetes/kubernetes/blob/v1.33.2/pkg/apis/core/v1/conversion.go#L302).

## Evidence and limits

The [report snapshot](evidence/issue.json), inspected October 15, 2026, contains 14 discovery failures and no attached logs or comments.
It names Shipyard v0.23.4, but does not establish the failing executable's Lighthouse revision, image digest, or OpenShift version.
The description says 0.23.4 while the affected-version metadata says 0.23.2.

Every failure points to the generic polling assertion at `framework.go:605`. That line alone does not identify the failing operation.
SCC admission is the leading hypothesis, not a confirmed diagnosis of the QE run.

Local checks of the two pinned images show:

- Their [default UID is 10000](evidence/image-default-users.json), without a runtime user override.
- HTTP and DNS work as UID 1000780000 with read-only roots, dropped capabilities, and no privilege escalation:
  [Konflux 0.23.4](evidence/konflux-0.23.4-arbitrary-uid-http-dns.log),
  [community devel](evidence/community-devel-arbitrary-uid-http-dns.log).

The accompanying image metadata identifies the exact tested images. Neither is proven to be the image used by the failing QE run.
These local checks do not exercise OpenShift admission. The available cluster credentials cannot create test pods.

## Remaining steps

1. Obtain the complete failure output, failing executable's dependency versions, and exact nettest image digest.
2. Check the failing namespace's ReplicaSet events for FailedCreate and UID 10000 rejection. If the failure instead concerns
   image pulling, scheduling, a crashing process, or DNS after successful setup, revisit this diagnosis.
3. Apply the Lighthouse patch, update and rebuild Subctl, and rerun the discovery tests on the target OpenShift clusters.
   Retain the selected SCC and admitted UID to verify the correction through the real controller path.

No PR is open. This branch is limited to the discovery issue; separate benchmark changes are outside its scope.
