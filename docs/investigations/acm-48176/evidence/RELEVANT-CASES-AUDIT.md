# Relevant-case audit of the nettest plan

Three reviewers independently challenged the candidate again after commit `ae55fe15`.
They found two implementation/test defects and two acceptance weaknesses, reproduced them, and corrected the candidate or
procedure. They found no further UID-policy blocker in the inspected ordinary OpenShift/Kubernetes configurations.
This supports the implementation path; it cannot establish that all later DNS assertions pass on the failing clusters.

## Corrections from concrete counterexamples

| Finding | Correction and evidence |
| --- | --- |
| HTTP 200 `{}` or `null` silently selected UID 10000 | Decode independently and require APIGroupList; both builders reject invalid replies before POST: [before/after](classifier-audit-results.json), [reproducer](classifier-adversary.go.txt) |
| Restoring TestContext's pointer did not restore mutated fields | Mutate a separate struct copy; shuffled three-repeat race suite passes: [source and hashes](candidate-provenance.json), [log](candidate-race.log) |
| The JUnit checker accepted dry-run or unsuccessful-suite metadata | Require genuine successful execution metadata; 39 adversarial checks pass: [results](junit-checker-selftest-results.json), [actual pinned reporter fixtures](junit-metadata-audit-results.json) |
| An established kubectl watch could close successfully before the run ended | Use a resumable collector with terminal expiry handling: [reproduction](kubectl-watch-close-results.json), [collector proof](capture-discovery-provenance.json) |

The invalid-response finding is limited: normal Kubernetes/OpenShift servers were not shown to emit these replies.
Typed Status/PodList responses already failed in the prior candidate; the broader source-only suspicion was disproved by tests.
The revised helper also rejects missing type metadata while permitting a correctly typed empty APIGroupList.

The three-client regression now checks each builder's discovery counter after every call. This detects a mistaken ClusterB
lookup for ClusterC even when both advertise OpenShift. Authentication, URL-prefix preservation, HTTP errors, canceled/zero
budgets, valid responses, and unchanged hardening remain covered. The [current patch](lighthouse-scc.patch) applies to exact
Lighthouse v0.23.4; lint and formatting pass. Both platforms' emitted pod templates still match the earlier references byte for
byte, so the admission/runtime evidence remains applicable.

The actual shared unit script subsequently passed on the complete exact-base Git worktree, including nested modules:
six packages with race detection, 291 Ginkgo specs, and the actual builder regression package. This replaces enumeration-only
confidence with a real run of the test payload: [summary](full-unit-summary.log), [provenance](full-unit-provenance.json).
It used host Go rather than the landing CI/container wrapper; that distinction and the intentionally excluded e2e tests remain explicit.

Discovery requires authenticated GET `/apis`; the upstream default
[role](https://github.com/kubernetes/kubernetes/blob/v1.32.13/plugin/pkg/auth/authorizer/rbac/bootstrappolicy/policy.go#L202) and
[binding](https://github.com/kubernetes/kubernetes/blob/v1.32.13/plugin/pkg/auth/authorizer/rbac/bootstrappolicy/policy.go#L591)
provide it. Customized discovery authorization must be checked explicitly; HTTP 403 is already a negative regression case.

The deadline claim is deliberately narrower now: an actual two-second exec credential program exceeded a one-second context
before returning. Existing client-go authentication does not cancel arbitrary programs. The helper still prevents Deployment
creation afterward, but does not promise to terminate arbitrary credential hooks. Repairing that client-wide behavior is outside
the nettest correction.

## Coverage and its practical limits

| Relevant case | Established | Still required |
| --- | --- | --- |
| OpenShift 4.19/4.20 default policy | 66 admission/allocation outcomes | Actual controller/SCC/Running-pod proof |
| Kubernetes, old/current image | UID 10000 and original templates preserved | Controller/kubelet regression |
| Mixed and third contexts | A/B/C requests and UID selection checked | Existing three-cluster e2e |
| Legacy image, arbitrary UID/GID | Both helpers work without root group | Target CRI-O/SELinux runtime |
| Image architectures | Consistent users across inspected platforms | Applicable native runtimes |
| Proxy/discovery failure | Prefix preserved; invalid replies fail | Target authentication/proxy path |
| DNS feature variants | All helper callsites inspected | Applicable existing feature e2e matrix |
| Artifact delivery | Fresh build, module/CLI/export checks pass | Published pin and downstream artifact |

The new [image audit](release-image-platform-audit.json) inspects every child of community 0.23.2/0.23.3/0.23.4 and the pinned
downstream 0.23.4 index. Both community architectures default to root in 0.23.2 and UID 10000 in current images; all four downstream
architectures use UID 10000. Registry metadata does not execute foreign-architecture binaries.
The [two additional legacy runtime cases](legacy-no-root-group-results.json), [source](legacy_no_root_group_audit.py), and
[server output](legacy-runtime-community-0.23.2-no-root-group-nginx-demo.log) close the earlier GID-0-only legacy coverage gap.
There are now 18 local runtime cases and 72 HTTP responses across all retained runtime experiments.

Subctl's version check accepts older deployments; that fact is not an official support-policy claim for every older release.
Likewise, platform discovery does not prove SCC admission exists or which policy wins. Custom higher-priority SCCs, v3-only
policies requiring user namespaces, absent grants, invalid namespace allocation, or arbitrary custom images need their own
qualification. Some are already deliberate negative controls; this fix does not claim to make them pass.
The framework deliberately creates privileged-PSA namespaces and disables SCC label synchronization. Preserve those labels;
SCC admission proof does not qualify the entire discovery suite under restricted PSA.

Before landing, use the applicable existing
[Lighthouse e2e workflow](https://github.com/submariner-io/lighthouse/blob/39802358763f6edf93850d1b863fec74aca64d08/.github/workflows/e2e.yml)
and [three-cluster configuration](https://github.com/submariner-io/lighthouse/blob/39802358763f6edf93850d1b863fec74aca64d08/.shipyard.e2e.yml).
Keep applicable IP-family/globalnet and clusterset-IP coverage separate from the original-case acceptance run; feature switches
can intentionally skip the ordinary discovery cases. The archive's 4.21 attempt failed before specs and is a separate setup issue.

## Preventing false closure

The [current Subctl proof](subctl-validated-build-provenance.json) selects the new production source; earlier build records are
historical. It still uses a local replacement and does not qualify strict-FIPS Konflux delivery or a published module pin.

The pinned Ginkgo reporter omits per-spec attempt counts. Both old and corrected checkers accept a synthetic decorator-retry
report because that information is absent. Audit the exact landed specs, Ginkgo configuration, and invocation wrappers for
retries/dry runs, or retain verified attempt records. Current inspected discovery sources have no retry decorators; current
Subctl exposes no dry-run flag. The reproduced checker weaknesses are acceptance-hardening findings, not a demonstrated bypass
of the documented current commands. See [pinned reporter reproduction](ginkgo-junit-semantic-audit.go.txt).

The read-only collector's seven race-enabled function checks and five resource-path CLI checks pass. It resumes from the last
opaque resourceVersion after EOF and preserves selectors. Expired versions fail explicitly, including initial HTTP 410, which
requires a guard beyond stock RetryWatcher behavior. It never silently relists to hide a gap. This is a local fixture proof;
the real ten-process capture still needs readiness, lifetime, output, and terminal-status verification.

The [QE procedure](../QE-VALIDATION.md) distinguishes the expected failing original baseline from the required passing corrected
runs. Closure requires original controller-cause evidence, unchanged image/configuration, the corrected delivered artifact,
expected SCC/UID and Running helpers, continuous capture, successful command exits, and all 14 original cases passed in both
directions. Offline success cannot prove later cross-cluster DNS behavior or exclude an additional fault hidden behind setup.
