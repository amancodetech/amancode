# CRM Data Service

The only controlled gateway to CRM tables. Agents call these operations and
never mutate tables directly (enforced by an architecture test).

## Operations

- `create_lead / update_lead / get_lead / search_leads`
- `create_customer / update_customer / get_customer`
- `create_opportunity / update_opportunity`
- `create_project / update_project`
- `create_care_plan`
- `append_conversation / get_conversation`

## Entities

leads · conversations · customers · opportunities · projects · care_plans ·
approvals · jobs · events · audit_events · content_items · idempotency_keys ·
usage_records.

See `amancore/storage/schema.sql` for columns/indexes.
