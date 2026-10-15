import json
import pathlib
import subprocess

out = pathlib.Path(__file__).resolve().parent
images = {
    'konflux-0.23.4': 'quay.io/redhat-user-workloads/submariner-tenant/nettest-0-23@sha256:a4ca9da9d5e1193a89956f5d5e6db7c1e02297ccb450a6a72a9b228f5ab06ae1',
    'community-devel': 'quay.io/submariner/nettest@sha256:378d5785fd8c84ed6d0f6bbe64a6245380d6e6de6d1d6a84cef3e692858c9181',
}
base = ['podman', 'run', '--read-only', '--read-only-tmpfs=false', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--user', '10000']
scratch = ['--tmpfs', '/tmp:rw,nosuid,nodev,size=64m,mode=1777']
results = []
for name, image in images.items():
    inspect = subprocess.run(['skopeo', 'inspect', 'docker://' + image], text=True, capture_output=True, check=True)
    metadata = json.loads(inspect.stdout)
    metadata.pop('RepoTags', None)
    (out / (name + '-image.json')).write_text(json.dumps(metadata, indent=2) + '\n')
    for server_tmp, client_tmp in [(False, False), (True, False), (False, True), (True, True)]:
        case = f'{name}-server-tmp-{server_tmp}-client-tmp-{client_tmp}'
        server = subprocess.run(base + (scratch if server_tmp else []) + ['-d', image, 'iperf3', '-s', '-p', '5201'], text=True, capture_output=True, check=True).stdout.strip()
        try:
            client = subprocess.run(base + (scratch if client_tmp else []) + ['--rm', '--network', 'container:' + server, image, '/bin/bash', '-c', 'sleep 1; iperf3 -c 127.0.0.1 -p 5201 -P 10 -w 256K -t 1'], text=True, capture_output=True, timeout=20)
            server_logs = subprocess.run(['podman', 'logs', server], text=True, capture_output=True)
            (out / (case + '.log')).write_text(client.stdout + client.stderr + '\nSERVER:\n' + server_logs.stdout + server_logs.stderr)
            expected = 0 if server_tmp and client_tmp else 1
            assert (client.returncode == 0) == (expected == 0), (case, client.returncode)
            results.append({'case': case, 'exit_code': client.returncode, 'expected_pass': expected == 0})
            print(case, client.returncode, flush=True)
        finally:
            subprocess.run(['podman', 'rm', '-f', server], capture_output=True, check=True)
    uid = '1000780000'
    command = 'id; /app/simpleserver >/dev/null 2>/dev/null & server_pid=$!; trap "kill $server_pid" EXIT; curl --retry 5 --retry-connrefused --retry-delay 1 --max-time 3 -fsS http://127.0.0.1:8080; dig +short localhost'
    http = subprocess.run(base + ['--rm', '--userns=keep-id:uid=' + uid + ',gid=0', '--user', uid, image, '/bin/bash', '-c', command], text=True, capture_output=True, timeout=20)
    (out / (name + '-arbitrary-uid-http-dns.log')).write_text(http.stdout + http.stderr)
    assert http.returncode == 0 and 'Hello World' in http.stdout and '127.0.0.1' in http.stdout, http
    results.append({'case': name + '-arbitrary-uid-http-dns', 'exit_code': http.returncode})
(out / 'runtime-results.json').write_text(json.dumps(results, indent=2) + '\n')
