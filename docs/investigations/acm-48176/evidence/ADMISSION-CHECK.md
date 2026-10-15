# Direct check of the proposed UID correction

The [results](admission-results.json) and [test log](admission-check.log) cover 32 cases. They use the real OpenShift admission plugin,
including final validation. Namespace allocation, informer contents, and authorization decisions are local fixtures. No live cluster,
controller, scheduler, kubelet, or image process is involved.

For each of the two pod templates, the original and patched versions are checked with default restricted grants, additional anyuid
or privileged grants for the requester or service account, no grants, and v3-only access. Two extra controls set external hostUsers
false. The original templates fail the default policies on UID 10000 and missing user namespaces. The proposed removal admits them
under restricted-v2 with a namespace-assigned UID. A stock anyuid grant alone does not solve the original template's seccomp rejection.
Adding hostUsers false to the original is accepted by v3 in this plugin check, but its runtime support is a separate requirement.

## Reproduction

Exact revisions, input hashes, and manifest URLs are in [provenance](admission-provenance.json).

1. Download the Lighthouse v0.23.4 Go module. Copy [the exporter](export-templates.go.txt) to a temporary `.go` file. From that module,
   run it with `go run -mod=readonly /path/to/export.go /path/to/original-inputs`.
   It calls the real builders against a local HTTP fixture and captures their serialized templates. Its Running pod response only
   lets the builder's wait finish; it supplies no SCC decision.
2. Apply the conditional [Lighthouse candidate patch](lighthouse-scc.patch) to an isolated checkout of the same builder source and run
   the exporter there with a separate output directory. The exporter's default fixture advertises OpenShift. These exported objects
   must differ only in the two removed UID fields. Also run the exporter with its second argument `kubernetes`; those outputs must
   equal the original templates, preserving UID 10000 for older images on plain Kubernetes.
3. Download the pinned OpenShift apiserver-library-go source with its vendor directory. Copy
   [the check](admission-check.go.txt) to `pkg/securitycontextconstraints/sccadmission/acm48176_policy_test.go` in that isolated source.
   It reuses the upstream test helpers for the admission plugin and informer fixtures.
4. Fetch the four pinned SCC manifests listed in provenance. Convert each YAML object to JSON under its recorded input filename in
   the original-inputs directory. The checked policies are unmodified shipped definitions; namespace preallocation is performed by
   the real admission code. The stock restricted role bindings are also pinned as the basis for the grant fixtures.
5. Set ACM_PROOF_ORIGINAL and ACM_PROOF_FIXED to the two absolute input directories, and ACM_PROOF_RESULTS to a writable JSON file.
   Run `go test -mod=vendor -p 2 -v ./pkg/securitycontextconstraints/sccadmission -run '^TestACM48176ShippedPolicies$'`.
   Set GOTMPDIR to a directory with sufficient space if needed. This does not add dependencies or tests to Shipyard.

This proves the patch repairs this admission failure for the tested default-policy conditions. The attached QE timeout details now
identify the operation: both helper Deployments time out with zero matching pods. The archive still lacks the ReplicaSet events
needed to establish why pod creation failed. The initial expectation that an anyuid grant would be enough was
refuted by the real-policy experiment; the recorded check includes the corrected expectation rather than weakening the policy.
