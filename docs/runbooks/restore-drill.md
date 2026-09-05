# Staging restore drill (G0a)

Recovery targets until proven otherwise: backup RPO ≤ 5 minutes, RTO ≤ 30 minutes.

Managed Postgres: Multi-AZ + PITR.
Private object store (no public ACLs).
TLS at load balancer.
Secret rotation via the platform secret store (never commit secrets).

See `infra/terraform/main.tf` for the staging skeleton. Do not enable Kafka, event partitioning, or SFU autoscale until G7 measurements show a bottleneck (`event` stays unpartitioned through the 200-seat gate).
