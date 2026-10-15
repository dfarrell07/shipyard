# Controller and QE acceptance procedure

Use this after the corrected Lighthouse dependency is in the delivered Subctl artifact. Repeat the original/fixed comparison
with fresh output directories, unchanged cluster configuration/service-account grants, and the same actual QE nettest digest.
The digest used in the earlier local container experiments is not established as the failing QE image.

## Capture before starting tests

On **each** context, require successful initial LISTs and established WATCHes for these resources:

| Resource | Scope |
| --- | --- |
| `namespaces` | Label selector `e2e-framework=discovery` |
| `deployments.apps`, `replicasets.apps`, `pods`, `events` | Each resource separately, across namespaces |

Confirm access by actually listing and opening the watches. An authorization precheck alone is insufficient.
For example, start the Pod collector as a background process and preserve its PID:

```bash
kubectl --context "$CTX_A" -v=6 get pods -A --watch --output-watch-events -o json \
  > "$LOCAL_CAPTURE/a-pods.jsonstream" 2> "$LOCAL_CAPTURE/a-pods.stderr" &
a_pods_pid=$!
```

Repeat for each resource and context. The namespace command uses
`get namespaces -l e2e-framework=discovery --watch --output-watch-events -o json` without `-A`.
Keep output and stderr in a local directory outside the notes checkout; API URLs and workload metadata can be private.
The JSON output is a stream, not necessarily one standalone JSON document.

Before proceeding, verify the initial LIST succeeded and stderr shows HTTP 200 for the **actual `watch=true` request** for
each resource/context. A discovery request's 200 response, an initial LIST's 200 response, or a live PID is not watch readiness.
Use a finite startup deadline and stop if any collector has not established its watch. The LIST resource version followed by
the WATCH preserves events occurring between the two requests. Keep collectors running until both directional runs finish;
record exits/errors and investigate unexplained gaps or loss of resource-version continuity before accepting capture coverage.

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

The checker cannot establish opposite context order, executable identity, collector coverage, causality, or retries hidden outside
JUnit. Preserve those records separately. Its self-checks reject the actual attached failing report and adversarial missing,
duplicate, skipped, substituted, failed, and malformed reports; synthetic passing fixtures are test inputs, not QE evidence.

Do not mark ACM-48176 fixed until the original controller failure is understood and the corrected delivered artifact satisfies
the controller/SCC/UID, image identity, command status, exact-case, and capture requirements above.
