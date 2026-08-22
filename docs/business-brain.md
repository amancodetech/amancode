# Business Brain

Single source of truth for **what AmanCore believes/allows/offers**.
It is versioned business configuration — NOT CRM state (no leads/customers).

## Sections (see `amancore/business_brain/data/v1.yaml`)

company · services · offers · pricing_policy · market_profiles · icp ·
sales_policy · negotiation_rules · faqs · objections · brand_voice ·
approved_claims · forbidden_claims · claims_requiring_verification ·
portfolio · case_studies · policies · agent_policies · decision_policies.

## Versioning

- v1 = immutable seed (`data/v1.yaml`).
- New versions written to `versions/vNNNN.yaml` + `versions/_index.json`.
- Every version records: created_by, reason, previous_version, approval_status.
- Read: `store.current()`, `store.get(n)`, `store.versions()`, `store.diff(a,b)`.

## Writer (deterministic write path)

```
propose(content, requested_by, reason)  → pending proposal (validated)
approve(proposal_id, approved_by)       → new immutable version + audit
reject(proposal_id, approved_by, reason)
rollback(target_version, ...)           → new version copying target
```

Agents must never write Business Brain directly.
