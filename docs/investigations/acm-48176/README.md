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

The attached logs show all 14 discovery failures occur during helper Deployment setup, before DNS checks: 10 time out with zero
`nginx-demo` pods and four with zero `netshoot` pods. The three StatefulSet cases complete StatefulSet setup, then fail at netshoot
setup. The fourth netshoot failure is the headless service without a selector. This matches the two builders containing the UID
override. The [case mapping](evidence/failure-paths.json) records the intended setup sequence; the ten nginx failures never reach
their later netshoot call. The [attachment analysis](evidence/attachment-analysis.json) records each observed failure.

The earlier Shipyard follow-up briefly added `securityContext.hostUsers`, then removed it before v0.23.4. That is an invalid
external API location. The SCC error path reflects internal Kubernetes types; API conversion places the external field at
`spec.hostUsers`. This UID fix does not need a user-namespace setting.

Sources: [SCC UID defaulting and validation](https://github.com/openshift/apiserver-library-go/blob/f0d44ef6e53b49bd864c035752191a85b293af14/pkg/securitycontextconstraints/user/mustrunasrange.go),
[internal/external API conversion](https://github.com/kubernetes/kubernetes/blob/v1.33.2/pkg/apis/core/v1/conversion.go#L302).

## Direct admission check

The [32-case offline check](evidence/ADMISSION-CHECK.md) executes pinned OpenShift 4.20 admission mutation and validation code against
exports from Lighthouse v0.23.4 and the patched builders. With pinned shipped restricted policies and a namespace UID-range fixture,
both original templates are rejected; both patched templates select `restricted-v2` and receive UID 1001530000. Other hardening is
preserved. Privileged-access controls admit the original; no-grant and v3-only controls remain rejected.

This supports the fix under default restricted-policy access. A v3-only cluster requires separate user-namespace qualification.
On plain Kubernetes, omitting the UID also relies on the image's non-root default; the two tested images meet that requirement,
but older/custom root-default images may not. These checks do not establish the failing QE cluster's policy or executable checksum.

## Evidence and limits

The [authenticated report snapshot](evidence/issue.json), inspected October 15, 2026, includes `e2e.zip` (attachment 1249936,
23,746 bytes) and two comments. The earlier anonymous API response hid these; its empty lists were insufficient evidence that
there were no attachments. The attachment was retrieved using the existing `acli` authentication.

The console and JUnit agree on all 14 zero-pod failures. Source paths identify Lighthouse, Shipyard, and Submariner v0.23.4.
The matching run filenames identify OpenShift 4.20 and 4.19; diagnose reports Kubernetes v1.32.13 for the diagnosed cluster.
Subctl reports `release-0.23`. The description says 0.23.4 while affected-version metadata says 0.23.2.

Zero pods narrows the failure to pod creation rather than a reported running-container or DNS error. The v0.23.4 helper waits
list all matching pods before testing their phase: an image-pull or scheduling failure would normally leave an existing Pending
pod and report its phase, rather than a zero count. SCC rejection fits this observation, but other admission failures or
controller failures can also prevent pod creation. The archive has no ReplicaSet events, SCC selection, namespace UID allocation,
exact nettest image digest, or executable checksum. UID rejection remains the leading explanation, not a confirmed QE admission event.

The archive also contains a separate AWS 4.21 attempt that panics before specs; its diagnostics report Submariner missing.
That setup failure is separate from the 14 discovery failures. Full raw logs remain local; the branch records selected diagnostic
findings and artifact hashes without copying network addresses or restricted comment bodies.

Local checks of the two pinned images show:

- Their [default UID is 10000](evidence/image-default-users.json), without a runtime user override.
- HTTP and DNS work as UID 1000780000 with read-only roots, dropped capabilities, and no privilege escalation:
  [Konflux 0.23.4](evidence/konflux-0.23.4-arbitrary-uid-http-dns.log),
  [community devel](evidence/community-devel-arbitrary-uid-http-dns.log).

The accompanying image metadata identifies the exact tested images. Neither is proven to be the image used by the failing QE run.
These local checks do not exercise OpenShift admission. The available cluster credentials cannot create test pods.

## Remaining steps

1. Obtain the exact nettest image digest and executable checksum; the attached output already identifies Lighthouse v0.23.4.
2. Capture the failing Deployment and ReplicaSet status/events before test namespace cleanup. Confirm FailedCreate and UID 10000
   rejection, and record the namespace UID allocation and available SCCs. Revisit the diagnosis if another creation failure is shown.
3. Apply the Lighthouse patch, update and rebuild Subctl, and rerun the discovery tests on the target OpenShift clusters.
   Retain the selected SCC and admitted UID to verify the correction through the real controller path.

No PR is open. This branch is limited to the discovery issue; separate benchmark changes are outside its scope.
