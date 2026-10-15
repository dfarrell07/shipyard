# Adversarial review of the nettest correction

Three independent reviewers examined admission, container runtime behavior, and the QE evidence/release integration.
The audit changed the proposal: remove the fixed UID only on OpenShift, retaining UID 10000 on plain Kubernetes.
The earlier unconditional two-line deletion is insufficient for a compatible general release.

## Concrete compatibility defect found

Subctl accepts a newer executable against an older deployed Submariner and derives the default nettest image from the deployment.
The published community 0.23.2 image has no configured USER; executing `id -u` without an override returns 0.
The published 0.23.3 image configures USER 10000. See [registry metadata](previous-image-registry-users.json) and
[the legacy default-user check](legacy-default-runtime-uid.log).

Without SCC UID defaulting, the unconditional deletion leaves the older image at UID 0 while retaining `runAsNonRoot: true`.
That introduces a kubelet rejection in a version combination Subctl accepts. A documentation caveat or an image override used
only during testing would leave the default release behavior broken. The candidate therefore discovers the target cluster's API
groups and omits the UID only when `security.openshift.io` is advertised. Discovery errors fail explicitly; cluster A's result is
not reused for cluster B. It neither reads SCCs nor guesses an allocated UID from namespace annotations.

Sources: [Subctl version check](https://github.com/submariner-io/subctl/blob/4b44caa4/internal/restconfig/restconfig.go#L486),
[deployment-derived image version](https://github.com/submariner-io/subctl/blob/4b44caa4/pkg/cluster/info.go#L185),
[0.23.2 image source](https://github.com/submariner-io/shipyard/blob/v0.23.2/package/Dockerfile.nettest),
[0.23.3 image source](https://github.com/submariner-io/shipyard/blob/v0.23.3/package/Dockerfile.nettest),
[kubelet non-root validation](https://github.com/kubernetes/kubernetes/blob/v1.33.2/pkg/kubelet/kuberuntime/security_context_others.go).

## Independent checks

| Check | Result | Evidence |
| --- | --- | --- |
| OpenShift 4.20 mutation and validation | 32 expected outcomes reproduced, using shipped SCCs | [Independent rerun](admission-4.20-audit.log), [original check and reproduction](ADMISSION-CHECK.md) |
| OpenShift 4.19 mutation and validation | 24 expected outcomes passed, using shipped SCCs without v3 | [Results](admission-4.19-results.json), [log](admission-4.19-check.log), [source](admission-4.19-check.go.txt), [provenance](admission-4.19-provenance.json) |
| Namespace allocation counterexamples | 10 expected outcomes: normal allocation and supplemental-group fallback work; missing UID/MCS fails | [Results](admission-namespace-controls.json), [source](admission-namespace-check.go.txt), [provenance](admission-namespace-provenance.json) |
| Current-image runtime | 12 cases passed; exact helper commands, both pinned images, default UID/high UID/high UID with non-root group | [Verified results](adversarial-runtime-verified.json), [filtered output](adversarial-runtime-filtered.log), [clean reproducer](adversarial_runtime_audit.publishable.py) |
| Legacy 0.23.2 runtime | Four cases passed: both helper commands at UID 10000 and UID 1001530000 | [Results](legacy-runtime-results.json), [output](legacy-runtime.log), [reproducer](legacy_runtime_audit.py) |
| Final candidate's emitted templates | OpenShift outputs exactly match validated no-UID templates; Kubernetes outputs exactly match original explicit-UID templates | [Byte comparisons and hashes](candidate-template-comparison.json) |
| Default unit-runner test discovery | Actual shared runner selects `test/unit/framework`; it prunes `test/e2e` | [Enumeration log](unit-discovery.log), [recorded Go arguments](unit-discovery-invocations.jsonl) |
| Real builder regression with race detection | Mixed cluster order and repeated calls select the correct UID; HTTP 403/503 errors stop both builders before Deployment creation; no races reported | [Final race-enabled test log](candidate-race.log), [command and exact source hashes](candidate-provenance.json) |
| Candidate static checks | Full lint passes with zero issues on both changed packages; format check passes | [Lint output](candidate-lint.log), [commands and source hashes](candidate-provenance.json) |
| Subctl dependency integration | Full executable builds with the final candidate, version/help smoke passes, and both platform exports match the expected templates | [Source/binary hashes, module graph, linked symbols, and limits](subctl-build-provenance.json) |

The runtime checks verify zero effective capabilities, no-new-privileges, an active seccomp filter, read-only `/tmp` and `/app`,
UDP/TCP DNS answers, and 64 successful HTTP responses across the eight server cases. CPU/memory flags were configured;
cgroup values were not independently recorded. No writable scratch volume or relaxed container security setting was required.
These are rootless Podman/crun checks; their UID mappings do not qualify Kubernetes `hostUsers: false` or CRI-O behavior.
The current-image results record an irrelevant external DNS timeout in the initial runner and the final case's successful cleaned rerun.
The unit-discovery check uses a recording Go shim to verify package enumeration only; it does not execute the tests.
The Subctl build uses a local module replacement, not a published dependency update. Its VCS stamp is disabled because the installed
Go toolchain skipped the worktree's `.git` file and selected the enclosing repository. The provenance records the independently
checked source revision and candidate hash instead of attributing that misleading stamp to Subctl. The binary is retained locally.

The namespace controls deliberately include a zero-based UID allocation. Admission accepts UID 0 in that artificial case despite
`runAsNonRoot`, illustrating why admission success alone cannot establish runtime success. The proposed fix assumes ordinary,
valid nonzero namespace UID/MCS allocation and access to restricted-v2. It does not claim compatibility with arbitrary custom SCCs.

## What the logs establish

All 14 QE failures occur before DNS assertions, with zero helper Deployment pods. The local StatefulSet case already has a Running
Pod using the same configured nettest image in the same namespace and cluster before netshoot fails. The helper actually waits for
Pod phase Running; this is stronger evidence than a successful StatefulSet API create, but does not establish the selected SCC.

Passing direct connectivity Pods do not validate the ReplicaSet controller's SCC authorization. Likewise, a direct administrator
Pod create is insufficient as the positive control. The namespace's privileged Pod Security label does not bypass SCC admission.
Other admission denials, quota failures, controller failures, or label mutation could still produce zero matching pods. The archive
does not contain the ReplicaSet events needed to discriminate them from the reproduced UID rejection.

The earlier follow-ups corrected Shipyard YAML but missed Lighthouse's independent compiled builders. This is a coverage and
release-integration omission; it does not show that SCC UID defaulting itself failed. This audit also exposed the older-image
regression and the shared unit script's pruning of the entire `test/e2e` subtree. A regression test hidden there would not protect
the release, so the candidate's tests belong outside that subtree.

A disposable local Kubernetes cluster could not start because the host exhausted inotify resources before test workloads ran.
That is an environment failure, not a passing controller/kubelet check. The actual QE image digest, controller events, selected SCC,
and rebuilt-executable discovery rerun remain required by the [main plan](../README.md#remaining-steps).
