# ACM-48176: nettest helper pods rejected on OpenShift

**Status:** diagnosed; the `devel` fix is in draft Lighthouse PR [#2324](https://github.com/submariner-io/lighthouse/pull/2324),
updated for skitt's review. The release-branch PRs (#2325–#2332) are closed until it merges.
ACM-48194 tracks the known-issue note.

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
The connectivity tests still pass because they create pods directly as the verifying user, typically a cluster admin whose
SCC access admits UID 10000.

Running the real OpenShift admission code on the exact Deployments rejects the original with
`restricted-v2: .containers[0].runAsUser: Invalid value: 10000: must be in the ranges`, and admits it once `runAsUser` is removed
([check](evidence/admission-check.log)).

QE hit the same rejection live while testing 0.23.2: [ACM-44539](https://redhat.atlassian.net/browse/ACM-44539) records a
netshoot `FailedCreate` with that exact restricted-v2 message, and a later interop report there blames these builders. The
earlier fix attempt changed only Shipyard's CI YAML files, which `subctl verify` does not use.

## Impact

Deployed Submariner is unaffected. Of the shipped binaries, only Subctl links the builders, and only `subctl verify` runs them:
the lighthouse-agent and coredns binaries do not link any Lighthouse `test/` package, and neither the operator nor the ACM addon
uses them. The attached run's `subctl diagnose all` and connectivity tests pass.

Users who run `subctl verify` against OpenShift with an affected Subctl can encounter these helper-setup failures. The attached
run provides no service-discovery result because all 14 cases failed before their DNS checks. QE should confirm other coverage
separately.

## Fix

For each target cluster, the builders query API discovery:

| Target cluster | Pod `runAsUser` |
| --- | --- |
| Serves the `security.openshift.io` API group | Unset; SCC admission assigns a UID from the namespace range |
| Anything else | 10000, as today |

Plain Kubernetes keeps 10000 because Subctl uses the nettest image of the deployed Submariner version, and only nettest images
from v0.22.2, v0.23.3, v0.24.2, and v0.25.0-rc0 onwards set a non-root user; every other release, including all 0.18–0.21
images, defaults to root ([image users](evidence/image-users.json); Shipyard's `Dockerfile.nettest`).
Without an explicit UID, `runAsNonRoot` would reject those images when a new Subctl verifies a cluster not yet upgraded, the
usual upgrade order. Simply deleting the UID, as Shipyard did for its CI YAMLs, would break that case.

Discovery retries transient errors within the operation timeout and otherwise fails the test. All other hardening is unchanged.

The builders are compiled into Subctl, so the fix ships as a rebuilt Subctl. No image or operator change is needed.

## Next steps

1. **Developer** marks [#2324](https://github.com/submariner-io/lighthouse/pull/2324) ready, gets it approved and merged, then
   opens the backports ([plan](PLAN.md#landing)).
2. **Release owners** pick up the fix through a Lighthouse tag, Subctl bump, and fresh Subctl build in each branch's next
   regular release ([delivery](PLAN.md#delivering-the-fix)).
3. **QE** runs `subctl verify --only service-discovery` with that Subctl on OpenShift to verify the fix and close ACM-48176.
4. **Developer** adds the known-issue note tracked by ACM-48194 to the affected Subctl releases.

The [evidence index](evidence/README.md) maps each claim to its supporting files.
