# Deployment — observability migration

## Staging (k3d, chart-built, live now)

- `otel-collector` (OTLP gRPC in → Prometheus exposition out; traces
  accepted and dropped via the debug exporter) + a minimal `prometheus`
  scraping it. This is the floor that keeps the product metrics and the
  KEDA weighted-capacity scaler alive — verified live (the scaler read
  `mdx_dictation_capacity_weight_*_ratio` and scaled 1→2).

## Production (per hosting choice; disable the staging pair)

- **kube-prometheus-stack** owns metrics/alerting/Grafana. Repo
  dashboards (`infra/grafana/dashboards/*`) mount as dashboard
  ConfigMaps (`grafana_dashboard: "1"` labels); alert rules
  (`infra/prometheus/rules/*`, promtool-linted by `make
  check-alert-rules`) load as PrometheusRule objects. Dashboards/alerts
  migrate verbatim — the metric names are unchanged, only the scrape
  topology differs.
- **Tempo** is the trace backend named since ADR-0005; wire the
  collector's traces pipeline to it (replacing the staging `debug` drop);
  Loki per hosting choice.
- The KEDA scaler's `prometheusAddress` flips to
  `prometheus-operated.monitoring` (values-prod).
- **Gauge staleness caveat (found live):** the collector re-exports
  last-known gauges of dead pods; short PromQL lookbacks or
  `last_over_time` guards are needed on per-pod capacity panels after
  scale-in — noted on the capacity dashboard's next revision.

## Standing gates

- `check-no-demo-envvars-in-prod` + `check-k8s-rendered` prove the
  demo/dev escape-hatch envvars absent from prod manifests (CI-enforced
  on every PR).
- `check-metric-names` keeps exported metric names equal to the declared
  instruments, so every dashboard/alert queries a series that exists.
