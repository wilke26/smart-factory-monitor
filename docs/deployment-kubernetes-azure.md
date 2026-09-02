# Kubernetes and Azure deployment baseline

## Scope and prerequisites

The manifests under `deploy/kubernetes` deploy the application workloads only. Before
deployment, operators must provide:

- a reachable MQTT 5 broker with TLS and separate simulator/consumer identities;
- a reachable PostgreSQL/TimescaleDB database with migrations already applied;
- a container registry image built with `requirements/ml.lock` if ML will be enabled;
- CA and client certificates issued by the deployment PKI;
- an Ed25519 model-signing public key distributed separately from model artifacts;
- a Kubernetes storage class supporting `ReadWriteMany` for the model registry.
- Kubernetes 1.30 or newer with `ValidatingAdmissionPolicy` available for production
  digest enforcement.

No password, connection string, private key, or certificate is stored in Git.

## Render before applying

```bash
kubectl kustomize deploy/kubernetes/base >/tmp/smart-factory-base.yaml
kubectl kustomize deploy/kubernetes/overlays/azure >/tmp/smart-factory-azure.yaml
```

Edit the broker host and non-secret settings in the base `kustomization.yaml`. Replace
`SMART_FACTORY_ACR` in the Azure overlay with the actual registry name.
This ordinary render is for inspection. A production rollout must use the digest-bound
render described below.

## Create runtime secrets

Create secrets directly through the deployment system or an external-secret controller.
For a manual demonstration:

```bash
kubectl create namespace smart-factory --dry-run=client -o yaml | kubectl apply -f -

kubectl -n smart-factory create secret generic smart-factory-runtime \
  --from-literal=database-url="$DATABASE_URL" \
  --from-literal=consumer-mqtt-username="$CONSUMER_MQTT_USERNAME" \
  --from-literal=consumer-mqtt-password="$CONSUMER_MQTT_PASSWORD" \
  --from-literal=simulator-mqtt-username="$SIMULATOR_MQTT_USERNAME" \
  --from-literal=simulator-mqtt-password="$SIMULATOR_MQTT_PASSWORD"

kubectl -n smart-factory create secret generic consumer-mqtt-tls \
  --from-file=ca.crt="$MQTT_CA_CERT" \
  --from-file=tls.crt="$CONSUMER_MQTT_CERT" \
  --from-file=tls.key="$CONSUMER_MQTT_KEY"

kubectl -n smart-factory create secret generic simulator-mqtt-tls \
  --from-file=ca.crt="$MQTT_CA_CERT" \
  --from-file=tls.crt="$SIMULATOR_MQTT_CERT" \
  --from-file=tls.key="$SIMULATOR_MQTT_KEY"

kubectl -n smart-factory create secret generic model-signing-public-key \
  --from-file=public.pem="$ML_SIGNATURE_PUBLIC_KEY"
```

Do not place literal production values in shell history; the commands illustrate the
required Secret keys only.

## Azure Container Registry and AKS

Build the ML-capable image remotely and attach ACR pull permission to AKS using managed
identity:

```bash
az acr build \
  --registry "$ACR_NAME" \
  --image smart-factory-monitor:0.24.0 \
  --build-arg DEPENDENCY_LOCK=requirements/ml.lock .

az aks update \
  --resource-group "$AKS_RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --attach-acr "$ACR_NAME"

az aks get-credentials \
  --resource-group "$AKS_RESOURCE_GROUP" \
  --name "$AKS_NAME"

IMAGE_DIGEST=sha256:replace-with-the-registry-digest
python deploy/kubernetes/render-release.py \
  --image "$ACR_NAME.azurecr.io/smart-factory-monitor" \
  --digest "$IMAGE_DIGEST" \
  --output /tmp/smart-factory-release.yaml
kubectl apply -f /tmp/smart-factory-release.yaml
kubectl -n smart-factory rollout status deployment/smart-factory-consumer
kubectl -n smart-factory rollout status deployment/smart-factory-alert-dispatcher
```

For v0.24, obtain `IMAGE_DIGEST` and the complete rendered YAML from the matching GitHub
Release. The release workflow builds one `linux/amd64` image with the ML dependency lock,
scans it before publication, pushes the version tag to GHCR, resolves the registry digest,
and records `ghcr.io/<owner>/<repository>@sha256:...` in manifest schema 3. The attached
Kubernetes YAML binds consumer, simulator, and alert dispatcher to exactly that reference.
The semantic registry tag is only a discovery alias and must never be the production
rollout input.

## Enforce digest-only production deployments

Install the cluster-scoped policy with an administrator identity before creating or
labelling the release namespace:

```bash
kubectl apply -k deploy/kubernetes/policies
kubectl get validatingadmissionpolicy,validatingadmissionpolicybinding \
  release-images.smart-factory-monitor.io
```

The Azure namespace carries
`security.smart-factory-monitor.io/require-digest-images=true`. After admission
registration has propagated, use a server-side dry run to confirm that a Deployment with
an image such as `smart-factory-monitor:0.24.0` is denied. Only then apply the
digest-bound release YAML. The ordinary Azure overlay deliberately retains a review tag
and will be rejected in the protected namespace.

The policy covers all normal and init-container images in every Deployment in the opted-in
namespace. It uses `failurePolicy: Fail` with `Deny` and `Audit`; evaluation errors and
nonconforming references therefore block the API request. A digest proves byte identity,
not publisher identity: signature/provenance verification and registry authorization
remain separate deployment controls.

When enabled for a public or Enterprise Cloud repository, GitHub separately attests the
checksummed release files and the published container name plus digest. Without that
facility, the checksummed release manifest, encrypted container SBOM, digest pull, and
attached deployment YAML remain independently verifiable evidence.

For an ABAC-enabled ACR, use the repository-reader role assignment described by Azure
instead of `--attach-acr`. The Azure overlay uses `azurefile-csi-premium` because the model
registry is mounted read-only by the consumer but must remain writable by controlled model
operations. It requests 100 GiB to match current Premium Azure Files provisioning bounds.

The signing private key is intentionally absent from the application manifests. A
controlled external training job must hold it and publish signed candidates. A separate
promotion job needs database evidence, the public key, and write access to publish
content-addressed versions plus the active manifest. Never place the private key in the
shared model claim. The consumer
mounts only the public-key Secret.

The alert dispatcher reads its webhook endpoint and retry policy from the generated
ConfigMap, its database URL from `smart-factory-runtime`, and the optional
`alert-webhook-token` from that same Secret. The consumer receives no webhook credential;
it only needs the non-secret endpoint setting to enable transactional outbox creation.
Replace the example endpoint before deployment. For a private webhook CA, add a dedicated
read-only Secret mount and set `ALERT_WEBHOOK_CA_CERT_PATH` in the overlay.

## Network-policy boundary

The base applies default-deny ingress and egress to application pods, then permits DNS,
consumer monitoring ingress on 8000, MQTT/TLS egress on 8883, webhook HTTPS egress on 443,
and PostgreSQL egress on 5432. The cluster CNI must enforce Kubernetes `NetworkPolicy`.

Standard policy cannot select an external managed service by hostname. The portable base
therefore permits the broker/database ports to any IPv4 address. Before production use,
add overlay-specific `ipBlock` CIDRs or a CNI-native FQDN policy for the actual managed
broker, database, and webhook endpoints. If custom ports or IPv6 are used, update and
re-render the policy deliberately.

## Operational checks

```bash
kubectl -n smart-factory get pods,pvc,service
kubectl -n smart-factory port-forward service/smart-factory-consumer 8000:8000
curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metrics
```

Production rollout still needs endpoint-specific network destinations, managed broker ACL
creation, certificate/credential/signing-key rotation, schema-migration automation,
managed database and model-registry backups with tested restore procedures, durable metrics and alert escalation policy, human model approval, registry
generation retention, externally pinned audit roots, and controlled signing-key rotation.
