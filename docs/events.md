# Events

Canonical in-process events.

## CanonicalEvent fields

event_id · event_type · timestamp · source · channel · actor_type · actor_id ·
correlation_id · causation_id · idempotency_key · risk_level · payload · metadata.

## Event types (subset)

lead.created/updated/scored · conversation.received/updated ·
message.sent/failed · offer.generated · price.calculated ·
negotiation.started · approval.* · proposal.* · deal.won/lost ·
project.* · care_plan.created · followup.* · content.* · job.*.

## Dispatcher

`subscribe(event_type, handler)` + `publish(event)` (isolates handler errors).

## Idempotency

`IdempotencyStore.check/store` — an action with the same key executes once.
