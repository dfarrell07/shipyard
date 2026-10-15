"""Check iperf3 stream creation with writable disk directories on both endpoints."""
import json
import os
import pathlib
import subprocess
import tempfile

out = pathlib.Path(__file__).resolve().parent
images = {
    'konflux-0.23.4': 'quay.io/redhat-user-workloads/submariner-tenant/nettest-0-23@sha256:a4ca9da9d5e1193a89956f5d5e6db7c1e02297ccb450a6a72a9b228f5ab06ae1',
    'community-devel': 'quay.io/submariner/nettest@sha256:378d5785fd8c84ed6d0f6bbe64a6245380d6e6de6d1d6a84cef3e692858c9181',
}
base = ['podman', 'run', '--read-only', '--read-only-tmpfs=false', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--user', '10000']
results = []
for name, image in images.items():
    with tempfile.TemporaryDirectory(prefix='disk-scratch-', dir=out.parent) as temporary:
        parent = pathlib.Path(temporary)
        paths = [parent / 'server', parent / 'client']
        for path in paths:
            path.mkdir()
            os.chmod(path, 0o1777)
        filesystem = subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(parent)], text=True).strip()
        assert filesystem != 'tmpfs', 'Use a disk-backed checkout for this probe'
        server = subprocess.check_output(base + ['-d', '-v', str(paths[0]) + ':/tmp:rw,Z', image, 'iperf3', '-s', '-1'], text=True).strip()
        try:
            client = subprocess.run(base + ['--rm', '-v', str(paths[1]) + ':/tmp:rw,Z', '--network', 'container:' + server,
                image, 'sh', '-c', 'sleep 1; exec iperf3 -c 127.0.0.1 -P 10 -w 256K -t 1 -J'], text=True, capture_output=True, timeout=20)
            (out / (name + '-disk-scratch.json')).write_text(client.stdout)
            assert client.returncode == 0, client.stderr
            data = json.loads(client.stdout)
            assert 'error' not in data, data
            transferred = data['end']['sum_received']['bytes']
            assert transferred > 0, data
            results.append({'image': image, 'filesystem': filesystem, 'exit_code': client.returncode, 'received_bytes': transferred})
            print(name, 'passed', flush=True)
        finally:
            subprocess.run(['podman', 'rm', '-f', server], capture_output=True, check=True)
(out / 'disk-scratch-results.json').write_text(json.dumps(results, indent=2) + '\n')
