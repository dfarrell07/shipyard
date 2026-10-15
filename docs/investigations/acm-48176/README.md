# ACM-48176: nettest helper pods rejected on OpenShift

**Status:** diagnosed offline; fix pushed to `dfarrell07/lighthouse` as `nettest-scc-uid-<branch>` for all nine branches, PRs not
opened.
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

Plain Kubernetes keeps 10000 because Subctl uses the nettest image of the deployed Submariner version, and every nettest image
before v0.22.2, v0.23.3, and v0.24.2 defaults to root ([image users](evidence/image-users.json); Shipyard's `Dockerfile.nettest`).
Without an explicit UID, `runAsNonRoot` would reject those images when a new Subctl verifies a cluster not yet upgraded, the
usual upgrade order. Simply deleting the UID, as Shipyard did for its CI YAMLs, would break that case.

Discovery retries transient errors within the operation timeout and otherwise fails the test. All other hardening is unchanged.

The builders are compiled into Subctl, so the fix ships as a rebuilt Subctl. No image or operator change is needed.

## Next steps

1. **Developer** opens the nine Lighthouse PRs together and merges `release-0.23`, `release-0.22`, and `release-0.24` first ([plan](PLAN.md)).
2. **Release owners** ship the fix in 0.23.5, and hold downstream 0.22.2 and 0.24.2 until they include it ([delivery](PLAN.md#delivering-subctl)).
3. **QE** reruns its usual Submariner job with the rebuilt Subctl. All 14 cases should pass; that confirms the fix.
4. **Developer** adds a known-issue note to the affected upstream Subctl releases.

If the cases still fail, `oc create` the [original Deployments](evidence/repro/original), with `NETTEST_IMAGE` replaced, in a
namespace with the e2e framework's labels. Their ReplicaSets report the admission decision directly.

The [evidence index](evidence/README.md) maps each claim to its supporting files.
