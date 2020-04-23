#!/usr/bin/env bash

## Process command line flags ##

source ${SCRIPTS_DIR}/lib/shflags
DEFINE_string 'k8s_version' '' 'Version of K8s to use'
DEFINE_string 'globalnet' 'false' "Deploy with operlapping CIDRs (set to 'true' to enable)"
DEFINE_string 'registry_inmemory' 'true' "Run local registry in memory to speed up the image loading."
DEFINE_string 'cluster_settings' '' "Settings file to customize cluster deployments"
DEFINE_integer "num_clusters" "3" "The number of clusters to create (1 to 3)" "n"
FLAGS "$@" || exit $?
eval set -- "${FLAGS_ARGV}"

version="${FLAGS_k8s_version}"
globalnet="${FLAGS_globalnet}"
registry_inmemory="${FLAGS_registry_inmemory}"
cluster_settings="${FLAGS_cluster_settings}"
num_clusters="${FLAGS_num_clusters}"

if [ ${num_clusters} -lt 1 ]; then
    echo "num_clusters must be greater than 1"
    exit 1
fi

echo "Running with: k8s_version=${version}, globalnet=${globalnet}, registry_inmemory=${registry_inmemory}, num_clusters=${num_clusters}, cluster_settings=${cluster_settings}"

set -em

source ${SCRIPTS_DIR}/lib/debug_functions
source ${SCRIPTS_DIR}/lib/utils

# Always source the shared cluster settings, to set defaults in case something wasn't set in the provided settings
source "${SCRIPTS_DIR}/lib/cluster_settings"

if [ ${num_clusters} -gt 3 ]; then
    for i in $(eval echo "{4..${num_clusters}}"); do
        cluster_nodes[$i]="control-plane worker"
        cluster_subm[$i]="true"
    done
fi

[[ -z "${cluster_settings}" ]] || source ${cluster_settings}

### Functions ###

function render_template() {
    eval "echo \"$(cat $1)\""
}

function generate_cluster_yaml() {
    local pod_cidr="${cluster_CIDRs[${cluster}]}"
    local service_cidr="${service_CIDRs[${cluster}]}"
    local dns_domain="${cluster}.local"
    local disable_cni="true"
    if [[ "${cluster}" = "cluster1" ]]; then
        disable_cni="false"
    fi

    local nodes
    for node in ${cluster_nodes[${cluster}]}; do nodes="${nodes}"$'\n'"- role: $node"; done

    render_template ${RESOURCES_DIR}/kind-cluster-config.yaml > ${RESOURCES_DIR}/${cluster}-config.yaml
}

function kind_fixup_config() {
    local master_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' ${cluster}-control-plane | head -n 1)
    sed -i -- "s/server: .*/server: https:\/\/$master_ip:6443/g" $KUBECONFIG
    sed -i -- "s/user: kind-.*/user: ${cluster}/g" $KUBECONFIG
    sed -i -- "s/name: kind-.*/name: ${cluster}/g" $KUBECONFIG
    sed -i -- "s/cluster: kind-.*/cluster: ${cluster}/g" $KUBECONFIG
    sed -i -- "s/current-context: .*/current-context: ${cluster}/g" $KUBECONFIG
    chmod a+r $KUBECONFIG
}

function create_kind_cluster() {
    export KUBECONFIG=${KUBECONFIGS_DIR}/kind-config-${cluster}
    if kind get clusters | grep -q "^${cluster}$"; then
        echo "KIND cluster already exists, skipping its creation..."
        rm -f "$KUBECONFIG"
        kind export kubeconfig --name=${cluster}
        kind_fixup_config
        return
    fi

    echo "Creating KIND cluster..."
    generate_cluster_yaml
    local image_flag=''
    if [[ -n ${version} ]]; then
        image_flag="--image=kindest/node:v${version}"
    fi

    kind create cluster $image_flag --name=${cluster} --config=${RESOURCES_DIR}/${cluster}-config.yaml
    kind_fixup_config
}

function deploy_weave_cni(){
    if kubectl wait --for=condition=Ready pods -l name=weave-net -n kube-system --timeout=60s > /dev/null 2>&1; then
        echo "Weave already deployed."
        return
    fi

    echo "Applying weave network..."
    kubectl apply -f "https://cloud.weave.works/k8s/net?k8s-version=v$version&env.IPALLOC_RANGE=${cluster_CIDRs[${cluster}]}"
    echo "Waiting for weave-net pods to be ready..."
    kubectl wait --for=condition=Ready pods -l name=weave-net -n kube-system --timeout=300s
    echo "Waiting for core-dns deployment to be ready..."
    kubectl -n kube-system rollout status deploy/coredns --timeout=300s
}

function run_local_registry() {
    # Run a local registry to avoid loading images manually to kind
    if registry_running; then
        echo "Local registry $KIND_REGISTRY already running."
    else
        echo "Deploying local registry $KIND_REGISTRY to serve images centrally."
        local volume_flag
        [[ $registry_inmemory != "true" ]] || volume_flag="-v /dev/shm/${KIND_REGISTRY}:/var/lib/registry"
        docker run -d $volume_flag -p 5000:5000 --restart=always --name $KIND_REGISTRY registry:2
    fi

    # This IP is consumed by kind to point the registry mirror correctly to the local registry
    registry_ip="$(docker inspect -f '{{.NetworkSettings.IPAddress}}' "$KIND_REGISTRY")"
}


### Main ###

rm -rf ${KUBECONFIGS_DIR}
mkdir -p ${KUBECONFIGS_DIR}

run_local_registry
declare_cidrs ${num_clusters}
with_retries 3 run_parallel "{1..${num_clusters}}" create_kind_cluster
declare_kubeconfig

if [ ${num_clusters} -gt 1 ]; then
    run_parallel "{2..${num_clusters}}" deploy_weave_cni
fi

print_clusters_message
