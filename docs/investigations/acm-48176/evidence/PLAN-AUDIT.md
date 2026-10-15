# Second adversarial review of the implementation plan

Three independent reviewers challenged the implementation, release delivery, and QE acceptance procedure.
They found a real timeout defect in the previous candidate and several ways a misleading build or green test result could
leave this issue unresolved. The UID policy remains unchanged: SCC defaulting on OpenShift, UID 10000 on plain Kubernetes.

## Implementation: the previous discovery request was unbounded

The earlier candidate used `Discovery().ServerGroups()`. Discovery's nominal 32-second default does not bound this call in the
framework's actual clientset. `kubernetes.NewForConfig` first constructs a shared HTTP client from the original configuration,
whose timeout is zero, then passes it to discovery. Discovery's later default on its copied configuration does not replace
that supplied client's timeout. The REST request consequently has no deadline.

The [focused reproduction](discovery-adversary.go.txt) constructs the same clientset, serves `/api`, and stalls `/apis`.
It remained blocked beyond 33 seconds with HTTP timeout zero: [output](discovery-adversary.log),
[versions, hashes, and controls](discovery-timeout-finding.json).
This demonstrates a defect in the earlier proposal, not a new diagnosis of the original QE failures.

Pinned source paths establish the construction and request behavior:

- [Clientset shared-client construction](https://github.com/kubernetes/client-go/blob/v0.35.8/kubernetes/clientset.go#L500)
- [Discovery configuration with a supplied HTTP client](https://github.com/kubernetes/client-go/blob/v0.35.8/discovery/discovery_client.go#L765)
- [REST request timeout source](https://github.com/kubernetes/client-go/blob/v0.35.8/rest/request.go#L150)
- [Framework client creation](https://github.com/submariner-io/shipyard/blob/v0.23.4/test/e2e/framework/framework.go#L379)

The [replacement patch](lighthouse-scc.patch) makes an authenticated GET of `/apis`, requests legacy JSON, and decodes an
`APIGroupList`. A context deadline uses the existing framework operation timeout and is canceled on return. Zero budget fails
immediately. This bounds requests and client-side waits without changing a shared client's settings or abandoning a goroutine.
Legacy JSON also avoids depending on aggregated resource-discovery conversion when only API group names are needed.

The reviewer tested stale aggregated discovery groups as an alternative explanation. Their names remain present, including a
stale security group; that control did not expose an incorrect platform classification. HTTP/decode/transport errors still
stop the builder rather than choosing a fallback UID. Platform discovery is not proof of SCC authorization or selected policy.

The regression fixture now checks both builders' one-second request cancellation, server-observed cancellation, authentication,
zero Deployment POSTs, immediate failure for zero budget, and `/apis`/JSON negotiation. It also retains mixed-cluster UID and
HTTP 403/503 checks. Tests install and restore a fresh `gomega.Default`; changing the saved instance's failure handler would
otherwise leak a panic handler into subsequent tests.

## Delivery: prove which code the executable contains

The [release reviewer](delivery-audit.json) confirmed the compiled Lighthouse-to-Subctl path and found three plan gaps:

| Gap | Correction now required |
| --- | --- |
| Workspace precheck does not constrain later builds | Use `GOWORK=off` throughout; inspect the delivered executable |
| Local build does not qualify downstream delivery | Require Konflux prefetch/build success and exact artifact identity |
| Reused checkout can preserve stale checksums | Use a fresh checkout or remove binaries, archives, and checksum file |

The existing Makefile's missing module-file prerequisites remain relevant: a dependency-only edit can leave an old binary
up to date in a reused tree. Version text alone does not prove delivery. Unexpected module replacements must be rejected or
explicitly mapped to checked source/checksums when introduced by the hermetic toolchain.
No downstream build incompatibility was demonstrated; that build remains an unperformed acceptance gate.

## QE: a green summary is insufficient

The QE reviewer checked the actual attached JUnit and source execution paths. The [acceptance procedure](../QE-VALIDATION.md)
now requires ready LIST/WATCH capture on both contexts before testing, with owner UIDs, namespace allocations, selected SCC,
admitted UID, image identity, collector errors, and command statuses retained. A live collector PID or discovery HTTP 200 is
insufficient; verify the actual watch request is established. Capture must survive the suite's namespace cleanup.

Use two commands with reversed contexts, distinct reports, the same pinned image digest, and the overriding related-image
environment variable explicitly removed after recording it. Require both command exit codes to be zero.
The [case checker](check_discovery_junit.py) requires all 14 original names exactly once and passed in each report; it rejects
skips of those cases, substitutions, duplicates, reported retries, and additional reported failures/infrastructure errors.
Its [21 adversarial self-checks](junit-checker-selftest-results.json) pass, including rejection of the actual failing attachment.
The [self-check source](check_discovery_junit_selftest.py) constructs synthetic passing/mutated reports only as test inputs.
JUnit cannot independently prove context order, artifact identity, collector coverage, causality, or retries hidden outside it.

## Verification of the corrected candidate

| Check | Result and evidence |
| --- | --- |
| Exact base and patch | Applies to Lighthouse v0.23.4; [source/test/patch hashes](candidate-provenance.json) |
| Actual builder regression | Race-enabled tests pass, including bounded cancellation and zero budget: [log](candidate-race.log) |
| Static checks | Fresh lint reports zero issues; formatting diff empty: [lint](candidate-lint.log), [format](candidate-format.log) |
| Emitted pod templates | All four platform/builder outputs remain byte-identical to the admission-checked OpenShift and original Kubernetes references: [comparisons](candidate-template-comparison.json) |
| Fresh Subctl integration | Build, module metadata, version/help smoke, and both-platform exports pass: [provenance](subctl-bounded-build-provenance.json) |

The unchanged template bytes retain the earlier 66 admission outcomes and 16 local runtime cases as relevant evidence.
The new production source hash is `e2e83bccd75aa722da7814248c5451d44be5aed6cfdce736c591b242fbb1e7aa`.
The new local Subctl binary hash is `433d9872da3cf47c4f25eb0b057b2a70bf6561150b2be3113df78a216db85386`.
That build captured an earlier test-only revision; the provenance distinguishes it from the final race/lint-tested test source.
Tests are not linked into the delivered executable, and the production source did not change between these checks.

The full Lighthouse unit gate, immutable published dependency pin, downstream build qualification, actual original FailedCreate
cause, controller-created Running pods, and delivered-artifact QE reruns remain required. The archive still lacks the admission
events needed to confirm the original cause. These audits support the implementation path; they do not establish issue closure.
