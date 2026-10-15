# Controller and QE acceptance procedure

Use this after the corrected Lighthouse dependency is in the delivered Subctl artifact. Repeat the original/fixed comparison
with fresh output directories, unchanged cluster configuration/service-account grants, and the same actual QE nettest digest.
The digest used in the earlier local container experiments is not established as the failing QE image.

The **original baseline** is an expected negative control: retain its nonzero exit statuses, original case failures, and
controller events. The checker should reject those reports. The zero-exit, all-cases-passed requirements below apply to the
**corrected delivered artifact**. Keep their output directories and artifact identities separate.

## Capture before starting tests

On **each** context, require successful initial LISTs and established WATCHes for these resources:

| Resource | Scope |
| --- | --- |
| `namespaces` | Label selector `e2e-framework=discovery` |
| `deployments.apps`, `replicasets.apps`, `pods`, `events` | Each resource separately, across namespaces |

Use the read-only [collector](evidence/capture_discovery.go.txt), built against the inspected client-go v0.35.8 graph.
It takes an initial complete LIST, then resumes watch connections from their last resourceVersion. A normal EOF reconnects;
HTTP or streamed 410 terminates without relisting, because relisting could hide missed events.
The [collector checks](evidence/capture-discovery-provenance.json) exercise replay after EOF and terminal/error controls.

Set `LOCAL_CAPTURE` to a fresh absolute directory outside the notes checkout. From the investigation directory, copy the
collector and its tests into a temporary source directory. Then build/test from the inspected Lighthouse or Subctl checkout
whose Go module selects the recorded client-go version:

```bash
capture_src=$(mktemp -d)
cp evidence/capture_discovery.go.txt "$capture_src/capture_discovery.go"
cp evidence/capture_discovery_test.go.txt "$capture_src/capture_discovery_test.go"
cd "$INSPECTED_MODULE_CHECKOUT"
GOWORK=off go test -mod=readonly -race "$capture_src/capture_discovery.go" "$capture_src/capture_discovery_test.go"
GOWORK=off go build -mod=readonly -o "$LOCAL_CAPTURE/capture-discovery" "$capture_src/capture_discovery.go"
```

Record that collector binary's checksum and module metadata. Start one process per resource/context, preserving each PID:

```bash
"$LOCAL_CAPTURE/capture-discovery" --context "$CTX_A" --resource pods \
  > "$LOCAL_CAPTURE/a-pods.jsonstream" 2> "$LOCAL_CAPTURE/a-pods.stderr" &
a_pods_pid=$!
```

Repeat for all five resources and both contexts. The namespace collector automatically applies `e2e-framework=discovery`;
the other four resources use all namespaces. `--kubeconfig` is optional; otherwise normal kubeconfig loading applies.
Keep stdout and stderr local: objects, API errors, and client diagnostics can contain private metadata.
The JSON output is a stream containing the initial LIST and subsequent object-change events, not one standalone document.

Before testing, require `list_complete` and `watch_established` records for all ten processes, with a finite startup deadline.
The latter is logged only after the actual watch request is accepted. Preserve readiness records and reconnect resource versions.
Resource versions are opaque tokens; do not require consecutive numeric values.
Every collector must remain alive through the runs. Only after tests and final evidence collection finish, send SIGTERM and
record each process's exit status and `operator_stop` record. A premature exit is invalid even when its status is zero.
Investigate every request/output error; an unexplained gap or terminal 410 invalidates capture. Do not restart the whole
collector in a shell loop, because its fresh LIST would hide a gap. Reproduce with fresh capture if continuity was lost.

A single `kubectl get --watch` connection is insufficient for the original baseline, which lasts about 58 minutes.
A [local reproduction](evidence/kubectl-watch-close-results.json) shows kubectl exiting zero on normal watch closure without
reconnecting. A live PID or successful initial HTTP response therefore does not establish coverage of the full run.

Preserve namespace UID/MCS allocations and the Deployment → ReplicaSet → Pod owner UID chain, service-account identity,
`openshift.io/scc`, pod/container security contexts, configured image, and imageID. Confirm corrected controller-created pods
use the expected restricted SCC and a nonzero UID inside the namespace range; an unexpected privileged SCC is not this positive
control. Where feasible, record `id -u` inside the running helper as well. The automated suite deletes namespaces afterward.

For the first causal proof, retained disposable namespaces and **real Deployments** from the original/fixed builders are useful:
collect original FailedCreate events and corrected Running pod metadata before manually cleaning those namespaces up.
Keep their default service accounts/grants unchanged. Direct administrator-created Pods can hide the UID admission failure.

## Run both directions and preserve statuses

Set `SUBCTL` to the absolute path of the inspected delivered executable; record its checksum and module metadata.
For a container invocation, preserve the equivalent immutable image/architecture and embedded binary identity.
Set `CTX_A`, `CTX_B`, `OUT`, and `NETTEST_DIGEST_REF` explicitly. `OUT` must be a fresh directory for this artifact/run;
`NETTEST_DIGEST_REF` must be the selected common `registry/repository@sha256:...` reference.
Record any existing `RELATED_IMAGE_submariner-nettest` value, then remove it for both commands so it cannot defeat the pin.

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

Preserve the exact commands, context mapping, artifact identity, digest/environment, and collector readiness/exit records.
Require both Subctl exit codes to be zero. Do not replace those statuses with a successful `tee`, checksum, or parser exit.
Swapping contexts matters: the tests use fixed ClusterA/ClusterB roles, and Subctl derives its shared image from cluster A.
Confirm the emitted image reference and running imageID in each direction instead of assuming the same CLI text guarantees it.

## Check the original cases by identity

From this investigation directory, run:

```bash
python3 evidence/check_discovery_junit.py \
  --expected evidence/attachment-analysis.json \
  --reports "$OUT/discovery-a-b.xml" "$OUT/discovery-b-a.xml"
```

Require exit zero **as well as** both successful Subctl statuses. The checker requires every one of the 14 original case names
exactly once with status `passed`, without failure/error/skip children, in each report. It rejects additional reported failures,
suite infrastructure errors, and reported retries/flakes; unrelated original skips are counted separately.
This prevents a green total from hiding skipped/replaced cases, including ordinary discovery skipped under a changed clusterset-IP
configuration. Do not enable wrapper retries or accept a flaky rerun as a new pass.

Require genuine execution metadata: the pinned producer must report `DryRun=false`, `SuiteSucceeded=true`, and no programmatic
focus or declared suite retries. Its JUnit does not contain per-case attempt counts, so audit the exact landed discovery code
and wrappers for per-spec retry decorators, or retain separate attempt-count evidence. A final passed status cannot prove this.

The checker cannot establish opposite context order, executable identity, collector coverage, causality, or retries hidden outside
JUnit. Preserve those records separately. Its self-checks reject the actual attached failing report and adversarial missing,
duplicate, skipped, substituted, failed, and malformed reports; synthetic passing fixtures are test inputs, not QE evidence.

Do not mark ACM-48176 fixed until the original controller failure is understood and the corrected delivered artifact satisfies
the controller/SCC/UID, image identity, command status, exact-case, and capture requirements above.
