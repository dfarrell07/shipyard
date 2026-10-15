#!/usr/bin/env python3
"""Local-only collector check: LIST, accepted WATCH, event, then server EOF."""
import http.server
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.parse

requests = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        requests.append({"path": url.path, "watch": query.get("watch") == ["true"]})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if url.path == "/api":
            obj = {"kind": "APIVersions", "apiVersion": "v1", "versions": ["v1"]}
        elif url.path == "/apis":
            obj = {"kind": "APIGroupList", "apiVersion": "v1", "groups": []}
        elif url.path == "/api/v1":
            obj = {"kind": "APIResourceList", "apiVersion": "v1", "groupVersion": "v1", "resources": [
                {"name": "pods", "singularName": "pod", "namespaced": True, "kind": "Pod", "verbs": ["list", "watch"]}]}
        elif url.path == "/api/v1/pods" and query.get("watch") == ["true"]:
            self.wfile.flush()
            time.sleep(0.3)
            obj = {"type": "ADDED", "object": {"kind": "Pod", "apiVersion": "v1", "metadata": {
                "name": "collector-proof", "namespace": "proof", "resourceVersion": "11"}}}
        elif url.path == "/api/v1/pods":
            obj = {"kind": "PodList", "apiVersion": "v1", "metadata": {"resourceVersion": "10"}, "items": []}
        else:
            raise AssertionError(url.path)
        self.wfile.write(json.dumps(obj).encode() + b"\n")
        self.wfile.flush()


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory(prefix="acm48176-watch-") as tmp:
        result = subprocess.run(["kubectl", "--kubeconfig", "/dev/null", "--server", "http://127.0.0.1:" + str(server.server_port),
                                 "--cache-dir", tmp, "-v=6", "get", "pods", "-A", "--watch", "--output-watch-events", "-o", "json"],
                                capture_output=True, text=True, timeout=10)
    version = json.loads(subprocess.check_output(["kubectl", "version", "--client", "-o", "json"], text=True))["clientVersion"]["gitVersion"]
    output = {
        "kubectl_version": version,
        "fixture": "localhost HTTP only; no Kubernetes credentials or live cluster",
        "server_sequence": "LIST resourceVersion 10, WATCH HTTP 200, ADDED resourceVersion 11, clean server EOF",
        "exit_code": result.returncode,
        "watch_requests": sum(request["watch"] for request in requests),
        "event_output_captured": "collector-proof" in result.stdout,
        "watch_http_200_in_stderr": any("watch=true" in line and "200 OK" in line for line in result.stderr.splitlines()),
        "watch_closed_error_in_stderr": "watch closed" in result.stderr.lower(),
        "requests": requests,
    }
    assert output["event_output_captured"] and output["watch_http_200_in_stderr"], output
    Path(__file__).with_name("kubectl-watch-close-results.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
finally:
    server.shutdown()
    server.server_close()
