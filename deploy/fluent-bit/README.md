# Fluent Bit Log Forwarder for LogScope AI

This directory provides the production configuration to deploy [Fluent Bit](https://fluentbit.io/) as a lightweight, high-performance node agent that collects container, host, and application logs and forwards them to LogScope AI.

## Quick Start (Docker Compose)

The official `fluent/fluent-bit:latest` image is pre-wired into `docker-compose.yml` under the `collector` profile.

To start LogScope with the Fluent Bit collector:
```bash
docker compose --profile collector up -d
```

## Kubernetes DaemonSet Deployment

To run Fluent Bit on every node in a Kubernetes cluster:

1. Create a ConfigMap from this directory:
   ```bash
   kubectl create configmap fluent-bit-config \
     --from-file=fluent-bit.conf \
     --from-file=parsers.conf \
     -n logscope
   ```

2. Mount the ConfigMap and node log directory (`/var/log`) into the standard `fluent/fluent-bit` DaemonSet:
   ```yaml
   apiVersion: apps/v1
   kind: DaemonSet
   metadata:
     name: fluent-bit
     namespace: logscope
   spec:
     selector:
       matchLabels:
         app: fluent-bit
     template:
       metadata:
         labels:
           app: fluent-bit
       spec:
         containers:
         - name: fluent-bit
           image: fluent/fluent-bit:latest
           env:
           - name: LOGSCOPE_HOST
             value: "logscope-service.logscope.svc.cluster.local"
           - name: LOGSCOPE_PORT
             value: "8000"
           - name: LOGSCOPE_ENV
             value: "production"
           volumeMounts:
           - name: config
             mountPath: /fluent-bit/etc
           - name: varlog
             mountPath: /var/log
             readOnly: true
         volumes:
         - name: config
           configMap:
             name: fluent-bit-config
         - name: varlog
           hostPath:
             path: /var/log
   ```

## Architecture & Features

- **Backpressure Protection**: File-backed storage buffer (`Storage.type filesystem`) ensures zero log loss even if LogScope undergoes rolling restarts.
- **Auto-enrichment**: Automatically tags logs with `application`, `environment`, and `source_name`.
- **Health Metrics**: Fluent Bit exports Prometheus metrics and health check endpoints on port `2020` (`http://localhost:2020/api/v1/metrics`).
