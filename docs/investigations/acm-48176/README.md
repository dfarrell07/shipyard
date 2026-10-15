# ACM-48176: nettest discovery failure

## Proposed fix

Choose `RunAsUser` for the target cluster in the two Lighthouse Deployment builders:

- `NewNginxDeployment`
- `NewNetShootDeploymentInNS`

If API discovery advertises `security.openshift.io`, omit the fixed UID and let SCC admission choose an allowed UID.
Otherwise retain UID 10000. Make this decision per cluster, including mixed cluster pairs; report discovery errors instead of
treating them as plain Kubernetes. Keep `runAsNonRoot`, read-only roots, dropped capabilities, no privilege escalation,
RuntimeDefault seccomp, disabled token mounting, and resource settings.

This corrects the earlier unconditional two-line proposal. The published nettest 0.23.2 image defaults to root, and a newer Subctl
can select it from an older deployment's version. Removing the UID on plain Kubernetes would make `runAsNonRoot` reject that image.
The [registry metadata](evidence/previous-image-registry-users.json) confirms the image default changes to UID 10000 in 0.23.3.
Retaining the explicit UID outside OpenShift preserves that working combination.

Use the [Lighthouse 0.23 candidate patch](evidence/lighthouse-scc.patch), update Subctl to consume the corrected Lighthouse version,
and rebuild it: these builders are compiled into its discovery tests. Updating the nettest image alone will not change them.

Shipyard 0.23 already corrected its independent helper YAML; the Lighthouse Go builders were missed by that follow-up.
This branch contains notes, evidence, and a candidate patch only. The separate devel YAML change is tracked in
[PR #2618](https://github.com/submariner-io/shipyard/pull/2618).

## Why this is the leading explanation

The Glasswing hardening added an explicit pod UID of 10000. OpenShift's range-constrained SCCs can reject that UID when it falls
outside the namespace allocation. Omitting it permits SCC defaulting. Keep the non-root default USER in current images;
the explicit UID on plain Kubernetes also supports older images that still default to root.

The attached logs show all 14 discovery failures occur during helper Deployment setup, before DNS checks: 10 time out with zero
`nginx-demo` pods and four with zero `netshoot` pods. The three StatefulSet cases first obtain Running StatefulSet pods, then fail at
netshoot setup. In the local case, a StatefulSet using the same configured image is already Running in the same namespace and cluster
where netshoot fails. This weakens image-wide and namespace-allocation explanations, although the selected SCC is unknown.
The fourth netshoot failure is the headless service without a selector. This matches the two builders containing the UID
override. The [case mapping](evidence/failure-paths.json) records the intended setup sequence; the ten nginx failures never reach
their later netshoot call. The [attachment analysis](evidence/attachment-analysis.json) records each observed failure.

Passing connectivity pods do not refute this explanation. Shipyard creates those Pods directly with the API caller's credentials;
Deployment pods are created later by the ReplicaSet controller. SCC authorization can differ for these requests, even in the same
namespace. A direct Pod test using an administrator account can therefore hide the defect; validation must use Deployments.

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

The [adversarial audit](evidence/EXPERT-AUDIT.md) adds OpenShift 4.19 checks, current/legacy image runtime checks, and the compatibility
finding that changed the proposed fix. It records the remaining controller and QE validation limits.

This supports the fix under default restricted-policy access. A v3-only cluster requires separate user-namespace qualification.
On plain Kubernetes, the revised candidate retains UID 10000 for older image compatibility. The OpenShift output still omits the
UID and is subject to the tested restricted-policy conditions. These checks do not establish the failing QE cluster's policy or
executable checksum.

## Evidence and limits

The [authenticated report snapshot](evidence/issue.json), inspected October 15, 2026, includes `e2e.zip` (attachment 1249936,
23,746 bytes) and two comments. The earlier anonymous API response hid these; its empty lists were insufficient evidence that
there were no attachments. The attachment was retrieved using the existing `acli` authentication.

The console and JUnit agree on all 14 zero-pod failures. Source paths identify Lighthouse, Shipyard, and Submariner v0.23.4.
The matching run filenames identify OpenShift 4.20 and 4.19; diagnose reports Kubernetes v1.32.13 for the diagnosed cluster.
Subctl reports `release-0.23`. The description says 0.23.4 while affected-version metadata says 0.23.2.

Zero matching pods points to a pod-creation or label-selection problem. The v0.23.4 helper waits
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

1. Record the failing executable checksum, exact nettest image digest, namespace UID/MCS allocations, and available SCCs.
   The attached output already identifies Lighthouse v0.23.4. Preserve the same image and configuration for the comparison.
2. Start event and ReplicaSet capture before reproducing either helper Deployment on the target clusters. Shipyard v0.23.4 deletes
   test namespaces after failure without collecting their events, despite its stale comment suggesting otherwise. Confirm FailedCreate
   and UID 10000 rejection; revisit the diagnosis if another creation failure is shown.
3. Apply the conditional UID correction to Lighthouse release-0.23, publish/pin the corrected dependency in Subctl, and rebuild
   the delivered executable. A local module replacement is only a build check. An unchanged executable cannot pick up this Go-source fix.
4. With the same image, verify both corrected Deployments produce Running pods under the expected SCC and allocated UID, then rerun
   discovery in both cluster directions. All 14 previously failing cases must execute and pass; record unrelated skips separately.
   Keep the emitted pod security settings and events as evidence. Admission-only success is insufficient to close the issue.

Subctl v0.23.4 accepts `--image-override 'submariner-nettest=<image>@sha256:<digest>'`; `--nettest-image` is a framework flag,
not a Subctl verify flag. `RELATED_IMAGE_submariner-nettest` takes precedence over that override. Record its value if present and
confirm the resulting Pod's image and imageID, so the comparison actually uses the intended digest.

No PR is open. This branch is limited to the discovery issue; separate benchmark changes are outside its scope.
