/*
SPDX-License-Identifier: Apache-2.0

Copyright Contributors to the Submariner project.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package framework

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	. "github.com/onsi/gomega"
	v1 "k8s.io/api/core/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

func TestThroughputPodsHaveWritableScratchSpace(t *testing.T) {
	RegisterTestingT(t)
	g := NewWithT(t)

	previousClients, previousSecurityContext := KubeClients, podSecurityContext

	t.Cleanup(func() {
		KubeClients, podSecurityContext = previousClients, previousSecurityContext
	})

	KubeClients = []*kubernetes.Clientset{newNetworkPodTestClient(t)}

	initPodSecurityContext()

	f := &Framework{Namespace: "test-throughput"}

	for _, podType := range []NetworkPodType{ThroughputClientPod, ThroughputServerPod} {
		pod := f.NewNetworkPod(context.Background(), &NetworkPodConfig{
			Type: podType, Scheduling: NonGatewayNode,
		}).Pod

		container := pod.Spec.Containers[0]
		g.Expect(container.SecurityContext.ReadOnlyRootFilesystem).To(HaveValue(BeTrue()))
		g.Expect(container.SecurityContext.AllowPrivilegeEscalation).To(HaveValue(BeFalse()))
		g.Expect(container.Resources.Limits).NotTo(HaveKey(v1.ResourceCPU))

		var mount v1.VolumeMount
		g.Expect(container.VolumeMounts).To(ContainElement(HaveField("MountPath", "/tmp"), &mount))
		g.Expect(mount.ReadOnly).To(BeFalse())

		var volume v1.Volume
		g.Expect(pod.Spec.Volumes).To(ContainElement(HaveField("Name", mount.Name), &volume))
		g.Expect(volume.EmptyDir).NotTo(BeNil())
		g.Expect(volume.EmptyDir.Medium).To(Equal(v1.StorageMediumDefault))
		g.Expect(volume.EmptyDir.SizeLimit).NotTo(BeNil())
		g.Expect(volume.EmptyDir.SizeLimit.Sign()).To(BeNumerically(">", 0))
	}
}

func newNetworkPodTestClient(t *testing.T) *kubernetes.Clientset {
	t.Helper()

	var lock sync.Mutex
	pods := map[string]*v1.Pod{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		lock.Lock()
		defer lock.Unlock()

		w.Header().Set("Content-Type", "application/json")
		var response any

		switch {
		case r.URL.Path == "/version":
			response = map[string]string{"major": "1", "minor": "37"}
		case r.URL.Path == "/api/v1/nodes":
			response = &v1.NodeList{}
		case r.Method == http.MethodPost && r.URL.Path == "/api/v1/namespaces/test-throughput/pods":
			pod := &v1.Pod{}
			if err := json.NewDecoder(r.Body).Decode(pod); err != nil {
				t.Errorf("decode created pod: %v", err)
				w.WriteHeader(http.StatusBadRequest)

				return
			}

			pod.Name = pod.GenerateName + "test"
			pod.Status.Phase = v1.PodRunning
			pods[r.URL.Path+"/"+pod.Name] = pod
			response = pod
		default:
			pod, found := pods[r.URL.Path]
			if !found {
				t.Errorf("unexpected API request: %s %s", r.Method, r.URL.Path)
				w.WriteHeader(http.StatusNotFound)

				return
			}

			response = pod
		}

		if err := json.NewEncoder(w).Encode(response); err != nil {
			t.Errorf("encode API response: %v", err)
		}
	}))
	t.Cleanup(server.Close)

	client, err := kubernetes.NewForConfig(&rest.Config{Host: server.URL, ContentConfig: rest.ContentConfig{ContentType: "application/json"}})
	if err != nil {
		t.Fatal(err)
	}

	return client
}

func TestThroughputClientRetryExitStatus(t *testing.T) {
	for _, tc := range []struct {
		name             string
		tries            uint
		successOn        int
		expectedAttempts int
		succeeds         bool
	}{
		{name: "all attempts fail", tries: 2, successOn: 3, expectedAttempts: 2},
		{name: "first attempt succeeds", tries: 2, successOn: 1, expectedAttempts: 1, succeeds: true},
		{name: "retry succeeds", tries: 2, successOn: 2, expectedAttempts: 2, succeeds: true},
		{name: "no attempts", tries: 0, successOn: 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			RegisterTestingT(t)
			g := NewWithT(t)
			previousClients, previousSecurityContext := KubeClients, podSecurityContext

			t.Cleanup(func() {
				KubeClients, podSecurityContext = previousClients, previousSecurityContext
			})
			KubeClients = []*kubernetes.Clientset{newNetworkPodTestClient(t)}

			initPodSecurityContext()

			f := &Framework{Namespace: "test-throughput"}
			pod := f.NewNetworkPod(t.Context(), &NetworkPodConfig{
				Type: ThroughputClientPod, Scheduling: NonGatewayNode, ConnectionAttempts: tc.tries,
			}).Pod
			container := pod.Spec.Containers[0]
			scratch := t.TempDir()
			attempts := filepath.Join(scratch, "attempts")
			fakeIperf := "#!/bin/sh\necho run >> \"$ATTEMPT_FILE\"\n" +
				"if [ \"$(wc -l < \"$ATTEMPT_FILE\")\" -ge \"$SUCCESS_ON_ATTEMPT\" ]; then exit 0; fi\nexit 7\n"
			// #nosec G306 -- This private test fixture must be executable.
			g.Expect(os.WriteFile(filepath.Join(scratch, "iperf3"), []byte(fakeIperf), 0o700)).To(Succeed())

			ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
			defer cancel()

			command := strings.ReplaceAll(container.Command[2], "/dev/termination-log", "termination.log")
			// #nosec G204 -- Execute the command emitted by this test with private local fixtures.
			cmd := exec.CommandContext(ctx, container.Command[0], container.Command[1], command)
			cmd.Dir = scratch

			cmd.Env = os.Environ()
			for _, variable := range container.Env {
				cmd.Env = append(cmd.Env, variable.Name+"="+variable.Value)
			}

			cmd.Env = append(cmd.Env, "PATH="+scratch+":"+os.Getenv("PATH"), "RETRY_SLEEP=0",
				"ATTEMPT_FILE="+attempts, "SUCCESS_ON_ATTEMPT="+strconv.Itoa(tc.successOn))
			output, err := cmd.CombinedOutput()
			g.Expect(ctx.Err()).NotTo(HaveOccurred(), string(output))

			if tc.succeeds {
				g.Expect(err).NotTo(HaveOccurred(), string(output))
			} else {
				g.Expect(err).To(HaveOccurred(), "exhausted retries must fail")
			}

			recorded, readErr := os.ReadFile(attempts)
			if !os.IsNotExist(readErr) {
				g.Expect(readErr).NotTo(HaveOccurred())
			}

			g.Expect(strings.Fields(string(recorded))).To(HaveLen(tc.expectedAttempts))
		})
	}
}
