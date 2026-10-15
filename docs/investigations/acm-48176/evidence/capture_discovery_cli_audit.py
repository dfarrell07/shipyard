#!/usr/bin/env python3
"""Local fixture smoke of the real collector CLI on all five resource paths."""
import http.server
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse

binary = Path(__file__).parents[1] / "capture-discovery"
paths = {
    "namespaces": ("/api/v1/namespaces", "v1", "Namespace"),
    "pods": ("/api/v1/pods", "v1", "Pod"),
    "events": ("/api/v1/events", "v1", "Event"),
    "deployments.apps": ("/apis/apps/v1/deployments", "apps/v1", "Deployment"),
    "replicasets.apps": ("/apis/apps/v1/replicasets", "apps/v1", "ReplicaSet"),
}
results = []
for resource, (path, api_version, kind) in paths.items():
    calls = []
    release = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            calls.append({"path": url.path, "watch": query.get("watch") == ["true"],
                          "selector": query.get("labelSelector", [""])[0]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if query.get("watch") == ["true"]:
                obj = {"type": "ADDED", "object": {"apiVersion": api_version, "kind": kind,
                       "metadata": {"name": "collector-proof", "resourceVersion": "11"}}}
            else:
                obj = {"apiVersion": api_version, "kind": kind + "List", "metadata": {"resourceVersion": "10"}, "items": []}
            self.wfile.write(json.dumps(obj).encode() + b"\n")
            self.wfile.flush()
            if query.get("watch") == ["true"]:
                release.wait(10)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="acm48176-collector-cli-") as tmp:
            directory = Path(tmp)
            config = directory / "config.json"
            config.write_text(json.dumps({"apiVersion": "v1", "kind": "Config", "current-context": "wrong-default",
                "clusters": [{"name": "fixture", "cluster": {"server": "http://127.0.0.1:" + str(server.server_port)}},
                             {"name": "wrong", "cluster": {"server": "http://127.0.0.1:1"}}],
                "contexts": [{"name": "selected-proof", "context": {"cluster": "fixture", "user": "fixture"}},
                             {"name": "wrong-default", "context": {"cluster": "wrong", "user": "fixture"}}],
                "users": [{"name": "fixture", "user": {}}]}))
            stdout, stderr = directory / "output", directory / "metadata"
            with stdout.open("w") as out, stderr.open("w") as err:
                child = subprocess.Popen([str(binary), "--kubeconfig", str(config), "--context", "selected-proof", "--resource", resource], stdout=out, stderr=err)
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if '"phase":"watch_established"' in stderr.read_text() and '"phase":"watch_event"' in stdout.read_text():
                            break
                        if child.poll() is not None:
                            raise AssertionError("collector exited before readiness")
                        time.sleep(0.02)
                    else:
                        raise AssertionError("readiness deadline")
                    alive = child.poll() is None
                    child.send_signal(signal.SIGTERM)
                    code = child.wait(timeout=5)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait()
            selector = "e2e-framework=discovery" if resource == "namespaces" else ""
            passed = alive and code == 0 and len(calls) == 2 and all(call["path"] == path and call["selector"] == selector for call in calls)
            passed = passed and [call["watch"] for call in calls] == [False, True] and '"phase":"operator_stop"' in stderr.read_text()
            results.append({"resource": resource, "path": path, "selector": selector, "explicit_context_overrode_wrong_default": True,
                            "alive_before_operator_stop": alive, "operator_stop_exit": code, "passed": passed})
    finally:
        release.set()
        server.shutdown()
        server.server_close()

output = {"fixture": "localhost HTTP; no credentials/live cluster; actual CLI binary", "cases": results, "passed": all(result["passed"] for result in results)}
Path(__file__).with_name("capture-discovery-cli-results.json").write_text(json.dumps(output, indent=2) + "\n")
print(json.dumps(output, indent=2))
raise SystemExit(0 if output["passed"] else 1)
