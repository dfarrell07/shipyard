# Controller and QE acceptance procedure

Run the steps below on both failing contexts. Step 1 establishes the controller failure in minutes without running the suite.
Step 2 optionally confirms it with the unchanged 0.23.4 Subctl. Steps 3–5 qualify the corrected artifact.
Use the same QE nettest digest, cluster configuration, and service-account grants throughout, except for the temporary grant in step 2.

## 0. Prepare

Set `CTX_A` and `CTX_B` to the target contexts and `NETTEST_DIGEST_REF` to the common `registry/repository@sha256:...`
reference QE uses. The earlier local image experiments do not establish the failing QE digest. Run commands from this investigation
directory. Create a fresh absolute directory `OUT` outside the checkout for each Subctl artifact. Record any existing
`RELATED_IMAGE_submariner-nettest` value; the Subctl commands below remove it because it overrides the CLI image pin.

## 1. Reproduce the controller failure in scratch namespaces

The [original](evidence/repro/original) manifests are the exact Deployments the Lighthouse v0.23.4 builders create. The
[corrected](evidence/repro/corrected) manifests omit only the pod `runAsUser`, which is what the fixed builders emit on OpenShift.
Both use the labels the e2e framework puts on its namespaces. For each context:

```bash
ctx=$CTX_A   # repeat with CTX_B
for variant in original corrected; do
  oc --context "$ctx" create namespace "acm-48176-$variant"
  oc --context "$ctx" label namespace "acm-48176-$variant" \
    pod-security.kubernetes.io/enforce=privileged security.openshift.io/scc.podSecurityLabelSync=false --overwrite
  for helper in nginx-demo netshoot; do
    sed "s|NETTEST_IMAGE|$NETTEST_DIGEST_REF|" "evidence/repro/$variant/$helper.json" |
      oc --context "$ctx" -n "acm-48176-$variant" create -f -
  done
done
oc --context "$ctx" -n acm-48176-corrected wait deployment --all --for=condition=Available --timeout=240s
```

Check the original variant. It should have no Pods, and each ReplicaSet should report the admission rejection:

```bash
oc --context "$ctx" -n acm-48176-original get pods
oc --context "$ctx" -n acm-48176-original get rs -o \
  jsonpath='{range .items[*]}{.metadata.name}{": "}{.status.conditions[?(@.type=="ReplicaFailure")].message}{"\n"}{end}'
oc --context "$ctx" -n acm-48176-original get events --field-selector reason=FailedCreate
```

The diagnosis is confirmed when the message contains `provider restricted-v2: .containers[0].runAsUser: Invalid value: 10000:
must be in the ranges`, as in the [offline admission result](evidence/admission-nonroot-check.log). On 4.20 it also lists the
restricted-v3 `hostUsers` rejection. Any other cause, such as quota, a different SCC field, or webhook denial, invalidates the
proposal; stop and revisit the diagnosis.

Check the corrected variant. It should be Running under restricted-v2 with a nonzero UID from the namespace range:

```bash
oc --context "$ctx" get namespace acm-48176-corrected -o jsonpath='{.metadata.annotations.openshift\.io/sa\.scc\.uid-range}{"\n"}'
oc --context "$ctx" -n acm-48176-corrected get pods -o \
  jsonpath='{range .items[*]}{.metadata.name} {.status.phase} {.metadata.annotations.openshift\.io/scc} {.spec.containers[0].securityContext.runAsUser}{"\n"}{end}'
for pod in $(oc --context "$ctx" -n acm-48176-corrected get pods -o name); do
  oc --context "$ctx" -n acm-48176-corrected exec "$pod" -- id -u
done
```

An unexpected privileged or anyuid SCC is insufficient. Save the outputs, then delete both namespaces.

## 2. Optional: confirm the cause with the unchanged artifact

On disposable QE clusters only, temporarily let service accounts use the stock `nonroot-v2` SCC. That SCC admits the original UID 10000
template while keeping the rest of the hardening ([admission result](evidence/admission-nonroot-check.log)):

```bash
oc --context "$CTX_A" adm policy add-scc-to-group nonroot-v2 system:serviceaccounts
oc --context "$CTX_B" adm policy add-scc-to-group nonroot-v2 system:serviceaccounts
```

Run step 3 with the original 0.23.4 Subctl. All 14 cases should get past helper setup. Then always remove the grant from both contexts,
for example with `oc --context "$CTX_A" adm policy remove-scc-from-group nonroot-v2 system:serviceaccounts`. Confirm
`oc get clusterrolebinding -o wide | grep scc:nonroot-v2` no longer lists the group. This weakens cluster policy; it is a
diagnostic, not a product fix or a general customer workaround.

## 3. Run discovery in both directions

Set `SUBCTL` to the absolute path of the inspected executable; retain its checksum and `go version -m` output. For containers,
retain image/platform and embedded executable identities. Run:

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

Preserve exact commands, context mapping, artifact identity, image/environment, and statuses. The tests use fixed ClusterA/ClusterB
roles, and Subctl derives its shared image from cluster A's Submariner CR unless overridden. Check the emitted image in each direction.
Disable wrapper retries and audit landed specs/Ginkgo configuration for retry or dry-run modes.

## 4. Record the corrected helpers' admission

The suite deletes its namespaces when each case ends. Start this sampler in a second terminal before step 3 runs the corrected artifact:

```bash
while sleep 5; do
  for ctx in "$CTX_A" "$CTX_B"; do
    oc --context "$ctx" get pods -A -l 'app in (nginx-demo,netshoot)' -o \
      jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.status.phase} {.metadata.annotations.openshift\.io/scc} {.spec.containers[0].securityContext.runAsUser}{"\n"}{end}'
  done
done | tee "$OUT/helper-pods.log"
```

Require restricted-v2 and a nonzero UID for every sampled helper; restricted-v2 only admits UIDs from the namespace range.
Stop the loop after step 3.

If step 1 shows a different cause, or the corrected run still fails, use the forensic capture in the appendix.

## 5. Accept the corrected artifact

Require both Subctl exit statuses to be zero, with no SCC grant from step 2 in place. Then run:

```bash
python3 evidence/check_discovery_junit.py \
  --expected evidence/attachment-analysis.json \
  --reports "$OUT/discovery-a-b.xml" "$OUT/discovery-b-a.xml"
```

Require checker exit zero too: every original case must occur exactly once and pass in each report, with no substituted/skipped
cases, additional failures, or invalid execution metadata. Unrelated skips are recorded separately. The pinned JUnit format omits
per-case attempt counts; audit source/wrappers for per-spec retries. The checker cannot establish artifact identity, context order,
or causality.

Close ACM-48176, and ACM-48194 as its duplicate, only when step 1 shows the UID rejection on the original templates, the corrected
delivered artifact produces restricted-v2 helpers with in-range UIDs, and all 14 original cases pass in both directions.

## Appendix: forensic capture

Use this only when steps 1–4 leave the cause unexplained. The [read-only collector](evidence/capture_discovery.go.txt) records
`namespaces` (selector `e2e-framework=discovery`) and, one process each, `deployments.apps`, `replicasets.apps`, `pods`, and
`events` across namespaces. It resumes from the last resourceVersion after EOF and fails on expired versions instead of
relisting over a gap. A single kubectl watch can [exit zero on stream closure](evidence/kubectl-watch-close-results.json).

Build it against an inspected Lighthouse or Subctl checkout that selects client-go v0.35.8:

```bash
capture_src=$(mktemp -d)
cp evidence/capture_discovery.go.txt "$capture_src/capture_discovery.go"
cp evidence/capture_discovery_test.go.txt "$capture_src/capture_discovery_test.go"
cd "$INSPECTED_MODULE_CHECKOUT"
GOWORK=off go test -mod=readonly -race "$capture_src/capture_discovery.go" "$capture_src/capture_discovery_test.go"
GOWORK=off go build -mod=readonly -o "$LOCAL_CAPTURE/capture-discovery" "$capture_src/capture_discovery.go"
```

Start one process per resource and context before step 3, for example
`"$LOCAL_CAPTURE/capture-discovery" --context "$CTX_A" --resource pods > a-pods.jsonstream 2> a-pods.stderr &`.
Require `list_complete` and `watch_established` records from every process before testing. Afterward, send SIGTERM and require
exit zero with an `operator_stop` record. Reject premature exits, output failures, expired versions, and unexplained gaps.
Keep the output local because it contains private metadata. See [collector checks](evidence/capture-discovery-provenance.json).
