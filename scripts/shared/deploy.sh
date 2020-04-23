#!/usr/bin/env bash

## Process command line flags ##

source ${SCRIPTS_DIR}/lib/shflags
DEFINE_string 'cluster_settings' '' "Settings file to customize cluster deployments"
DEFINE_string 'deploytool' 'operator' 'Tool to use for deploying (operator/helm)'
DEFINE_string 'deploytool_broker_args' '' 'Any extra arguments to pass to the deploytool when deploying the broker'
DEFINE_string 'deploytool_submariner_args' '' 'Any extra arguments to pass to the deploytool when deploying submariner'
DEFINE_string 'globalnet' 'false' "Deploy with operlapping CIDRs (set to 'true' to enable)"
DEFINE_string 'cable_driver' '' "Cable driver implementation"

FLAGS "$@" || exit $?
eval set -- "${FLAGS_ARGV}"

globalnet="${FLAGS_globalnet}"
deploytool="${FLAGS_deploytool}"
deploytool_broker_args="${FLAGS_deploytool_broker_args}"
deploytool_submariner_args="${FLAGS_deploytool_submariner_args}"
cluster_settings="${FLAGS_cluster_settings}"
cable_driver="${FLAGS_cable_driver}"
num_clusters=$(kind get clusters | wc -l)

echo "Running with: globalnet=${globalnet@Q}, deploytool=${deploytool@Q}, deploytool_broker_args=${deploytool_broker_args@Q}, deploytool_submariner_args=${deploytool_submariner_args@Q}, num_clusters=${num_clusters}, cluster_settings=${cluster_settings@Q}, cable_driver=${cable_driver@Q}"

set -em

source ${SCRIPTS_DIR}/lib/debug_functions
source ${SCRIPTS_DIR}/lib/version
source ${SCRIPTS_DIR}/lib/utils
source ${SCRIPTS_DIR}/lib/deploy_funcs

# Always source the shared cluster settings, to set defaults in case something wasn't set in the provided settings
source "${SCRIPTS_DIR}/lib/cluster_settings"

if [ ${num_clusters} -gt 3 ]; then
    for i in $(eval echo "{4..${num_clusters}}"); do
        cluster_nodes[$i]="control-plane worker"
        cluster_subm[$i]="true"
    done
fi

[[ -z "${cluster_settings}" ]] || source ${cluster_settings}

### Main ###

declare_cidrs ${num_clusters}
declare_kubeconfig

import_image quay.io/submariner/submariner
import_image quay.io/submariner/submariner-route-agent
[[ $globalnet != "true" ]] || import_image quay.io/submariner/submariner-globalnet

load_deploytool $deploytool
deploytool_prereqs

run_parallel "{1..${num_clusters}}" prepare_cluster "$SUBM_NS"

with_context cluster1 setup_broker
install_subm_all_clusters

deploytool_postreqs

with_context cluster2 connectivity_tests

