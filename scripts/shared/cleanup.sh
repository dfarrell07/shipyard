
#!/usr/bin/env bash
set -em

source ${SCRIPTS_DIR}/lib/debug_functions
source ${SCRIPTS_DIR}/lib/utils

### Functions ###

function delete_cluster() {
    kind delete cluster --name=${cluster};
}

function stop_local_registry {
    if registry_running; then
        echo "Stopping local KIND registry..."
        docker stop $KIND_REGISTRY
    fi
}


### Main ###

n=$(kind get clusters | wc -l)
if [ ${n} -gt 0 ]; then
    run_parallel "{1..${n}}" delete_cluster
fi

stop_local_registry
docker system prune --volumes -f

