# ACM-48176: nettest helper pods rejected on OpenShift

**Status:** diagnosed offline; fix committed locally for all nine Lighthouse branches, not yet pushed; QE confirmation pending.
ACM-48194 is a duplicate.

## What fails

`subctl verify --only service-discovery` on OpenShift 4.19 and 4.20 fails 14 cases while setting up its helper Deployments,
before any DNS check runs. The [attached run](evidence/attachment-analysis.json) shows:

- All 14 helper Deployments end with zero pods: 10 `nginx-demo` (6 on 4.19, 4 on 4.20) and 4 `netshoot` (on 4.20).
- All 4 StatefulSets in the same namespaces reach Running. They use the same image, service account, and `nginx-demo` command,
  but have no securityContext.

Zero Pod objects means the pods were never admitted. A crashing image would still leave Pods behind.

## Cause

Security hardening in Lighthouse v0.23.2 (present on every branch) set `runAsUser: 10000` on the pods of `NewNginxDeployment` and
`NewNetShootDeploymentInNS`. OpenShift's default restricted-v2 SCC only admits UIDs from the namespace's allocated range. The
ReplicaSet controller creates these pods, and it has only the stock SCC grants, so every pod create is rejected.
The connectivity tests still pass because their pods are created directly by the cluster-admin user, whose SCC access admits UID 10000.

Running the real OpenShift admission code on the exact Deployments rejects the original with
`restricted-v2: .containers[0].runAsUser: Invalid value: 10000: must be in the ranges`, and admits it once `runAsUser` is removed
([check](evidence/admission-check.log)).

Downstream QE never ran these builders on OpenShift before: 0.23.2 never reached downstream production, and 0.23.4 is the first QE run.
The earlier fix attempt changed only Shipyard's CI YAML files, which `subctl verify` does not use.

## Fix

For each target cluster, the builders query API discovery:

| Target cluster | Pod `runAsUser` |
| --- | --- |
| Serves the `security.openshift.io` API group | Unset; SCC admission assigns a UID from the namespace range |
| Anything else | 10000, as today |

Plain Kubernetes keeps 10000 because Subctl uses the nettest image of the deployed Submariner version. The 0.23.2 image
defaults to root (0.23.3 and later use 10000; see [image users](evidence/image-users.json)), and without an explicit UID
`runAsNonRoot` would reject it. Discovery retries transient errors within the operation timeout and otherwise fails the test.
All other hardening is unchanged.

The builders are compiled into Subctl, so the fix ships as a rebuilt Subctl. No image or operator change is needed.

## Next steps

1. **QE** reproduces the rejection in scratch namespaces, which takes minutes: [QE step 1](QE-VALIDATION.md#1-reproduce-the-rejection).
2. **Developer** opens the nine Lighthouse PRs together and merges `release-0.23`, `release-0.22`, and `release-0.24` first ([plan](PLAN.md)).
3. **Release owners** ship the fix in 0.23.5, and hold downstream 0.22.2 and 0.24.2 until they include it ([delivery](PLAN.md#delivering-subctl)).
4. **QE** accepts the rebuilt Subctl: all 14 cases pass in both directions ([QE steps 3–4](QE-VALIDATION.md#3-run-discovery-with-the-fixed-subctl)).
5. **Developer** adds a known-issue note to the affected upstream Subctl releases.

The [evidence index](evidence/README.md) maps each claim to its supporting files.
