# Kubernetes and Azure deployment baseline

## Scope and prerequisites

The manifests under `deploy/kubernetes` deploy the application workloads only. Before
deployment, operators must provide:

- a reachable MQTT 5 broker with TLS and separate simulator/consumer identities;
- a reachable PostgreSQL/TimescaleDB database with migrations already applied;
- a container registry image built with the `ml` extra if ML will be enabled;
- CA and client certificates issued by the deployment PKI;
- a Kubernetes storage class supporting `ReadWriteMany` for the model registry.

No password, connection string, private key, or certificate is stored in Git.

## Render before applying

```bash
kubectl kustomize deploy/kubernetes/base >/tmp/smart-factory-base.yaml
kubectl kustomize deploy/kubernetes/overlays/azure >/tmp/smart-factory-azure.yaml
```

Edit the broker host and non-secret settings in the base `kustomization.yaml`. Replace
`SMART_FACTORY_ACR` in the Azure overlay with the actual registry name.

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
```

Do not place literal production values in shell history; the commands illustrate the
required Secret keys only.

## Azure Container Registry and AKS

Build the ML-capable image remotely and attach ACR pull permission to AKS using managed
identity:

```bash
az acr build \
  --registry "$ACR_NAME" \
  --image smart-factory-monitor:0.8.1 \
  --build-arg 'PROJECT_INSTALL=.[ml]' .

az aks update \
  --resource-group "$AKS_RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --attach-acr "$ACR_NAME"

az aks get-credentials \
  --resource-group "$AKS_RESOURCE_GROUP" \
  --name "$AKS_NAME"

kubectl apply -k deploy/kubernetes/overlays/azure
kubectl -n smart-factory rollout status deployment/smart-factory-consumer
```

For an ABAC-enabled ACR, use the repository-reader role assignment described by Azure
instead of `--attach-acr`. The Azure overlay uses `azurefile-csi-premium` because the model
registry is mounted read-only by the consumer but must remain writable by controlled model
operations. It requests 100 GiB to match current Premium Azure Files provisioning bounds.

## Operational checks

```bash
kubectl -n smart-factory get pods,pvc,service
kubectl -n smart-factory port-forward service/smart-factory-consumer 8000:8000
curl --fail http://127.0.0.1:8000/readyz
curl --fail http://127.0.0.1:8000/metrics
```

Production rollout still needs policy-specific network controls, broker ACL creation,
certificate and secret rotation, schema-migration automation, backups, monitoring/alerts,
and an approved model-promotion workflow.
