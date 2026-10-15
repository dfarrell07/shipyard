# Benchmark failures that could be reported as success

The deeper review found a third defect in the error-reporting path. It is independent of the likely Lighthouse admission problem
and predates the Glasswing hardening. It can hide the reproduced iperf3 scratch-space regression.

## Shipyard's retry command

The old throughput client ran a shell loop that broke on iperf3 success and otherwise printed a retry message and slept. When every
attempt failed, the loop finished with the status of its last successful sleep. With zero attempts, the empty loop also succeeded.
Kubernetes could therefore report a Succeeded client pod even though no throughput test succeeded.

The command is already present before Shipyard's 2022 formatting commit `df224175`; that blame entry identifies a formatting change,
not the bug's introduction. The scratch-space change exposed a pre-existing error-propagation problem rather than creating it.

The [Shipyard retry patch](evidence/shipyard-retry-status.patch) is based on the initial feature-branch state at `dd4add5e`.
It is separate from the earlier scratch-only patches.

The new regression test obtains the command from the actual pod builder and executes it with a private fake iperf3. Only the
kubelet-managed termination-log path is replaced with a local test file. It checks four cases:

- Every configured attempt fails: non-zero status and the expected attempt count.
- The first attempt succeeds: zero status and no extra attempt.
- The retry succeeds: zero status and the expected attempt count.
- No attempts are configured: non-zero status, with no iperf3 invocation.

[Before the correction](evidence/retry-exit-before.log), exhausted and empty loops incorrectly succeed. The corrected command exits
zero immediately on iperf3 success and exits one after exhaustion. [After correction](evidence/retry-exit-after.log), the framework
package's tests pass. Its read-only root, scratch mounts, retry count, and benchmark CPU policy are preserved.

This is a shell-status test with controlled fixtures. It establishes error propagation, not iperf3 behavior or real cluster behavior.
The independent pinned-image checks establish the temporary-file failure and successful exchanges.

## A remaining Subctl consumer defect

The inspected Subctl tree is `4b44caa4f6abaf37a303d3da81a367bc8b2b232c`. Its
[throughput caller](https://github.com/submariner-io/subctl/blob/4b44caa4f6abaf37a303d3da81a367bc8b2b232c/internal/benchmark/throughput.go#L160)
only calls CheckSuccessfulFinish when verbose mode is disabled. Consequently:

- Before the Shipyard retry correction, the ordinary mode's exit-code check can accept exhausted retries as success.
- After the Shipyard correction, ordinary mode can detect exhaustion, but verbose mode still skips that check.
- A verbose log containing an error is not the same as a failing command or CI job.

The [proposed consumer patch](evidence/subctl-throughput-status.patch) moves CheckSuccessfulFinish outside the verbosity condition.
It passes `git apply --check` against that inspected tree, but has **not** been applied to Subctl or runtime-tested. A Subctl regression
should verify the same failed pod result in both modes, and verify that successful runs still return success and preserve output.
The Shipyard feature branch alone cannot close that consumer defect.

Related connector retry loops also end in sleep after a failed attempt. They were observed in the source, but their callers have
additional data-validation behavior. No blanket claim is made about their final verification result, and they are not changed here.
A separate caller-by-caller review is needed before generalizing this throughput fix.

## Closing a reproduction gap

The first successful scratch-space experiments used explicit tmpfs mounts. The Kubernetes patch uses disk-backed emptyDir.
The [additional reproduction](evidence/disk_scratch_check.py) supplies separate writable disk directories for server and client,
keeps both roots read-only, disables implicit writable temporary mounts, drops capabilities, and disables privilege escalation.
Both pinned images pass on the host's btrfs filesystem. The script also checks iperf3's JSON for no error and a positive received-byte
count; an exit status alone is not used as evidence of a successful exchange.

[Results](evidence/disk-scratch-results.json) and both full JSON reports are retained. This narrows the gap between tmpfs and the
proposed storage policy. It still does not exercise kubelet emptyDir ownership, storage-limit enforcement, SELinux labels in the
QE cluster, OpenShift admission, or representative network performance. The reported throughput numbers are local functional-test
artifacts, not product performance measurements.

## Correcting the validation record

During the second pass, an initial `TEST_ARGS=--fail` run picked up the newly added, deliberately failing retry test while the fix was
still in progress. Its non-zero status therefore did not demonstrate the intended negative control. The earlier commit retains that
history; the current evidence replaces it with a run of the completed changes and explicitly checks both that the framework package
passes and that the intentional `test/scripts/unit/failing_test.go` fixture causes failure. A failing negative control is useful only
when it fails for the intended reason.

The local shared runner also discovers an existing nested `.claude/worktrees` module in this workspace. Those extra runs are visible
in the logs; they do not substitute for the explicitly recorded root framework test. A clean CI checkout need not contain that module.
No claim is made that fresh remote CI ran, since this feature branch has no PR.
