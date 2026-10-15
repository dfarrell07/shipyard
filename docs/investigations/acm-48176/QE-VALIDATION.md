# Controller and QE acceptance procedure

Run the original Subctl artifact first, then the corrected artifact. Repeat steps 1–3 with fresh output and capture directories for each.
Use the same QE nettest digest, cluster configuration, namespace labels, and service-account grants for both runs.
The original run must reproduce the failure and retain causal evidence; its nonzero statuses and checker rejection are expected.
The successful-exit and all-cases-passed requirements below apply to the corrected artifact.

## 1. Prepare the run and capture

Set `SUBCTL` to the absolute path of the inspected executable; retain its checksum and module metadata. For containers, retain
image/platform and embedded executable identities. Set `CTX_A`, `CTX_B`, and `NETTEST_DIGEST_REF` to the target contexts and common
`registry/repository@sha256:...` reference. The earlier local image experiments do not establish the failing QE digest.
Create fresh absolute directories `OUT` and `LOCAL_CAPTURE` outside the checkout. Record any existing
`RELATED_IMAGE_submariner-nettest` value; the commands below remove it because it overrides the CLI image pin.

Start collection **before** reproducing either artifact: the suite deletes its namespaces, and Subctl has no preservation flag.
On each context, collect these resources:

| Resource | Scope |
| --- | --- |
| `namespaces` | Label selector `e2e-framework=discovery` |
| `deployments.apps`, `replicasets.apps`, `pods`, `events` | One collector per resource, across namespaces |

Use the [read-only collector](evidence/capture_discovery.go.txt), tested against client-go v0.35.8.
It resumes from the last resourceVersion after EOF and fails on expired versions without a gap-hiding relist.
A single kubectl watch can [exit zero on stream closure](evidence/kubectl-watch-close-results.json).

From this investigation directory, copy the collector and tests into a temporary directory. Set `INSPECTED_MODULE_CHECKOUT` to
the inspected Lighthouse or Subctl checkout selecting that client-go version, then build/test there:

```bash
capture_src=$(mktemp -d)
cp evidence/capture_discovery.go.txt "$capture_src/capture_discovery.go"
cp evidence/capture_discovery_test.go.txt "$capture_src/capture_discovery_test.go"
cd "$INSPECTED_MODULE_CHECKOUT"
GOWORK=off go test -mod=readonly -race "$capture_src/capture_discovery.go" "$capture_src/capture_discovery_test.go"
GOWORK=off go build -mod=readonly -o "$LOCAL_CAPTURE/capture-discovery" "$capture_src/capture_discovery.go"
```

Retain the collector checksum/module metadata. Start each process and save its PID, for example:

```bash
"$LOCAL_CAPTURE/capture-discovery" --context "$CTX_A" --resource pods \
  > "$LOCAL_CAPTURE/a-pods.jsonstream" 2> "$LOCAL_CAPTURE/a-pods.stderr" &
a_pods_pid=$!
```

Repeat for all five resources and both contexts; add five collectors for ClusterC when qualifying a third-context extension.
The namespace selector is automatic. `--kubeconfig` is optional; normal loading otherwise applies.
Keep output local because it contains private metadata. Stdout is a JSON stream of the initial LIST and object-change events.

Require `list_complete` and `watch_established` records for every process within a finite startup deadline before testing.
Preserve reconnect records and opaque resourceVersions. Keep all collectors alive until testing and final collection finish;
then send SIGTERM and require exit zero with an `operator_stop` record. Retain statuses and reject premature exits, output
failures, expired versions, and unexplained gaps; investigate request errors. Restarting the whole collector would hide a gap
behind a fresh LIST.
See [collector checks and provenance](evidence/capture-discovery-provenance.json).

## 2. Run discovery in both directions

For each artifact, run these commands with its own `SUBCTL`, `OUT`, and active capture:

```bash
if env -u 'RELATED_IMAGE_submariner-nettest' "$SUBCTL" verify \
  --context "$CTX_A" --tocontext "$CTX_B" --only service-discovery \
  --image-override "submariner-nettest=$NETTEST_DIGEST_REF" \
  --junit-report "$OUT/discovery-a-b.xml" > "$OUT/discovery-a-b.log" 2>&1; then
  a_to_b_status=0
else
  a_to_b_status=$?
fi
printf '%s\n' "$a_to_b_status" > "$OUT/discovery-a-b.exit"

if env -u 'RELATED_IMAGE_submariner-nettest' "$SUBCTL" verify \
  --context "$CTX_B" --tocontext "$CTX_A" --only service-discovery \
  --image-override "submariner-nettest=$NETTEST_DIGEST_REF" \
  --junit-report "$OUT/discovery-b-a.xml" > "$OUT/discovery-b-a.log" 2>&1; then
  b_to_a_status=0
else
  b_to_a_status=$?
fi
printf '%s\n' "$b_to_a_status" > "$OUT/discovery-b-a.exit"
```

Preserve exact commands, context mapping, artifact identity, image/environment, statuses, and collector records.
The tests use fixed ClusterA/ClusterB roles, and Subctl derives its shared image from cluster A. Check the emitted image and
running imageID in each direction. Disable wrapper retries and audit landed specs/Ginkgo configuration for retry or dry-run modes.

## 3. Inspect the controller evidence

Preserve the Deployment → ReplicaSet → Pod owner UIDs, service-account identity, namespace UID/MCS allocations and labels,
selected `openshift.io/scc`, security contexts, configured image, and running imageID. Use real Deployments: directly creating
Pods as an administrator can hide the controller's SCC denial.

The original FailedCreate events must explain why helper pods are absent. UID 10000 outside the namespace range confirms this
proposal; another cause requires revisiting the diagnosis. Corrected helpers must reach Running under the expected restricted
SCC with a nonzero UID in range. Where feasible, also record `id -u`. An unexpected privileged SCC is insufficient.
Retained disposable namespaces with the original/fixed Deployments can establish this comparison before suite cleanup.

## 4. Accept the corrected artifact

Require both Subctl exit statuses to be zero. From this investigation directory, run:

```bash
python3 evidence/check_discovery_junit.py \
  --expected evidence/attachment-analysis.json \
  --reports "$OUT/discovery-a-b.xml" "$OUT/discovery-b-a.xml"
```

Require checker exit zero too: every original case must occur exactly once and pass in each report, with no substituted/skipped
cases, additional failures, or invalid execution metadata. Unrelated skips are recorded separately.
The pinned JUnit format omits per-case attempt counts; audit source/wrappers for per-spec retries or retain independent attempt
records. The checker cannot establish artifact identity, context order, capture coverage, or causality.

Close ACM-48176 only when the original controller failure is understood, the corrected delivered artifact produces Running
helpers under the expected SCC/UID, and all 14 original cases pass in both directions with continuous evidence capture.
