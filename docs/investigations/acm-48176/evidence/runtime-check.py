import json, pathlib, subprocess, time
out=pathlib.Path(__file__).parent
images={'konflux-0.23.4':'quay.io/redhat-user-workloads/submariner-tenant/nettest-0-23@sha256:a4ca9da9d5e1193a89956f5d5e6db7c1e02297ccb450a6a72a9b228f5ab06ae1','community-devel':'quay.io/submariner/nettest@sha256:378d5785fd8c84ed6d0f6bbe64a6245380d6e6de6d1d6a84cef3e692858c9181'}
base=['podman','run','--pull=never','--read-only','--read-only-tmpfs=false','--cap-drop=ALL','--security-opt=no-new-privileges','--memory=256m','--cpus=0.5']
identities={'image-default':[], 'openshift-like':['--userns=keep-id:uid=1001530000,gid=0','--user','1001530000:0'], 'no-root-group':['--userns=keep-id:uid=1001530000,gid=1001530000','--user','1001530000:1001530000']}
results=[]
def run(args,check=True,timeout=35):
 p=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
 if check and p.returncode: raise RuntimeError({'cmd':args,'exit':p.returncode,'out':p.stdout,'err':p.stderr})
 return p
for image_name,image in images.items():
 for identity,flags in identities.items():
  for kind,command in [('netshoot',['sleep','600']),('nginx-demo',['/app/simpleserver'])]:
   case=f'{image_name}-{identity}-{kind}'
   args=base+flags+['-d',image]+command
   created=run(args)
   cid=created.stdout.strip()
   try:
    time.sleep(.3)
    state=json.loads(run(['podman','inspect',cid]).stdout)[0]
    assert state['State']['Running'],state['State']
    checks=['id; grep -E "^(CapEff|NoNewPrivs|Seccomp):" /proc/self/status; test ! -w /tmp; test ! -w /app; test "$(dig +time=2 +tries=1 +short localhost)" = 127.0.0.1; test "$(dig +time=2 +tries=1 +tcp +short localhost)" = 127.0.0.1; echo UDP-DNS-PASS; echo TCP-DNS-PASS']
    p=run(['podman','exec',cid,'/bin/bash','-ec',checks[0]])
    assert 'CapEff:\t0000000000000000' in p.stdout, p.stdout
    assert 'NoNewPrivs:\t1' in p.stdout, p.stdout
    assert 'Seccomp:\t2' in p.stdout, p.stdout
    expected_uid = '10000' if identity == 'image-default' else '1001530000'
    assert ('uid=' + expected_uid + '(') in p.stdout, p.stdout
    response=''
    if kind=='nginx-demo':
     for i in range(8):
      response+=run(['podman','exec',cid,'curl','--max-time','3','-fsS','http://127.0.0.1:8080']).stdout
     assert response.count('Hello World')==8,response
    log=created.stderr+p.stdout+p.stderr+response
    (out/f'runtime-{case}.log').write_text(log)
    results.append({'case':case,'running':True,'checks_exit':p.returncode,'http_responses':response.count('Hello World'),'command':args})
    print(case,'PASS',flush=True)
   finally: run(['podman','rm','-f',cid])
(out/'runtime-output.json').write_text(json.dumps(results,indent=2)+'\n')
