# QE procedure for ACM-48176

Step 1 confirms the cause in minutes and needs no new build. Step 2 is an optional confirmation with the unchanged 0.23.4 Subctl.
Steps 3 and 4 accept the fixed Subctl. Run all commands from this directory.

Set:

- `CTX_A` and `CTX_B` to the two cluster contexts;
- `NETTEST_DIGEST_REF` to the `registry/repository@sha256:...` nettest image QE uses;
- `OUT` to a fresh directory.

Use the same image, clusters, and grants throughout, apart from step 2's temporary grant.

## 1. Reproduce the rejection

[`evidence/repro/original`](evidence/repro/original) holds the exact Deployments that the Lighthouse v0.23.4 builders create.
[`evidence/repro/corrected`](evidence/repro/corrected) holds the same Deployments without the pod `runAsUser`, which is what
the fix produces on OpenShift. The namespaces get the same labels the e2e framework uses. On each context:

```bash
ctx=$CTX_A   # then CTX_B
for variant in original corrected; do
  ns=acm-48176-$variant
  oc --context "$ctx" create namespace "$ns"
  oc --context "$ctx" label namespace "$ns" \
    pod-security.kubernetes.io/enforce=privileged security.openshift.io/scc.podSecurityLabelSync=false
  for helper in nginx-demo netshoot; do
    sed "s|NETTEST_IMAGE|$NETTEST_DIGEST_REF|" "evidence/repro/$variant/$helper.json" | oc --context "$ctx" -n "$ns" create -f -
  done
done
oc --context "$ctx" -n acm-48176-corrected wait deployment --all --for=condition=Available --timeout=240s

# Original: expect no pods, and a ReplicaFailure message naming runAsUser 10000.
oc --context "$ctx" -n acm-48176-original get pods
oc --context "$ctx" -n acm-48176-original get rs -o \
  jsonpath='{range .items[*]}{.metadata.name}: {.status.conditions[?(@.type=="ReplicaFailure")].message}{"\n"}{end}'

# Corrected: expect Running under restricted-v2, with a UID from the namespace range.
oc --context "$ctx" get namespace acm-48176-corrected -o jsonpath='{.metadata.annotations.openshift\.io/sa\.scc\.uid-range}{"\n"}'
oc --context "$ctx" -n acm-48176-corrected get pods -o \
  jsonpath='{range .items[*]}{.metadata.name} {.status.phase} {.metadata.annotations.openshift\.io/scc} {.spec.containers[0].securityContext.runAsUser}{"\n"}{end}'

oc --context "$ctx" delete namespace acm-48176-original acm-48176-corrected
```

The diagnosis is confirmed when each original ReplicaSet reports
`provider restricted-v2: .containers[0].runAsUser: Invalid value: 10000: must be in the ranges`. On 4.20 the message also
includes a restricted-v3 `hostUsers` rejection. Any other cause, such as quota, a different SCC field, or a webhook, means the
diagnosis is wrong; stop here. Save the output.

## 2. Optional: confirm with the unchanged Subctl

On disposable test clusters only, temporarily allow every service account to use the stock `nonroot-v2` SCC. It admits UID 10000
and still enforces the rest of the hardening:

```bash
for ctx in "$CTX_A" "$CTX_B"; do oc --context "$ctx" adm policy add-scc-to-group nonroot-v2 system:serviceaccounts; done
```

Run step 3 with the original 0.23.4 Subctl; all 14 cases should get past helper setup. Then remove the grant with
`oc --context "$ctx" adm policy remove-scc-from-group nonroot-v2 system:serviceaccounts` on both contexts. It is a diagnostic,
not a workaround to recommend.

## 3. Run discovery with the fixed Subctl

Set `SUBCTL` to the executable under test and record its checksum and `go version -m` output (see the [plan](PLAN.md#delivering-subctl)).
The commands unset `RELATED_IMAGE_submariner-nettest`, which would override the image flag, and sample the helper pods for the
whole run, because the suite deletes its namespaces.

```bash
sample_helpers() {
  while sleep 5; do
    for ctx in "$CTX_A" "$CTX_B"; do
      oc --context "$ctx" get pods -A -l 'app in (nginx-demo,netshoot)' -o \
        jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.status.phase} {.metadata.annotations.openshift\.io/scc} {.spec.containers[0].securityContext.runAsUser}{"\n"}{end}'
    done
  done
}
run_discovery() { # from-context to-context name
  env -u RELATED_IMAGE_submariner-nettest "$SUBCTL" verify --context "$1" --tocontext "$2" --only service-discovery \
    --image-override "submariner-nettest=$NETTEST_DIGEST_REF" --junit-report "$OUT/$3.xml" > "$OUT/$3.log" 2>&1
  echo $? > "$OUT/$3.exit"
}

sample_helpers > "$OUT/helper-pods.log" 2>&1 &
sampler=$!
run_discovery "$CTX_A" "$CTX_B" a-to-b
run_discovery "$CTX_B" "$CTX_A" b-to-a
kill "$sampler"
```

## 4. Accept

```bash
cat "$OUT/a-to-b.exit" "$OUT/b-to-a.exit"   # both 0
python3 evidence/check_discovery_junit.py --expected evidence/attachment-analysis.json \
  --reports "$OUT/a-to-b.xml" "$OUT/b-to-a.xml"
grep -v ' restricted-v2 [1-9]' "$OUT/helper-pods.log"   # no output
```

The checker requires each of the 14 original cases to appear exactly once and pass in both reports. The last command requires
every sampled helper to run under restricted-v2 with a nonzero UID; restricted-v2 only admits UIDs from the namespace range.
Make sure step 2's grant is gone first.

Close ACM-48176 and its duplicate ACM-48194 when step 1 showed the UID rejection and step 4 passes.
