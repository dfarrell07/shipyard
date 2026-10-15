# ACM-48176: second-pass root cause and review failures

This review follows the initial investigation, without treating its conclusions as established facts. The code defects are concrete;
the cause of the reported QE run remains a hypothesis until its missing diagnostics are obtained.

## What is actually established

- The report identifies a **Shipyard dependency** at v0.23.4. It does not establish the executable's name, its Lighthouse revision,
  CLI flags, OpenShift version, service-account grants, or nettest digest. The local Subctl/Lighthouse checkouts are candidate builds,
  not provenance for the failing binary. Use `go version -m` on that executable and retain the complete version output.
- All 14 reported failures were mapped to their candidate Lighthouse 0.23 entry functions in
  [failure-paths.json](evidence/failure-paths.json). Each function reaches a netshoot Deployment. Most also create an nginx Deployment.
  This is a common dependency, not proof that execution reached that call in the QE run.
- Three StatefulSet tests first create unhardened StatefulSet templates and later create a hardened netshoot Deployment. That
  distinction explains how the UID regression could affect tests named after StatefulSets.
- The headless-service-without-selector case creates no nginx Deployment in its entry function, yet still creates netshoot.
  Replacing the HTTP server would not remove this shared setup dependency.
- Subctl's default operation timeout is 240 seconds. Fourteen such waits account for 3360 of the reported 3504.408 seconds, leaving
  144.408 seconds for other work. This fits one setup timeout per failed spec, but the actual flags and per-spec durations are unknown.
  It does not distinguish SCC rejection from scheduling or image-pull timeouts.
- The Jira API was checked again during this review. It still returned no attachments, comments, or issue links.

## The admission mechanism, with pinned source

The [source provenance record](evidence/scc-source-provenance.json) pins the inspected OpenShift library's release-4.20 revision to
`f0d44ef6e53b49bd864c035752191a85b293af14`. This is a representative implementation, not identification of the QE server version.

1. [SCC authorization](https://github.com/openshift/apiserver-library-go/blob/f0d44ef6e53b49bd864c035752191a85b293af14/pkg/securitycontextconstraints/sccadmission/scc_authz_check.go)
   considers the pod's service account and the requester of the **pod** operation. A person submitting a Deployment does not thereby
   transfer their SCC permissions to the controller's later pod request. A directly submitted NetworkPod can therefore get a
   different result from the same UID inside a Deployment template. Neither controller failure nor direct-pod success is universal:
   the actual allowed SCCs and identities must be recorded.
2. [Provider generation](https://github.com/openshift/apiserver-library-go/blob/f0d44ef6e53b49bd864c035752191a85b293af14/pkg/securitycontextconstraints/sccmatching/provider.go#L151)
   defaults the effective UID only when it is absent. A pod-level UID is already an effective container UID; adding an image `USER`
   does not change it. The provider does not silently replace an explicitly invalid 10000 with an allowed UID.
3. [UID strategy](https://github.com/openshift/apiserver-library-go/blob/f0d44ef6e53b49bd864c035752191a85b293af14/pkg/securitycontextconstraints/user/mustrunasrange.go)
   generates the configured range minimum and validates a requested UID against both range bounds. Removing the explicit UID permits
   defaulting under this strategy; `runAsNonRoot` still expresses the workload's actual non-zero-identity requirement.
4. [Admission selection](https://github.com/openshift/apiserver-library-go/blob/f0d44ef6e53b49bd864c035752191a85b293af14/pkg/securitycontextconstraints/sccadmission/admission.go#L251)
   tries authorized providers until one validates. Error output listing restricted-v3 and restricted-v2 failures does not mean that
   both policies must be satisfied simultaneously. A required-SCC annotation or a restricted set of grants can change the result.
5. `automountServiceAccountToken: false` disables token projection. It does **not** remove the pod's service-account identity from SCC
   authorization. Likewise, the privileged PSA namespace label does not grant access to a privileged SCC.

The initial notes' shorthand that controller pods run under just the workload account's permissions was too broad. The precise
condition for rejection is that no SCC available to either checked identity permits the completed pod specification.

## Why the hostUsers error path was misleading

The earlier patch did more than miss a field-name lookup. Its input error path reflected a different Kubernetes representation.

- External core/v1 puts `hostUsers` directly in PodSpec.
- [Internal core types](https://github.com/kubernetes/kubernetes/blob/v1.33.2/pkg/apis/core/types.go#L3859) group host namespace settings
  inside PodSecurityContext, including HostUsers.
- [API conversion](https://github.com/kubernetes/kubernetes/blob/v1.33.2/pkg/apis/core/v1/conversion.go#L302) moves these fields between
  those locations. The inverse conversion fills the internal security context from the external pod specification.
- [SCC matching](https://github.com/openshift/apiserver-library-go/blob/f0d44ef6e53b49bd864c035752191a85b293af14/pkg/securitycontextconstraints/sccmatching/matcher.go#L114)
  passes a `spec.securityContext` field path to pod-context validation. The provider appends `hostUsers` when checking user namespaces.
  Thus the diagnostic path can describe the internal object rather than a valid external YAML path.

This source chain explains why following `.spec.securityContext.hostUsers` literally produced an invalid external manifest. The
[local strict-decoding check](evidence/hostusers-schema-check.log), using this Shipyard checkout's Kubernetes API libraries, rejects
that nesting and accepts `spec.hostUsers`. The [probe source](evidence/schema-check.go.txt) can be copied to a temporary `.go` file
and executed with `go run` from this checkout. Decoding acceptance proves neither SCC authorization nor runtime user-namespace support.
The UID correction should omit `hostUsers`; deliberately opting into user namespaces is a separate change with separate requirements.

## What the earlier agents and reviews demonstrably missed

The artifacts do not reveal every agent's reasoning or prove that every previous agent failed. Several earlier corrections were
valid, including retaining a numeric image USER and removing the invalid hostUsers field. The following are observable failures
of the combined plan, implementation, validation, and rollout.

1. **Consistency was substituted for a runtime contract.** The original audit knew that the framework required an arbitrary non-zero
   UID, yet prescribed 10000 in the YAML to match directly created test pods. The meaningful contract is non-root execution plus
   portable permissions. Matching numeric identities across differently authorized creation paths is unnecessary and can be invalid.
2. **A true statement about one layer was extended to another.** Range-defaulting SCCs can override an image's default user. They do
   not override an explicit out-of-range pod UID. The audit's reassurance about image USER was valid in that context but did not make
   the later pod-level override safe. Other SCC strategies can also preserve the image default, so “OpenShift ignores USER” is not a
   universal rule.
3. **The corrective search stopped at repository and file-format boundaries.** Shipyard YAML was fixed, but Lighthouse's independent
   Go builders retained the same setting. The older audit explicitly knew those builders existed. That knowledge did not become a
   complete follow-up inventory or a consumer release gate.
4. **A display path was treated as an external API schema.** The SCC diagnostic's internal HostUsers path was copied into YAML without
   strict decoding or checking external types and conversion. The follow-up corrected the syntax, but syntax was only one layer.
5. **The implementation dropped a planned runtime requirement.** The audit asked for writable `/tmp` for iperf3. The merged read-only
   root change omitted it. The shipped program opens buffer backing files on both endpoints; inspecting only shell commands or image
   builds cannot discover the resulting runtime error. With only the client fixed, the server failure even looks like a transport
   failure from the client, as the retained logs demonstrate.
6. **Successful tests covered different environments and entry points.** Lighthouse PR #2230 has successful E2E checks. Those do not
   establish OpenShift SCC admission. Shipyard's normal connectivity E2E does not instantiate throughput benchmark pods. Compilation,
   image scanning, and valid YAML establish still different properties. Their successful results should not be merged into one broad
   “safe” claim.
7. **Audit repetition was counted more strongly than experimental independence.** The local Glasswing report describes eleven audit
   rounds and extensive agent review, including later rounds concentrating on prose and citations. Those claims are not evidence of a
   restricted-SCC controller-pod run or an iperf3 exchange with writable temporary mounts explicitly disabled. Rechecking the same
   assumptions can converge on a shared omission. This is an inference about the process, not a claim about individual intent.
8. **Passing new tests were not connected to the actual runner.** This investigation initially added a test under
   `test/e2e/framework` and ran it directly. However, the shared unit runner prunes the `test/e2e` directory containing RunE2ETests,
   including its descendants. [The recorded selection analysis](evidence/unit-selection-before.json) shows the new test would be
   skipped by `make unit`. Direct success was real; automatic CI protection was not yet established. This is the same kind of coverage
   overstatement the investigation is meant to prevent, and it requires a build-target correction.

## How to keep the next correction falsifiable

Use separate acceptance conditions for each layer:

- **Source and artifact identity:** pin the failing executable's dependencies and the server/image versions. A local checkout, a
  release label, an image index digest, a selected platform digest, and a configuration digest identify different artifacts.
- **External API schema:** strictly decode rendered manifests and serialized Go output. Validate the external representation rather
  than translating an error string into YAML by eye.
- **Authorization and admission:** test the generated workload through the same controller and account path used by QE. A server-side
  dry-run of a Deployment does not create its ReplicaSet's pods. A bare pod dry-run submitted by an administrator can also pass under
  a more permissive SCC and hide the regression. Check the actual selected SCC and resulting UID on admitted pods.
- **Runtime behavior:** run both endpoints with read-only roots, no privilege escalation, and dropped capabilities. Disable Podman's
  implicit writable `/tmp` before claiming it represents a Kubernetes pod without scratch. Test RHEL and Fedora independently.
- **Storage and performance:** distinguish our tmpfs runtime reproduction from the disk-backed emptyDir patch. Verify the emitted
  mount, an actual Kubernetes exchange when credentials permit, and representative benchmark behavior. A 64 MiB disk emptyDir limit
  is not a synchronous filesystem quota; unlinked open files also complicate directory-scan storage accounting.
- **Consumer rollout:** separately carry Lighthouse's UID fix and Shipyard's throughput fix into Subctl dependency updates, a rebuilt
  executable, and the selected release streams. Image publication alone does not replace compiled Go builders.
- **CI execution:** show that the normal job actually selects each regression test. Keep negative controls: the pre-fix implementation
  must fail for the expected reason, and the corrected one must pass. A source-only fixture cannot substitute for a real SCC test.

For the QE rerun, retain complete output and capture controller events **before namespace cleanup**. The essential distinction is:
no child pod plus FailedCreate/UID rejection; an existing Pending pod with scheduling or pull errors; a crashing process; or successful
setup followed by a DNS mismatch. The summary's common polling assertion loses this distinction. Also retain namespace UID allocation,
service-account name, selected SCC, owner references, admitted pod UID, and the nettest imageID. Do not collect Secret contents.

## Remaining limits

The source review and strict decoding strengthen the causal explanation but do not replace the missing QE events. The current
credentials cannot create test pods in the accessible Konflux namespace. No actual OpenShift admission or two-cluster discovery rerun
is claimed. The patch fixes a reproducible benchmark defect and a concrete restricted-SCC portability defect; closing ACM-48176 still
requires tying that defect to the reported executable and run.
