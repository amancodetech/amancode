# AmanCore — Runtime Architecture & Conversation Behavior Investigation Report

> **Methodology**: Every conclusion is labeled with an evidence standard:
> - **[CONFIRMED]** — directly verified in source code.
> - **[INFERRED]** — logically derived from code but not a single explicit branch.
> - **[UNVERIFIED]** — the repository does not provide enough evidence.

> **Investigation scope**: Read-only inspection of `aman-core/amancore/` source. No code was modified, refactored, or proposed.

---

## 1. Executive Summary

AmanCore has **two parallel execution paths** for customer messages:

1. **Price-intent shortcut** (`coordinator.py`, `_PRICE_INTENT` regex at line 80, check at line 610). When any of 16+ price-related words is matched, the message is **immediately** routed to `_price_or_proposal_reply()`, which **bypasses** RIL, the SalesAgent, the ConversationModel planner, and (unless `scope_under_review` is active) the QualityGuard.

2. **Normal conversation flow** (lines 624–746). The message passes through the RequirementsService (RIL), then the SalesAgent (fact extraction + BANT qualification + objection detection + offer selection), then the ConversationModel planner (`ResponsePlanner.plan()`), then the LLM drafts the reply, then QualityGuard validates it, then it is enqueued to the outbox.

The **root cause of premature pricing** is the price-intent shortcut: it fires on a broad regex, and its T1 branch returns a public starting price range from the Business Brain for **any known service category** — with **no owner approval**, **no scope-completeness gate**, and **no QualityGuard validation** (because `plan=None` is passed to `_queue_reply`).

---

## 2. Relevant Files

| File | Relevant Classes / Functions | Responsibility | Called From | Calls | Importance |
|---|---|---|---|---|---|
| `channels/coordinator.py` | `MessageCoordinator`, `_process_inbound`, `_price_or_proposal_reply`, `_t1_band_reply`, `_t2_estimate_reply`, `_queue_reply`, `_draft_reply`, `_drafter`, `_ExtractionGateRouter` | Channel-neutral inbound orchestration; price shortcut; LLM drafting; outbox enqueue | `webhook_server.build_conversation_stack` | CRM, SalesAgent, ConversationModel, QuoteFlow, ModelRouter, KnowledgeRetriever | **[CONFIRMED] THE central dispatch** |
| `conversation/planner.py` | `ResponsePlanner.plan`, `ConversationModel`, `_ESCALATION_KEYWORDS`, `_SENTIMENT_KEYWORDS` | Pure deterministic conversation planning; produces ResponsePlan (brief, base, question, mode, quality) | coordinator `_process_inbound` | ConversationPolicy, ModeManager, KnowledgeRetriever | **[CONFIRMED] SINGLE steering source** for normal flow |
| `conversation/policy.py` | `ConversationPolicy`, `next_question`, `field_known`, `weights_for`, `detect_service_category`, `detect_industry`, `detect_small_scope`, `gate_b_like_scope` | Deterministic question selection via weighted scoring; category/industry detection | planner, coordinator | (loads YAML config) | **[CONFIRMED] question & category selection** |
| `conversation/modes.py` | `ModeManager`, `initial_mode`, `advance` | Conversation MODE state machine: OPENING→NEED→SHAPING→COMMERCIAL→NEGOTIATION | planner | policy | **[CONFIRMED] mode state machine** |
| `conversation/pricing_flow.py` | `QuoteFlow`, `gate_b_ready`, `estimate`, `request_owner_approval`, `approved_snapshot` | T2 estimate computation + Gate-B check + owner approval + snapshots | coordinator `_price_or_proposal_reply` | registry, crm | **[CONFIRMED] pricing gate + engine** |
| `conversation/quality_guard.py` | `QualityGuard.check` | Pre-send validation: unauthorized numbers, foreign names, question budget, mode consistency, scope_under_review | coordinator `_queue_reply` | policy | **[CONFIRMED] response validation (bypassed when plan=None)** |
| `conversation/memory_reducer.py` | `inject_context`, `reduce_memory`, `summarize_turn` | Rolling summary / context compaction for LLM | planner `_with_interaction` | — | **[CONFIRMED] long-conversation memory** |
| `agents/sales.py` | `SalesAgent.process_message`, `_build_facts`, `extract_facts`, `compute_fit`, `select_offer` | Legacy sales agent: fact extraction, BANT qualification, objection detection, offer selection | coordinator `_process_inbound` | ConversationMemory, QualificationEngine, DiscoveryEngine, FitEngine, ObjectionHandlingSkill, KnowledgeRetriever | **[CONFIRMED] pre-planner processing (still runs)** |
| `sales/conversation_memory.py` | `ConversationMemory`, `get_or_create`, `save`, `merge_facts`, `extract_facts`, `_deterministic_facts`, `detect_scope_delta`, `SCOPE_DELTA_MAP`, `JSON_FIELDS` | CRM-backed conversation state persistence; fact extraction; scope-delta detection | SalesAgent, coordinator | crm | **[CONFIRMED] memory + fact store** |
| `sales/discovery.py` | `DiscoveryEngine.next_question`, `PRIORITY`, `TEMPLATES` | Legacy questionnaire path: first missing field from PRIORITY | SalesAgent (legacy path only) | — | **[CONFIRMED] OLD question selection** (still present, bypassed by planner) |
| `sales/qualification.py` | `QualificationEngine.qualify` | BANT-derived qualification scoring | SalesAgent | — | **[CONFIRMED] qualification gate** |
| `sales/fit.py` | `compute_fit` | Fit/qualification scoring from brain + facts | SalesAgent | — | **[CONFIRMED] fit scoring** |
| `sales/state_machine.py` | `STATES`, `TRANSITIONS`, `transition`, `can_transition` | CRM lead stage FSM: new→contacted→…→onboarding | SalesAgent | — | **[CONFIRMED] CRM stage FSM** |
| `sales/handoff.py` | `HandoffService`, `request_human`, `can_send_ai`, `modes` | Human takeover: AI_ACTIVE→HUMAN_REQUESTED→HUMAN_ACTIVE→AI_RESUMED→CLOSED | coordinator | channels policy | **[CONFIRMED] human handover** |
| `skills/objection_handling.py` | `ObjectionHandlingSkill.classify` | Objection classification: price_high, want_discount, need_think, etc. | SalesAgent | — | **[CONFIRMED] objection detection** |
| `pricing/offer.py` | `select_offer`, `recommendation_message` | Offer selection based on qualification | SalesAgent | pricing/engine, registry | **[CONFIRMED] recommendation logic** |
| `pricing/engine.py` | `PricingEngine.price` | Hour-based cost computation with complexity multipliers | QuoteFlow | registry | **[CONFIRMED] pricing computation** |
| `routing/models.py` | `ROUTINE`, `EXTRACTION`, task-class constants | LLM task-class identifiers | coordinator `_drafter`, extractor | — | **[CONFIRMED] LLM routing config** |
| `channels/webhook_server.py` | `build_conversation_stack`, `build_runtime` | Production composition root: wires all services | FastAPI handler | all services above | **[CONFIRMED] composition root** |
| `channels/policy.py` | `ChannelPolicyEngine`, `evaluate_send`, `opt_out_blocks_marketing` | Channel delivery policy | coordinator `_queue_reply` | brain | **[CONFIRMED] delivery gating** |
| `channels/routing/router.py` | `IntentRouter` | NOT FOUND — router is at `channels/routing/` | — | — | see `support/intent.py` |
| `support/intent.py` | `IntentRouter.classify_domain` | Deterministic domain routing: legal/billing/complaint/support/sales/general | coordinator | — | **[CONFIRMED] domain intent routing** |
| `crm/service.py` | `CRMService`, `create_lead`, `find_lead_by_identity`, `get_opportunity_for_lead`, `append_conversation`, `get_conversation_for_lead`, `update_lead`, `create_opportunity`, `list_requirements_for_lead` | SQLite-backed CRM: leads, opportunities, conversations, channel messages | coordinator, SalesAgent, ConversationModel, RIL | schema | **[CONFIRMED] persistence layer** |
| `storage/schema.sql` | `conversations`, `channel_messages`, `leads`, `opportunities`, `requirements`, `proposals`, `snapshots`, `channel_ai_settings` | Database schema | CRM | — | **[CONFIRMED] data model** |
| `configs/conversation_policy.yaml` | (data) `question_weights`, `commercial_boost`, `suggestion_triggers`, `suggestion_clarifiers`, `request_verbs`, `commercial_signals`, `affirmations`, `service_categories`, `field_satisfied_by`, `small_scope_triggers`, `budget_weight_outside_commercial` | Conversation strategy configuration | ConversationPolicy.load | — | **[CONFIRMED] strategy config** |
| `configs/models.yaml` | (data) task-routing table: `{routine: {primary: google/gemini-3.6-flash, secondary: glm/glm-5.3-flash, fallback: null}}` | LLM provider routing | `build_providers` / `ModelRouter` | — | **[CONFIRMED] model routing** |
| `amancore/business_brain/data/v1.yaml` | `services`, `industry_profiles`, `price_bands_public`, `claims`, `objections`, `market_profiles` | Business Brain: service catalog, pricing bands, industry knowledge | ConversationModel, QuoteFlow, KnowledgeRetriever, CRM | — | **[CONFIRMED] factual / pricing knowledge source** |

---

## 3. Actual Runtime Message Flow

### 3.1 The price-intent shortcut (premature pricing path)

```
Webhook receives WhatsApp message
  ↓
webhook_server.handle_whatsapp_webhook()
  ↓
MessageCoordinator.handle_inbound()
  ↓
MessageCoordinator._intake_single_event(event, summary)
  ↓
MessageCoordinator._process_inbound(msg)
  │
  ├─ [line 500] Lead lookup: find_lead_by_identity / find_lead_by_whatsapp / create_lead
  ├─ [line 520] Consent recording (first message = opt-in)
  ├─ [line 538] Message recorded (message_recorder)
  ├─ [line 555] Opt-out check: _OPT_OUT → block
  ├─ [line 562] Language detection
  ├─ [line 563] Memory load: get_or_create(lead_id) → mem dict with facts, working_memory, summary
  ├─ [line 569] _update_scope_review(mem, msg) → reconcile scope-under-review (every turn)
  ├─ [line 574] Opt-out keyword check
  ├─ [line 581] Handover check: handover.can_send_ai() → if False, return (hold)
  ├─ [line 586] Human intent: _HUMAN_INTENT.search(text) → handoff path, return
  ├─ [line 595] Intent routing: IntentRouter.classify_domain(text) → legal/billing/complaint/support
  │             → if support/legal/billing/complaint (existing customer), route to SupportAgent
  │
  ├─ [line 610] ⭐ PRICE INTENT SHORTCUT ⭐
  │   if _PRICE_INTENT.search(text):
  │     └─ _update_scope_review called again inside _price_or_proposal_reply (line 1044)
  │     └─ if scope_under_review → _scope_review_reply() (HARD gate, NO figures)
  │     └─ T3: approved snapshot fingerprint match → deterministic price text (NO LLM)
  │     └─ T2: gate_b_ready() → estimate + owner approval request (LLM for wording)
  │     └─ T1: public_band(category) → public starting range from Brain (NO approval)
  │     └─ T0: _requirement_reply → ONE deterministic question
  │     └─ _queue_reply(plan=price_plan) → plan is None unless scope_under_review
  │           ↳ QualityGuard BYPASSED (plan=None)
  │           ↳ Outbox.enqueue → OutboxWorker drains → channel adapter sends
  │
  └─ return {price_reply: True}  ← NORMAL FLOW NEVER EXECUTES
```

### 3.2 The normal conversation flow (non-price)

```
_process_inbound(msg)  [line 484]
  │
  ├─ [line 500-569] Lead lookup, consent, memory load, _update_scope_review (as above)
  ├─ [line 574-608] Opt-out, handover, human intent, intent routing (as above)
  │
  ├─ [line 610] _PRICE_INTENT.search(text) → False (no price words) → continue
  │
  ├─ [line 624] RIL: RequirementsService.process_message()
  │     → extracts structured requirements, conflicts, coverage, next_question
  │
  ├─ [line 640] Extraction gate: _ExtractionGateRouter wraps router
  │     → if confident deterministic evidence → skip LLM extraction call
  │     → extract_facts(text, router=gate_router) → facts dict (regex + optional LLM)
  │
  ├─ [line 647] SalesAgent.process_message(lead, text)
  │     → extract_facts → merge_facts (conflict detection: re-ask_known)
  │     → QualificationEngine.qualify → BANT score
  │     → DiscoveryEngine.next_question (legacy; only used if conversation is None)
  │     → ObjectionHandlingSkill.classify
  │     → select_offer (if qualified) → recommendation
  │     → state machine transition (CRM stage)
  │     → returns result dict {reply, state, next_action, facts, qualification, objection, recommendation}
  │
  ├─ [line 660] Approval classification: classify_approval(text)
  │     → if approved → _draft_quote_reply → _queue_reply (plan=None)
  │
  ├─ [line 689] if self.conversation is not None:   ← THE NEW PATH (production)
  │     └─ plan = ConversationModel.plan(lead, mem, agent_result, text, ...)
  │         → ModeManager.advance → mode (OPENING/NEED/SHAPING/COMMERCIAL/NEGOTIATION)
  │         → detect industry + service_category
  │         → generate value_payload (industry pack sections/features/goals)
  │         → policy.next_question(category, mode, facts, exclude_field) → weighted question
  │         → determine commercial tier (T0/T1/T2/T3) — see section 14
  │         → _with_interaction → inject memory context, escalation, sentiment, industry data
  │         → produce ResponsePlan {mode, brief, base, question, commercial, quality, working_memory}
  │     └─ ConversationModel.persist(memory, lead_id, working_memory=plan["working_memory"])
  │     └─ _relationship_maintenance (follow-up seeding, rolling summary)
  │     └─ intent_note = plan["brief"]
  │     └─ base = plan.get("base") or ""
  │
  ├─ [line 706] elif result.get("next_action") == "ask_next_question":
  │     (legacy fallback — only when conversation is None)
  │     → intent_note = "discovery stage. ... DISCOVERY PLAYBOOK ..."
  │     → base = raw_reply or _SAFE_FALLBACK
  │
  ├─ [line 289/730] reply = _draft_reply(lead, msg, language, intent_note, base, history)
  │     → cost governor allow? → if blocked, deterministic fallback
  │     → System prompt: "You are AmanCode's assistant... max 55 words... "
  │     → User: "CUSTOMER MESSAGE: ... DRAFT CONTENT: ... RECENT CHAT: ..."
  │     → ModelRouter.route(ROUTINE, messages) → gemini-2.5-flash primary
  │
  └─ [line 743] _queue_reply(lead, mem, msg, reply, corr, plan=plan)
        → response_filter.check(text) → if leak, redraft
        → if plan is not None: QualityGuard.check(text, plan)
            → one strict redraft if violations
            → if still violations → localized _SAFE_FALLBACK
        → channel_policy.evaluate_send(channel, ...) → allow/deny/approval_required
        → outbox.enqueue(...)
        → log.info("outbox.enqueued ...")
```

---

## 4. Actual Call Graph

```
webhook_server.handle_whatsapp_webhook()
    ↓
MessageCoordinator.handle_inbound()
    ↓
MessageCoordinator._intake_single_event(event)
    ↓
MessageCoordinator._process_inbound(msg)
    │
    ├── CRM.find_lead_by_identity / find_lead_by_whatsapp / create_lead
    ├── ConversationMemory.get_or_create(lead_id)        ← load state
    ├── MessageCoordinator._update_scope_review(mem, msg)  ← every turn
    │
    ├── IntentRouter.classify_domain(text)              ← line 595
    │
    ├── _PRICE_INTENT.search(text)                      ← line 610  ⭐
    │   ├── True  → _price_or_proposal_reply()          ← SHORTCIRCUIT
    │   │           ├── _update_scope_review(fresh, msg)
    │   │           ├── _scope_review_reply()           (scope_under_review)
    │   │           ├── QuoteFlow.approved_snapshot()   (T3)
    │   │           ├── _t2_estimate_reply()
    │   │           │   ├── ConversationPolicy.gate_b_ready()   ← Gate-B check
    │   │           │   └── QuoteFlow.estimate()  ← PricingEngine.price()
    │   │           ├── _t1_band_reply()          ← T1 band
    │   │           │   └── ConversationModel.public_band(category)  ← Brain price_bands_public
    │   │           └── _requirement_reply()      ← T0 question
    │   │           └── _draft_reply()            ← LLM (T1/T2 wording only)
    │   │           └── _queue_reply(plan=None or scope_plan)
    │   │           └── RETURN  ← normal flow bypassed
    │   │
    │   └── False → continue to normal flow
    │
    ├── RequirementsService.process_message()        ← RIL (line 624)
    │   ├── RequirementsExtractor.extract()
    │   ├── ConflictDetector.detect_conflicts()
    │   ├── CoverageAnalyzer.analyze()
    │   ├── QuestionEngine.select_best_question()
    │   └── ScopeBuilder.build()
    │
    ├── _ExtractionGateRouter()                       ← line 640
    ├── extract_facts(text, router=gate_router)      ← regex + optional LLM
    ├── ConversationMemory.merge_facts(mem, facts)   ← conflict detection
    │
    ├── SalesAgent.process_message(lead, text)       ← line 651
    │   ├── compute_fit()
    │   ├── QualificationEngine.qualify()
    │   ├── ObjectionHandlingSkill.classify()
    │   ├── select_offer()  (if qualified)
    │   ├── DiscoveryEngine.next_question()  (legacy only)
    │   └── state_machine.transition()
    │
    ├── classify_approval(text)                       ← line 663
    │
    ├── ConversationModel.plan(...)                   ← line 689
    │   ├── ModeManager.initial_mode / advance()
    │   ├── ConversationPolicy.detect_service_category()
    │   ├── ConversationPolicy.detect_industry_with()
    │   ├── KnowledgeRetriever.retrieve()             ← industry pack slice
    │   ├── ConversationPolicy.next_question()        ← weighted question
    │   ├── ConversationPolicy.gate_b_like_scope()    ← commercial tier
    │   └── ResponsePlanner._with_interaction()
    │
    ├── ConversationModel.persist()                    ← save working_memory
    │
    ├── _draft_reply(lead, msg, language, intent_note, base, history)
    │   ├── cost_governor.allow(gov_key)             ← cost gate before LLM
    │   ├── ModelRouter.route(ROUTINE, messages)     ← gemini-2.5-flash
    │   └── fallback: _deterministic_voice_reply / _SAFE_FALLBACK
    │
    └── _queue_reply(lead, mem, msg, reply, corr, plan=plan)
        ├── ExternalResponseFilter.check(text)        ← data leak prevention
        ├── QualityGuard.check(text, plan)            ← validated
        ├── ChannelPolicyEngine.evaluate_send()
        └── MessageOutbox.enqueue() → OutboxWorker.drain() → adapter.send()
```

---

## 5. Conversation State Machines

### 5.1 CRM Lead Stage FSM (`sales/state_machine.py`)

| State | Purpose | Entry Condition | Exit Condition | Transitions | Who Changes It | Persistence |
|---|---|---|---|---|---|---|
| `new` | Lead just created | First message received, no prior interaction | Any message event | `first_message` → `contacted` | `transition()` in SalesAgent | `leads.stage` column in CRM |
| `contacted` | Lead contacted | First message processed | Second message | `message` → `engaged` | SalesAgent | `leads.stage` |
| `engaged` | Active conversation | Repeated engagement | Discovery starts | `discovery` → `discovery` | SalesAgent | `leads.stage` |
| `discovery` | Requirements gathering | SalesAgent process | Qualified → offer | `qualified` → `qualification`; `message` → `discovery` (self-loop) | SalesAgent | `leads.stage` |
| `qualification` | BANT scored | Readiness = all required facts | Offer recommended | `recommended` → `offer_recommended` | SalesAgent | `leads.stage` |
| `offer_recommended` | Offer prepared | `select_offer()` returns | Proposal/OFFER | `proposal` → `proposal`; `lost` → `lost` | SalesAgent | `leads.stage` |
| `proposal` | Commercial proposal | Proposal shown | Negotiation/Won | `negotiation` → `negotiation`; `won`/`lost` → (owner override) | SalesAgent | `leads.stage` |
| `negotiation` | Back-and-forth | Objection detected in COMMERCIAL | Decision/Won/Lost | `awaiting` → `awaiting_decision`; `won`/`lost` → (owner override) | SalesAgent | `leads.stage` |
| `awaiting_decision` | Waiting on buyer | Post-negotiation | Won/Lost | `won`/`lost` → (owner override) | SalesAgent | `leads.stage` |
| `onboarding` | Implementation | Won | Terminal | — | SalesAgent | `leads.stage` |

**CRITICAL FINDING**: This CRM stage FSM is **separate** from the conversation MODE state machine (5.2). The CRM stage only advances via `SalesAgent.process_message()`, which is **bypassed entirely by the price-intent shortcut** (line 610). When the customer asks about price, no stage transition occurs.

### 5.2 Conversation Mode State Machine (`conversation/modes.py` `ModeManager`)

Modes answer: **how should the AI behave right now?**

```
OPENING
   ↓ (service_category or request_verb or commercial_signal detected)
NEED
   ↓ (structure_proposed=true on agent reply, OR recommendation_ready)
SHAPING
   ↓ (commercial_signal detected, OR affirmation + price ask, OR recommendation_ready)
COMMERCIAL
   ↓ (objection detected in COMMERCIAL/OFFER)
NEGOTIATION  →  return to COMMERCIAL
```

| Mode | Purpose | Entry Condition | Exit Condition | Who Changes It | Persistence |
|---|---|---|---|---|---|
| **OPENING** | First-contact greeting | `first_turn = not wm.get("mode")` | service_category detected, or request_verb, or commercial_signal | `ModeManager.initial_mode()` | `working_memory.mode` (JSON in `conversations` table) |
| **NEED** | Value-first proposal | service_category set, or "commercial_signal" | `structure_proposed=True` on agent reply → SHAPING; `recommendation_ready=True` → COMMERCIAL | `ModeManager.advance()` | `working_memory.mode` |
| **SHAPING** | Collaborative solution building | `structure_proposed` flag cleared on customer affirmation | `recommendation_ready` → COMMERCIAL; `commercial_signal` or `_affirms_and_asks_price` → COMMERCIAL | `ModeManager.advance()` | `working_memory.mode` |
| **COMMERCIAL** | Pricing discussion | From NEED (recommendation) or SHAPING (commercial signal) | Objection (price_high/want_discount) → NEGOTIATION | `ModeManager.advance()` | `working_memory.mode` |
| **NEGOTIATION** | Objection handling | Objection in COMMERCIAL/OFFER | Affirmation → return_mode (COMMERCIAL); stays in NEGOTIATION | `ModeManager.advance()` | `working_memory.mode` |
| **OFFER** | (reserved, not wired) | Requires approved snapshot | — | — | `working_memory.mode` |
| **DECISION** | (reserved) | — | — | — | — |
| **FOLLOW_UP** | (reserved) | — | — | — | — |

**Interaction between the two FSMs**:
- The CRM stage FSM is driven by `SalesAgent.process_message()` — it advances `new→contacted→engaged→discovery→qualification→offer_recommended→proposal→negotiation→…`.
- The MODE FSM is driven by `ModeManager.advance()` inside `ConversationModel.plan()` — it advances `OPENING→NEED→SHAPING→COMMERCIAL→NEGOTIATION`.
- **They run in parallel**: `plan()` is called after `sales_agent.process_message()` returns. Both write to the same `working_memory` JSON.
- **Price-intent shortcut bypasses BOTH**: When `_PRICE_INTENT.search(text)` matches (line 610), the method returns immediately. `SalesAgent.process_message()` is never called, the CRM stage does not advance, and `ModeManager.advance()` never runs for that turn.

### 5.3 Human Handover Mode FSM (`sales/handoff.py` `HandoffService`)

| Mode | Purpose | Entry Condition | Exit Condition | Persistence |
|---|---|---|---|---|
| `AI_ACTIVE` | AI handling | Default | Human requested | `channel_ai_settings.mode` table |
| `HUMAN_REQUESTED` | Awaiting handoff | `_HUMAN_INTENT` regex match | Agent accepts | `channel_ai_settings.mode` |
| `HUMAN_ACTIVE` | Human handling | Agent accepts handoff | Human releases | `channel_ai_settings.mode` |
| `AI_RESUMED` | AI resumes | Human releases | — | `channel_ai_settings.mode` |
| `CLOSED` | No further AI sends | Opt-out | — | `channel_ai_settings.mode` |

**Gate**: `can_send_ai(lead_id, channel)` is checked at line 581 in `_process_inbound`, BEFORE the price-intent shortcut. If the channel is in `HUMAN_ACTIVE` or `CLOSED`, the method returns `{"hold": True}` and nothing is sent.

### 5.4 State diagram (combined)

```
[CRM LEAD STAGE FSM]                    [MODE FSM]                    [HANDOVER FSM]

  new → contacted → engaged →        OPENING → NEED → SHAPING →     AI_ACTIVE
  discovery → qualification →         COMMERCIAL → NEGOTIATION →      ↓ (human
  offer_recommended → proposal →      (OFFER / DECISION reserved)      requested)
  negotiation → …                     ↑                            HUMAN_REQUESTED
                                      │                            ↕
  PRICE-INTENT SHORTCUT bypasses    objection detected           HUMAN_ACTIVE
  ALL of the above (returns         in COMMERCIAL → NEGOTIATION    ↗
  immediately)                      (then affirmation → return)    AI_RESUMED / CLOSED
```

---

## 6. Question Selection Mechanism

### What the system actually checks

**A. Fixed predefined questions?**
**YES** — but only on the legacy path. `DiscoveryEngine.next_question()` (line 35-37 of `sales/discovery.py`) returns the first missing field from `PRIORITY` and looks up a fixed `TEMPLATES[field]` string. However, this path is **bypassed** in production (`build_runtime` always sets `conversation=ConversationModel(...)`).

**B. Missing fields?**
**YES** — the **NEW path** (`ConversationPolicy.next_question()`, policy.py line 312) scores every field by weight, then returns the first MISSING (unsatisfied) one. `field_known(field, facts)` checks `field_satisfied_by` mapping (e.g., `key_features` is satisfied by `facts.scope`).

**C. Weighted fields?**
**YES** — `[CONFIRMED]` `weights_for(category, mode)` returns a dict like `{key_features: 9, integrations: 8, languages: 7, timeline: 5, authority: 4, scale: 4}` for `website` in `NEED` mode. In `COMMERCIAL` mode, additional `commercial_boost` weights are applied (`budget_band: 9, timeline: 8, authority: 7`). Budget is weighted `0` outside COMMERCIAL.

**D. LLM reasoning?**
**NO** for question selection. `[CONFIRMED]` `next_question` is a pure deterministic function: iterate fields sorted by weight descending, return first unsatisfied field. The LLM is only used to **word** the question.

**E. Domain-specific playbooks?**
**YES** — `[CONFIRMED]` `suggestion_clarifiers` in the policy (per-industry, e.g., `restaurant`, `association_ngo`). When the customer delegates ("اقترح لي"), the planner enters SUGGEST-INTAKE and asks easy-choice questions one at a time with ready options.

**F. Previous conversation context?**
**YES** — `[CONFIRMED]` `exclude_field=wm.get("last_question_field")` prevents re-asking the same field. Also `facts` (accumulated from previous turns) drive `field_known`. Also `_recent_history()` feeds the last 8 messages to the LLM for rephrasing.

**G. Project state?**
**YES** — `[CONFIRMED]` facts dict (budget, scope, timeline, users, authority, etc.) is loaded from CRM conversation memory and consulted by `field_known`.

**H. Customer intent?**
**YES** — `[CONFIRMED]` Intent queue: `wm.get("intent_queue")` holds multi-intent categories. If a customer mentions two services, the primary drives the current turn, the rest queue and resume on a later turn.

**I. Can it generate a question never explicitly predefined?**
**NO** — `[CONFIRMED]` Questions are selected from a fixed field list (`key_features`, `integrations`, `languages`, `timeline`, `authority`, `scale`, `budget_band`, `current_process`, `desired_outcome`, `problem`). The LLM only rewords them. No open-ended question generation.

**J. Can it decide NOT to ask a question?**
**YES** — `[CONFIRMED]` `next_question` returns `None` when all fields are known or all have weight ≤ 0. In that case, the brief says "Do NOT ask any question this turn."

**K. Can it ask a follow-up based on the exact previous answer?**
**YES** — `[CONFIRMED]` `recent_history` (last 8 messages) is passed to the LLM as "RECENT CHAT" with the instruction "NEVER repeat a question already present in RECENT CHAT." So the LLM can ask a contextual follow-up. However, the *field* selection is still from the weighted missing-field logic, not from LLM reasoning about the previous answer.

**L. Can it decide another topic is more important than the current missing field?**
**YES** — `[CONFIRMED]` `intent_queue` mechanism (planner.py line 111-124). If the customer mentions multiple industries/services in one message, the primary category's question is asked first, and other categories are queued. On the next turn, queued categories are resumed even if the current missing field has a higher weight. Also, `_affirms_and_asks_price` can jump to COMMERCIAL mode.

### The exact `next_question` algorithm (`conversation/policy.py` lines 312-327):

```python
def next_question(self, category, mode, facts, exclude_field=None):
    weights = self.weights_for(category, mode)       # weighted score per field
    best_field, best_w = None, 0
    for field, weight in sorted(weights.items(), key=lambda kv: -kv[1]):
        if field == exclude_field or weight <= 0:    # skip last asked or zero-weight
            continue
        if not self.field_known(field, facts):        # skip satisfied fields
            best_field, best_w = field, weight
            break                                     # highest-weight missing wins
    if best_field is None or best_w <= 0:
        return None                                   # all known
    hint = self.data["question_hints"].get(best_field, {}).get("en", "")
    return best_field, hint
```

**Decision process**: Sort fields by weight descending → skip excluded (last asked) → skip satisfied → return first remaining.

**Priority system**: Weights from `question_weights[category]` × `commercial_boost` (in COMMERCIAL mode). Budget weight capped to 0 outside COMMERCIAL.

**Missing-field logic**: `field_known(field, facts)` iterates `field_satisfied_by[field]` aliases and checks `facts.get(alias)` truthiness.

**Exclusion logic**: `exclude_field = wm.get("last_question_field")` — the last field that was asked.

**Output**: `(field_name, hint_string)` or `None`.

---

## 7. Requirement Extraction Audit

### Requirement extractor

**A. Requirement extractor** — `[CONFIRMED]` Two layers:
1. **Deterministic** (`_deterministic_facts` in `sales/conversation_memory.py` line 38): regex-based extraction of `budget`, `authority`, `timeline`, `problem`, `desired_outcome`, `current_process`, `scope`, `pages`, `users`, `payment_gateways`, `languages`, plus scope-delta fields (`booking`, `payments`, `integrations`, `languages`, `member_areas`, `dynamic_content`).
2. **LLM-assisted** (`extract_facts` in `sales/conversation_memory.py` line 74): optional LLM extraction via `_ExtractionGateRouter` — skipped when deterministic evidence is confident.

**B. Fact extractor** — `[CONFIRMED]` Same as above. The `RequirementsExtractor.extract()` (RIL) is a separate, more structured system with `requirement_id`, `subcategory`, `source_message_id`, `confidence`, etc.

**C. Intent extractor** — `[CONFIRMED]` `IntentRouter.classify_domain()` — deterministic keyword-based: legal, billing, complaint, support, sales, general.

**D. Classification** — `[CONFIRMED]` Facts are stored as key-value pairs in the `facts` JSON field. RIL requirements are stored in `requirements` table with `category`, `subcategory`, `requirement_type`, `source_message_id`.

**E. Normalization** — `[CONFIRMED]` `_deterministic_facts` normalizes some fields (e.g., budget strings, scale numbers). RIL uses `RequirementsExtractor` with structured models.

**F. Confidence** — PARTIAL. RIL requirements have a `confidence` field (in `requirements` table schema). Conversation memory facts do NOT have confidence. The extraction gate (`_ExtractionGateRouter`) makes an all-or-nothing skip decision, not a confidence score.

**G. Certainty** — `[UNVERIFIED]` No explicit "certainty" field or state exists in the codebase. Confidence is used in RIL but "certainty" as a distinct concept is NOT IMPLEMENTED.

**H. Persistence** — `[CONFIRMED]` Facts persisted as JSON in `conversations.facts`. RIL requirements in `requirements` table. `working_memory` as JSON in `conversations.working_memory`.

**I. Conflict detection** — `[CONFIRMED]` Two mechanisms:
1. `ConversationMemory.merge_facts()`: when a non-empty fact value differs from existing, adds `"clarify {field}"` to `open_questions`.
2. `ConflictDetector.detect_conflicts()`: operates on RIL requirements (checks for contradictions across messages).

### Requirement states (explicit / inferred / assumed / unknown / confirmed / rejected / conflicting)

**`explicit`** — `[CONFIRMED]` — `_deterministic_facts` and `extract_facts` detect facts directly from the message text (e.g., "6 pages" → `pages=6`).

**`inferred`** — `[INFERRED]` — The RIL `RequirementsExtractor` classifies requirements by `requirement_type` (explicit, inferred, assumed). But for conversation memory facts, there is no explicit "inferred" label — `_deterministic_facts` either matches a regex or doesn't.

**`assumed`** — `[NOT IMPLEMENTED]` for conversation memory facts. RIL may mark some as "assumed" (e.g., `suggestion_active` is an assumption when customer delegates), but this is operational state, not a requirement classification.

**`unknown`** — `[CONFIRMED]` — Facts not present in the `facts` dict. The `unknown` JSON field in conversations table stores a list of unknown items.

**`confirmed`** — `[NOT IMPLEMENTED]` — There is no explicit "confirmed" state. `merge_facts` overwrites old values, and `field_known` checks truthiness. There is no confirmation flag.

**`rejected`** — `[PARTIAL]` — `_withdrawn_fields` in the coordinator sets `facts[f] = False` when a field is explicitly withdrawn (e.g., "I don't want booking"). This is a form of rejection at the scope level, not at the individual requirement level.

**`conflicting`** — `[PARTIAL]` — `merge_facts` adds a `"clarify {field}"` question to `open_questions` when a new fact value differs from the existing one. `ConflictDetector` in RIL checks for contradictions. However, neither mechanism actually asks the customer for clarification in the conversation flow — `open_questions` is stored but NOT surfaced to the customer. The price shortcut also bypasses this entirely.

---

## 8. Implicit Requirement Handling

### What happens when a customer says:

> "I want something like Airbnb."

`detect_service_category("I want something like Airbnb")` → NO service keyword match (Airbnb is not in the brand/service keyword list) → category = None. The system detects "request_verb" ("want") → mode = NEED. The planner brief says "The request is too vague to advise yet" and asks what kind of activity/build they have in mind. **No hidden implications extracted** — `[CONFIRMED]` no brand-mapping logic exists.

> "Like Noon but for spare parts."

Same as above — "Noon" and "spare parts" are not service keywords. Category = None. System asks for clarification.

> "I need a system like Haraj."

Same — "Haraj" is not a service keyword. No hidden implication extraction.

> "We want customers to pay by card and Mada."

`detect_scope_delta("We want customers to pay by card and Mada.")` → matches `payments` pattern ("pay", "دفع") → adds `payments` to scope_review_fields. `_deterministic_facts` also extracts `payment_gateways`. The system notes this as a scoped expansion. **Partial extraction of implications** — `[CONFIRMED]` payment method → `payment_gateways` fact + `payments` scope delta.

> "We may add a mobile app later."

`detect_scope_delta("We may add a mobile app later.")` → does NOT match "mobile" or "app" keywords in SCOPE_DELTA_MAP. The word "mobile" is in the `mobile_app` service category keywords, but scope_delta doesn't check for it. **No implication extracted** — `[CONFIRMED]` "may add" is future tense and the scope delta map doesn't capture it.

> "I don't know what payment system I need."

`_UNCERTAIN_CUES.search("I don't know what payment system I need.")` → matches "don't know" → extraction gate will NOT skip LLM. The message lacks service keywords → category = None. System asks clarifying questions. **No suggestion offered** at this point.

> "You decide what is best."

`suggestion_triggers` detection (planner.py line 298-300): "you decide" matches `suggestion_triggers` — but only in SHAPING mode (requires `sections` to exist, which requires a detected industry+category). If the customer hasn't yet specified what they want, the system can't enter SUGGEST-INTAKE. In the price shortcut path, this is not checked at all.

### Determined capabilities:
- `[CONFIRMED]` **extracts hidden implications**: Limited — `_deterministic_facts` extracts payment gateways, scale numbers, etc. from keyword patterns. No semantic inference.
- `[CONFIRMED]` **suggests missing requirements**: YES — via `SuggestionClarifiers` (SUGGEST-INTAKE) when customer delegates in SHAPING mode.
- `[INFERRED]` **infers architecture**: The `value_payload` (sections, features, goals) from industry packs serves as an implicit architecture proposal, but it's industry-template-based, not inferred from customer input.
- `[CONFIRMED]` **asks contextual follow-up questions**: YES — `recent_history` + "NEVER repeat a question already present in RECENT CHAT" lets the LLM ask contextual follow-ups.
- `[PARTIAL]` **offers alternatives**: The SUGGEST-INTAKE flow offers ready-choice options for clarifier fields. The recommendation path (via `select_offer`) can propose a service by name.
- `[CONFIRMED]` **does nothing**: Many implicit statements (brands like Airbnb/Haraj) produce NO extraction — the system just asks "what do you want to build?"

---

## 9. Recommendation Engine Audit

### Sources of recommendations

**1. Industry packs** (`business_brain/data/v1.yaml` → `industry_profiles`): Each industry profile has `typical_sections`, `features`, `goals`, `common_pain_points`, `common_processes`, `typical_integrations`. The planner uses these to build `value_payload` (planner.py lines 240-252).

**2. Knowledge pack extensions** (`knowledge/packs/*.yaml`): Loaded by `KnowledgeRetriever` and sliced by mode. Contains `decision_roles` (BANT-lite tone priors), `common_pain_points`, `decision_roles`, etc.

**3. Offer selection** (`pricing/offer.py: select_offer`): `select_offer(brain, qual)` returns a recommendation dict `{service_name, offer_name, message}` based on qualification score. `recommendation_message` formats it.

**4. Service catalog** (`business_brain/data/v1.yaml` → `services`): Each service has `id`, `name`, `description`, `features`, `typical_sections`, `cross_sell`, `relevant_services`, `objections`.

### Capability answers (with evidence)

| Capability | Can it? | Evidence |
|---|---|---|
| Recommend features | **YES** | `value_payload["features"] = features[:4]` (planner.py line 248). Industry pack `features` lists. `[CONFIRMED]` |
| Recommend architecture | **YES** | `value_payload["sections"] = sections[:7]` (planner.py line 247). Sections are architectural building blocks. `[CONFIRMED]` |
| Recommend an MVP | **PARTIAL** | `suggest_clarifiers` → if customer delegates → proposes full structure (planner.py lines 345-361). No explicit "MVP" framing — it proposes "full concrete structure." `[INFERRED]` |
| Recommend phased development | **YES** | Cross-sell hint: "you can also handle {cand} later as an extension" (planner.py line 489). SUGGEST-INTAKE proposes structure incrementally. `[CONFIRMED]` |
| Explain trade-offs | **PARTIAL** | Industry pack `common_pain_points` + `digital_maturity` are data fed as "TAGGED DATA" to the LLM. The brief says "use as DATA only (context to reason about the customer)." Whether the LLM actually explains trade-offs is LLM-dependent. `[INFERRED]` |
| Challenge a customer requirement | **PARTIAL** | Objection handling path (planner.py lines 178-199): the negotiation brief says "reframe the VALUE of solving it properly, then offer to REDUCE SCOPE." This challenges through scope reduction, not direct requirement challenge. Only triggers when `agent_result.get("objection")` is set. `[INFERRED]` |
| Say a proposed solution is not optimal | **NO** | There is no explicit "suboptimal solution" detection. The system always proposes the industry pack's `typical_sections`. No comparison logic. `[CONFIRMED]` NOT IMPLEMENTED |
| Propose alternatives | **YES** | SUGGEST-INTAKE offers ready-choice options for clarifier fields (planner.py lines 313-343). Cross-sell hint suggests extensions. `[CONFIRMED]` |

---

## 10. Memory Architecture

```
┌─────────────────────────────────────────────────────────┐
│  SQLite database (storage/schema.sql)                    │
├─────────────────────────────────────────────────────────┤
│  conversations  table                                    │
│    ├── working_memory   JSON  ← MODE state              │
│    ├── facts            JSON  ← extracted BANT+scope     │
│    ├── requirements     JSON  ← RIL requirements state   │
│    ├── unknowns         JSON  ← unknown items list       │
│    ├── decisions        JSON  ← RIL decision tracking    │
│    ├── open_questions   JSON  ← clarification requests    │
│    ├── objections       JSON  ← objection history         │
│    ├── preferences      JSON  ← customer preferences      │
│    ├── summary          TEXT   ← rolling summary (÷10 msgs)│
│    └── mode, industry, service_category (denormalized)  │
├─────────────────────────────────────────────────────────┤
│  channel_messages  table                                 │
│    ├── direction    'in' | 'out'                         │
│    ├── body         TEXT  ← raw message body             │
│    ├── external_message_id, external_user_id, channel   │
│    └── hidden       0 | 1   ← soft-delete                 │
├─────────────────────────────────────────────────────────┤
│  requirements  table (RIL)                               │
│    ├── requirement_id, lead_id, category, subcategory   │
│    ├── requirement_type, confidence, source_message_id   │
│    └── status (draft/review/final)                       │
├─────────────────────────────────────────────────────────┤
│  opportunities  table                                      │
│    ├── stage (CRM FSM stages)                           │
│    ├── lead_score, fit_score                            │
│    └── proposed_value, proposed_hours                    │
├─────────────────────────────────────────────────────────┤
│  channel_ai_settings  table                              │
│    ├── mode (AI_ACTIVE/HUMAN_ACTIVE/etc.)               │
│    └── ...                                               │
└─────────────────────────────────────────────────────────┘
```

### Memory layers

| Layer | Where stored | Who writes | When updated | Who reads | Retained | Survives restart? | Survives new session? |
|---|---|---|---|---|---|---|---|
| **Raw messages** | `channel_messages.body` | `message_recorder` | Every inbound/outbound msg | `_recent_history()` (last 8), `_recent_assistant_replies()` (last 2) | ALL messages (no deletion) | YES (SQLite) | YES (keyed by channel + external_user_id) |
| **Facts** | `conversations.facts` (JSON) | `SalesAgent.merge_facts` | Every turn (in normal flow) | Planner (`field_known`), price shortcut, quality guard | All extracted facts | YES | YES |
| **Working memory** | `conversations.working_memory` (JSON) | `ConversationModel.persist()` | Every turn (in normal flow) | Planner (`plan()` reads wm), price shortcut (`wm.get("service_category")`) | Mode, industry, service_category, scope_review_fields, etc. | YES | YES |
| **Requirements** | `requirements` table + `conversations.requirements` | `RequirementsService` | Every turn (RIL) | Planner (`requirements_question`, `requirements_coverage`) | All requirements | YES | YES |
| **Rolling summary** | `conversations.summary` (TEXT) | `_relationship_maintenance` (line 1238) | Every 10 inbound messages | Planner (OPENING mode: `mem.get("summary")`) | Last ~220 chars | YES | YES |
| **Conversation summary (memory_reducer)** | In-memory + brief summary in `conversations.summary` | `memory_reducer.inject_context` | Computed on-the-fly per turn | `_with_interaction` → brief (planner.py line 584) | "Last 3 exchanges: ..." (capped) | NO (in-memory, recomputed) | NO |
| **Decisions** | `conversations.decisions` (JSON) | `DecisionTracker` (RIL) | When decisions are detected | — | All | YES | YES |
| **Open questions** | `conversations.open_questions` (JSON) | `ConversationMemory.merge_facts` | When facts conflict | — | Stored but NOT surfaced to customer | YES | YES |
| **Objections** | `conversations.objections` (JSON) | `ObjectionHandlingSkill` | When objections detected | Planner (mode transition to NEGOTIATION) | Stored but NOT actively used in replies | YES | YES |
| **Unknown items** | `conversations.unknowns` (JSON) | RIL | — | — | — | YES | YES |

---

## 11. Long-Conversation Behavior

### Truncation mechanisms

- **`_recent_history`** (coordinator.py line 1379): reads last 8 messages from `channel_messages` table. `[CONFIRMED]` This is the hard context window for the LLM.
- **Rolling summary** (`_relationship_maintenance` line 1238): every 10 inbound messages, a summary is generated via `recent_learnings_summary()` or `ops.learning`. `[CONFIRMED]`
- **`memory_reducer.inject_context`** (planner.py line 584): produces a "Last 3 exchanges:" summary injected into the brief. `[CONFIRMED]`
- **Summary truncation**: `summary[:220]` at planner.py line 230 — the relationship summary is capped to 220 characters. `[CONFIRMED]`

### State persistence

- **SQLite** — ALL persistence is to SQLite. `[CONFIRMED]` This survives restarts and across sessions (keyed by `external_user_id`).
- **`working_memory`** persists mode, industry, service_category, etc. across turns. `[CONFIRMED]`
- **`facts`** persist across turns. `[CONFIRMED]`

### Can an early requirement influence a late decision?

| Property | Status | Evidence |
|---|---|---|
| **STORED** (persisted) | YES | `facts` JSON in `conversations` table. Survives restart. |
| **RETRIEVED** (loaded) | YES | `get_or_create` loads facts every turn. |
| **IN CONTEXT** (LLM receives it) | YES | `facts` → `base` content in `_draft_reply`. Recent messages (8) in `history`. |
| **USED FOR DECISION** | YES | `facts` feed `field_known()` (question selection), `gate_b_ready()` (pricing), `policy.next_question()`. `working_memory.service_category` feeds T1 band. |

However:
- The **"DECISION"** layer only considers facts + current message. It does NOT re-read all raw messages — only the last 8 via `_recent_history` and the `facts` dict. So a fact from message 3 is "used for decision" IF it was extracted into `facts` (by `extract_facts`). If it wasn't extracted, it's in `channel_messages` (stored, retrieved for context) but NOT in `facts` (not used for decision).
- `[CONFIRMED]` The facts dict is the structured memory; raw messages are only for context (anti-repeat, recap).

### Conversation length support

- **20+ messages**: `[CONFIRMED SUPPORTED]` — `_recent_history` reads last 8, summary every 10. Tests go up to 5-7 messages. No explicit test for 20+.
- **40+ messages**: `[INFERRED SUPPORTED]` — facts persist, working_memory persists, summary rolls. No truncation limit on facts. But `_recent_history` only returns last 8 messages — older messages are NOT in LLM context.
- **60+ messages**: `[INFERRED SUPPORTED]` — same as above. The facts dict is the durable memory; the summary provides lightweight context. No hard limit.
- **100+ messages**: `[INFERRED SUPPORTED]` — same mechanism. But no tests. The summary is capped to 220 chars.
- **2+ hours**: `[UNVERIFIED]` — No timestamp-based expiry or staleness check found in code.
- **Multiple sessions**: `[CONFIRMED SUPPORTED]` — SQLite persistence keyed by `external_user_id`. A new session loads the same lead + conversation. `[CONFIRMED]`

---

## 12. Contradiction and Change Handling

### Example:
```
Message 10: "I do not need a mobile app."
Message 35: "Actually I want Android and iOS."
```

### What the code does:

1. **`detect_scope_delta("I do not need a mobile app.")`** → does NOT match any SCOPE_DELTA_MAP patterns. "mobile app" is not a scope delta field. The negation is NOT detected at the scope-delta level.

2. **`_withdrawn_fields("I do not need a mobile app.")`** → also does NOT match (no SCOPE_DELTA_MAP fields). `[CONFIRMED]` "mobile app" is NOT a scope-delta field.

3. The SalesAgent's `extract_facts` would extract... nothing for "mobile app" (it's not a deterministic fact). If the LLM is invoked, it might extract something, but there's no conflict detection between "mobile app: no" and "mobile app: yes."

4. For scope-delta fields (booking, payments, integrations, languages, member_areas, dynamic_content):
   - `merge_facts` (conversation_memory.py line 106): when a non-empty value differs from existing, it adds `"clarify {field}"` to `open_questions`. `[CONFIRMED]` But `open_questions` is **stored but NOT surfaced to the customer** in any reply path. The planner does NOT read `open_questions`. The price shortcut does NOT read `open_questions`.
   - `_withdrawn_fields` (coordinator.py line 109): detects negated scope fields (e.g., "I don't want booking") and sets `facts[f] = False`. `[CONFIRMED]`

5. **`scope_fingerprint`** (pricing/registry.py): The pricing snapshot is invalidated when the scope fingerprint changes (e.g., if `fact.scope` changes). `[CONFIRMED]` But this only affects T3 (approved snapshot reuse).

### System capabilities for contradiction handling:

| Capability | Implemented? | Evidence |
|---|---|---|
| Overwrites | YES | `merge_facts` overwrites old fact values. `[CONFIRMED]` |
| Adds another value | NO | Facts are a single dict, not a list. No history of old vs new. `[CONFIRMED]` NOT IMPLEMENTED |
| Detects contradiction | PARTIAL | `merge_facts` adds to `open_questions` when values differ. `_withdrawn_fields` handles negation. `[CONFIRMED]` |
| Asks for clarification | NO | `open_questions` is stored but NEVER surfaced. `[CONFIRMED]` NOT IMPLEMENTED |
| Records history | NO | No fact history/audit trail. `[CONFIRMED]` NOT IMPLEMENTED |
| Marks old requirement obsolete | NO | No "obsolete" state. `[CONFIRMED]` NOT IMPLEMENTED |
| Updates scope | PARTIAL | `scope_fingerprint` changes on scope change → T3 snapshot invalidated. `[CONFIRMED]` |

**The price shortcut bypasses ALL of this** — `merge_facts` is only called in the normal flow (line 651+), not in the price shortcut path (line 610).

---

## 13. Topic Switching

### Test scenario:
```
Customer: "I need an ecommerce platform."
AI asks about products.
Customer: "What server do you recommend?"
Customer: "Can you integrate Mada?"
Customer: "What about SEO?"
Customer: "I want something like Noon."
Customer: "How much would this cost?"
Customer: "Actually I also need a mobile app."
```

### What the code does:

1. **"I need an ecommerce platform."** → `detect_service_category` matches "ecommerce" keywords → category = "ecommerce" → mode = NEED → planner proposes ecommerce structure, asks first question.

2. **"What server do you recommend?"** → No service category keywords → `category = wm.get("service_category")` = "ecommerce" → mode stays NEED/SHAPING → question selection continues. "server" is not a recognized field, so `next_question` picks the next missing high-weight field. **The system does NOT switch topics — it stays on the current missing field.** `[CONFIRMED]`

3. **"Can you integrate Mada?"** → `detect_scope_delta` matches "integration" keywords (ربط/تكامل) → adds `integrations` to pending scope review. `_deterministic_facts` extracts `payment_gateways`. The system notes this as a scope addition but stays on the current topic.

4. **"What about SEO?"** → `_STANDARDS_TRIGGER_RE` matches "seo" → industry pack standards slice provides "Schema.org v30 structured data" as data to the LLM. The LLM may mention it. The system stays on the current discovery flow.

5. **"I want something like Noon."** → "Noon" is not a service category keyword → no category change. The system continues on "ecommerce".

6. **"How much would this cost?"** → `_PRICE_INTENT.search` matches "cost" → **PRICE SHORTCIRCUIT** → `_price_or_proposal_reply()`:
   - Category from working_memory: "ecommerce"
   - T1 band: ecommerce → {low: 5100, high: 14800} → returns starting range
   - **The system abandons discovery and returns a price.** `[CONFIRMED]`

7. **"Actually I also need a mobile app."** → `detect_service_category` matches "mobile" → category = "mobile" → BUT this is NOT a price question, so the normal flow runs:
   - RIL processes → extracts mobile app as scope_delta? NO — "mobile app" is NOT in SCOPE_DELTA_MAP. `detect_scope_delta("أحتاج تطبيق موبايل أيضاً")` → matches `dynamic_content`? NO. Matches `integrations`? NO. Returns empty.
   - SalesAgent.process_message → `extract_facts` → no "mobile" detection
   - Planner: `detected = ["mobile"]` → category changes to "mobile"
   - Mode might transition. The planner picks up the new category.

**The system CAN handle topic switching** within the normal flow (via `intent_queue` and `service_category`), but the price shortcut interrupts this.

---

## 14. Pricing Trigger Logic

### Every mechanism related to price/pricing/cost/budget/estimate/quote/proposal/commercial:

| Mechanism | Type | What it does |
|---|---|---|
| `_PRICE_INTENT` regex (coordinator line 80) | Deterministic regex | Matches price-related words: price, cost, berapa, harga, سعر, بكم, كم تسوى, كم تكلف, كم ثمن, كم سعر, سيكلف, يكلف, quote, proposal, تسعير, estimate |
| `_PRICE_INTENT.search(text)` (line 610) | Deterministic check | If matched → short-circuit to `_price_or_proposal_reply()` |
| `IntentRouter.classify_domain` | Deterministic | Does NOT classify price as support/sales/legal/billing/complaint. "pricing" is NOT in any of these regex patterns. Price goes through the sales path, not support. |
| `commercial_signals` (policy DEFAULTS) | Deterministic keyword list | Detects commercial signals: سعر, price, cost, budget, التكلفة, تسعير, estimate, quote, etc. Used by ModeManager to transition to COMMERCIAL mode (line 72 of modes.py). This is SEPARATE from `_PRICE_INTENT`. |
| `policy.commercial_signal()` | Deterministic | Returns True if any commercial_signal keyword is in the text. Used by ModeManager.advance(). |
| `_affirms_and_asks_price` (modes.py line 103) | Deterministic | `re.search(r"(سعر|price|harga)", text) and policy.affirmation(text)` — detects affirmation + price question. Used in SHAPING→COMMERCIAL transition. |
| `policy.gate_b_like_scope(facts)` | Deterministic | Checks if key_features + (timeline OR scale) are known. Used in planner COMMERCIAL mode for T2 tier. |
| `QuoteFlow.gate_b_ready()` | Deterministic | Same check but with category. Used in price shortcut T2 path. |
| `policy.weights_for(category, mode)` + `commercial_boost` | Configurable | Budget weighted 9 in COMMERCIAL mode, capped at `budget_weight_outside_commercial` (0) outside. |
| `policy.field_known("budget_band", facts)` | Deterministic | Checks if `facts.budget` is truthy. |
| `policy.detect_small_scope()` | Deterministic | Detects small-scope signals that trigger mini_scope T1 bands. |
| `_VAGUE_BUDGET_CUES` (coordinator line 97) | Deterministic regex | Matches "budget", "ميزانية", "anggaran" without concrete digits → forces LLM extraction (doesn't skip). |
| `_DEFERRAL_AR/EN` (coordinator lines 40-41) | Deterministic strings | Fallback when LLM is unavailable. |
| `price_bands_public` (v1.yaml line 212) | Brain data | Public starting ranges per category: website 1500-4200, ecommerce 5100-14800, mobile 6600-25800, business_system 12100-42600, automation 8100-28400. No approval required. |

### What exact event causes AmanCore to enter pricing?

**[CONFIRMED]** The **ONLY** trigger for the pricing flow is:

```python
# coordinator.py line 610-611
if _PRICE_INTENT.search(text):
    reply = self._localize(self._price_or_proposal_reply(lead, corr, msg=msg), language)
    self._queue_reply(lead, mem, msg, reply, corr, ...)
    return {"lead_id": lead["lead_id"], "reply_sent": True, "price_reply": True}
```

The `_PRICE_INTENT` regex matches if the customer's message contains ANY of these substrings (case-insensitive):

```
price | cost | berapa | harga | سعر | بكم | كم تسوى | كم تكلف | كم ثمن | كم سعر | سيكلف | يكلف | quote | proposal | تسعير | estimate
```

**There is no secondary check.** No Gate-B verification, no scope completeness check, no mode verification, no QualityGuard. The check fires on the **first** price word and immediately short-circuits to `_price_or_proposal_reply()`.

The secondary `commercial_signals` list in the policy (used by `ModeManager`) includes more words but is only used for mode TRANSITION in the normal flow — it does NOT trigger the price shortcut.

---

## 15. Pricing Readiness / Gate Logic

### Exact function: `QuoteFlow.gate_b_ready` (conversation/pricing_flow.py line 1328)

```python
@staticmethod
def gate_b_ready(policy, category, facts):
    if not category:
        return False
    if not policy.field_known("key_features", facts):  # facts.scope must be set
        return False
    if not (policy.field_known("timeline", facts)
            or policy.field_known("scale", facts)):     # facts.timeline or facts.users
        return False
    return True
```

### Gate-B requires:

| Requirement | Field mapping | Evidence |
|---|---|---|
| Category known | `service_category` (from detection or working_memory) | Line 1329 |
| key_features | `field_satisfied_by["key_features"]` — checks `facts.scope` | policy.py line 306-310 |
| timeline OR scale | `field_satisfied_by["timeline"]` — checks `facts.timeline`; `field_satisfied_by["scale"]` — checks `facts.users` or `facts.scale` | policy.py line 306-310 |

### Critical asymmetry:

```
Gate-B applies ONLY to T2. T1 has NO readiness gate.
```

- **T2** (indicative estimate): requires Gate-B (category + key_features + timeline/scale). `[CONFIRMED]`
- **T1** (public starting range): requires ONLY category known. `[CONFIRMED]` No scope, no timeline, no scale required.
- **T3** (approved snapshot): requires a matching scope fingerprint. `[CONFIRMED]` Stricter than both.

### Can a final price be generated while architectural requirements are unknown?

**YES — `[CONFIRMED]`**. The T1 band path returns a price range as soon as the service category is known. A category is detectable from a single word in the customer's message (e.g., "موقع" = website). No architectural requirements (pages, features, integrations, timeline, scale, budget, authority) are checked.

The test `test_t1_engages_in_commercial_brief` (test_p03) confirms this:
```python
plan = self.model.plan(lead={"lead_id": "L"}, mem={"facts": {}},
                       agent_result={},
                       text="كم تستغرق مدة موقع جمعية؟",
                       language="ar", channel="whatsapp")
# facts = {} — EMPTY! No architectural requirements.
# But category = "website" (from "موقع") → T1 fires.
self.assertEqual(plan["commercial"]["tier"], "T1")
```

This test passes `facts: {}` (empty) and still gets T1. `[CONFIRMED]`

---

## 16. Complete Pricing Pipeline

| Stage | File | Function | Input | Output | Decision | Persistence |
|---|---|---|---|---|---|---|
| **Price intent** | coordinator.py:80-84 | `_PRICE_INTENT` regex | customer text | match/no match | regex-based, broad | None |
| **Price shortcut** | coordinator.py:610 | `if _PRICE_INTENT.search(text)` | match | short-circuit | deterministic | None |
| **Scope review** | coordinator.py:824 | `_update_scope_review(fresh, msg)` | message | `scope_under_review` flag | reconciles scope deltas vs facts | `working_memory.scope_under_review` |
| **T3 snapshot** | coordinator.py:1060 | `_price_or_proposal_reply` → snapshot check | approved snap + fingerprint | deterministic price text | fingerprint match | snapshots table |
| **T2 estimate** | coordinator.py:1307 | `_t2_estimate_reply` | Gate-B (category + scope + timeline/scale) | estimate + owner approval | Gate-B check | opportunities table |
| **T1 band** | coordinator.py:1152 | `_t1_band_reply` | category known | public starting range from Brain | category known (NO gate) | brain price_bands_public |
| **T0 defer** | coordinator.py:985 | `_requirement_reply` | no category | ONE requirement question | no category | None |
| **Draft** | coordinator.py:1452 | `_draft_reply` | base + brief + history | LLM-worded reply | LLM (wording only) | None |
| **Quality check** | coordinator.py:1583 | `_queue_reply(plan=...)` | reply text + plan | allowed/blocked, redraft or fallback | QualityGuard.rules | None |
| **Deliver** | coordinator.py:1640 | `outbox.enqueue()` | text + channel + recipient | message_id | channel_policy.evaluate_send | channel_messages, outbox |
| **Drain** | channels/outbox.py | `OutboxWorker.drain()` | queued messages | sends via adapter | — | — |

### T3: Approved Snapshot (lines 1055-1138)

```
opp = crm.get_opportunity_for_lead(lead_id)
snap = snapshots.get_for_opportunity(opp_id)
if snap and snap["approved_price"] is not None:
    if snap["scope_fingerprint"] is None or snap_fp == current_fp:
        → return deterministic price text with specs (NO LLM)
    else:
        → snapshots.supersede(snap_id)  # scope changed, invalidate old
prop = proposals.get_approved_for_opportunity(opp_id)
if prop:
    → return "approved proposal ready" (NO LLM)
```

T3 is a **deterministic short-circuit** — no LLM call, no approval request. The price is frozen from a previously approved snapshot.

### T2: Gate-B Estimate (lines 1307-1375)

```
if not QuoteFlow.gate_b_ready(policy, category, facts):
    return None  # ← falls through to T1
est = QuoteFlow.estimate(lead, category, hours_override, facts, scope_addons, small)
if not est:
    return None  # ← falls through to T1
approval_id = QuoteFlow.request_owner_approval(lead, est, scope_fingerprint)
→ return LLM-drafted T2 text with estimate + "engineering team reviewing"
```

T2 **requests owner approval** — the estimate is sent to the owner for approval before becoming a T3 snapshot. The customer sees "tentative estimate" wording.

### T1: Public Band (lines 1152-1218)

```
category = detect_service_category(msg.text) or wm.service_category
band = ConversationModel.public_band(category)  → brain["price_bands_public"][category]
if not band or band.low is None:
    return None  # ← falls through to T0
→ compose deterministic base text with band.low, band.high, currency
→ call _draft_reply (LLM for wording only)
→ return reply
```

**T1 requires NO approval.** `[CONFIRMED]` The brief says "MODE=COMMERCIAL tier=T1. Convey EXACTLY the starting range..." and the LLM is only asked to word it.

### Price intent → T1/T2 gate flow:

```
_PRICE_INTENT.search(text) → True
    → _price_or_proposal_reply()
        → _update_scope_review(fresh, msg)
        → if scope_under_review → scope_review_reply (HARD gate, NO figures)
        → category = detect_service_category(text) or wm.service_category
        → T3: if approved snapshot + fingerprint match → deterministic price (NO LLM)
        → T2: if Gate-B (key_features + timeline/scale) → estimate + owner approval (LLM)
        → T1: if category known → public band (NO approval, LLM for wording)
        → T0: if no category → ONE requirement question
        → _queue_reply(plan=None or scope_plan)
            → plan=None → QualityGuard BYPASSED
            → plan={"scope_under_review": True} → QualityGuard blocks numbers
```

---

## 17. LLM vs Deterministic Control

| Decision | LLM | Python (deterministic) | Config (YAML/brain) | DB State | Hybrid |
|---|---|---|---|---|---|
| **Next question** | ✓ (wording only) | ✓ (weighted scoring via `next_question`) | ✓ (weights, hints, service_categories) | ✓ (facts → `field_known`, working_memory → `last_question_field`) | hybrid (Python selects field, LLM words it) |
| **Requirement extraction** | ✓ (optional, gated) | ✓ (deterministic regex `_deterministic_facts`) | | ✓ (facts persisted, `open_questions` on conflict) | hybrid |
| **Recommendation** | ✓ (wording of value_payload) | ✓ (`select_offer`, `gate_b_like_scope`) | ✓ (industry_profiles sections/features, `suggestion_clarifiers`) | ✓ (qualification result) | hybrid |
| **Discovery completion** | ✓ (wording) | ✓ (`field_known` — all fields known when `next_question` returns None) | ✓ (`question_weights`) | ✓ (facts) | hybrid |
| **Pricing entry** | ✗ (NONE) | ✓ (`_PRICE_INTENT` regex) | ✓ (`price_bands_public`, `commercial_signals`) | ✓ (`working_memory.category`, `facts`) | Python-dominant |
| **Final price** | ✓ (wording only for T1/T2) | ✓ (T1 bands from brain, T2 from `PricingEngine.price`, T3 from snapshot) | ✓ (brain `price_bands_public`, `services` hours) | ✓ (snapshots table, opportunities) | Python-dominant |
| **Human handover** | ✓ (wording) | ✓ (`_HUMAN_INTENT` regex, `HandoffService` FSM) | | ✓ (`channel_ai_settings.mode`) | hybrid |

**Key insight**: The price-intent shortcut is **100% deterministic Python (regex)**. It does NOT use LLM reasoning, does NOT consult the mode state machine, and does NOT consult the question-selection weights. It is a hard-coded regex check that runs BEFORE any other logic.

---

## 18. Prompt Inventory

### 1. System prompt for drafting (`coordinator.py` line 1490)

```
"You are AmanCode's assistant (websites, systems, AI automation, and brand
identity). Brand spelling is exactly "AmanCode" (أمان كود).
CHANNEL: {channel}. Write the customer's reply: warm, confident, human, max 55
words, in the SAME language/dialect as their message.
LANGUAGE LOCK: ...answer ONLY in that exact language and script...
Convey exactly the facts in DRAFT CONTENT (translate if needed); NEVER invent
prices, discounts, deadlines, or approvals beyond it.
Purpose: {intent_note}.
If the customer talks about something unrelated to our business, respond warmly
and briefly acknowledge it, then gently steer back.
NEVER repeat a question already present in RECENT CHAT.
Any block labeled LEARNINGS_DATA is anonymized market statistics: background only.
Output only the message text." + COMPANY FACTS
```

**When called**: `_draft_reply()` — every reply that goes through the LLM (normal flow, T1, T2, human handover wrapping).

**Model**: `ModelRouter.route(ROUTINE, messages)` → gemini-3.6-flash (primary), glm-5.3-flash (secondary).

**Inputs**: `CUSTOMER MESSAGE: {text}`, `DRAFT CONTENT: {base}`, `RECENT CHAT: {last 8 msgs}`, `LEARNINGS: {summary}`.

**Purpose**: Word the reply — the WHAT (decision, question, price) is in `base` and `intent_note`. NOT a decision maker.

### 2. T1 brief (coordinator.py line 1198)

```
"MODE=COMMERCIAL tier=T1. Convey EXACTLY the starting range in DRAFT
CONTENT (both numbers + currency). Never round, extend, discount, or call
it a final quote."
```

**When called**: T1 price shortcut path, embedded in `base` via `_draft_reply`.

### 3. T2 brief (coordinator.py line 1355)

Arabic: `"MODE=COMMERCIAL tier=T2. انقل التقدير الاسترشادي باللغة العربية بالضبط..."`
English: `"MODE=COMMERCIAL tier=T2. Convey EXACTLY the figures in DRAFT CONTENT (range + currency) as a tentative estimate; never round, extend, discount or promise them."`

**When called**: T2 price shortcut path.

### 4. T3: NO prompt (deterministic)

T3 returns the price text directly (line 1102-1129) — NO `_draft_reply` call. `[CONFIRMED]`

### 5. T0: NO prompt (deterministic)

T0 returns `_requirement_reply()` directly — NO `_draft_reply` call. `[CONFIRMED]`

### 6. NEED mode brief (planner.py line 257-283)

```
"MODE=NEED (VALUE-FIRST is mandatory).
Detected business type: {industry}; requested solution: {category}.
Provide IMMEDIATE value: reflect their request back in one warm sentence
and present the typical structure below as an initial proposal
tailored to their business type: {sections}.
Then ask EXACTLY ONE high-value question about [{field}] using this
intent: "{hint}". ...
Zero jargon, max 55 words, no prices, no timelines."
```

### 7. SHAPING mode brief (planner.py line 291-392)

Varies based on SUGGEST-INTAKE state. Key branches:
- **SUGGEST-INTAKE**: "Before proposing, make choosing EASY: ask this one quick question with ready options"
- **Full proposal**: "The customer asked YOU to decide. Propose the FULL concrete structure below..."
- **Normal**: "Anchor the working structure: {sections}"

### 8. COMMERCIAL mode brief (planner.py line 397-446)

T1: `"You MAY state the public STARTING RANGE for {category}: from {low} to {high} {currency}. Present it as an entry range that moves with scope, never a final quote."`
T2: `"Scope is clear enough that our team will compute a tentative estimate... NEVER invent figures yourself."`
T0: `"Scope is not clear enough for numbers. Explain in ONE line that pricing follows scope..."`

### 9. Objection wrap brief (planner.py line 180-192)

```
"MODE=NEGOTIATION (objection loop). Acknowledge the customer's concern
sincerely, then follow the approved negotiation ladder in order:
(1) reframe the VALUE, (2) offer to REDUCE SCOPE,
(3) offer phased delivery, (4) recommend the lowest legitimate service.
NEVER reduce the price without a scope change and NEVER invent a discount."
```

### 10. Recommendation wrap brief (planner.py line 205-210)

```
"MODE=COMMERCIAL (recommendation presented). Present the recommended
solution '{offer_name}' by name with a one-line WHY tied to their stated
need. Invite their reaction. Do NOT mention any price figure."
```

### 11. Legacy discovery playbook brief (coordinator.py line 706)

```
"discovery stage. ALREADY KNOWN about this customer: {known}.
Still missing: {missing}. Follow this DISCOVERY PLAYBOOK in order:
STEP 1 (understand), STEP 2 (structure), STEP 3 (essentials).
Reply with exactly ONE step, whichever comes next..."
```

### 12. T3 deterministic text (coordinator.py line 1102-1129)

Full price text with specs, infrastructure package, payment terms. NO prompt — returned directly.

### 13. Scope review reply (coordinator.py line 969)

Deterministic acknowledgment + ONE scope review question from `_SCOPE_REVIEW_QUESTIONS`. NO prompt — returned directly.

---

## 19. Configuration Inventory

### `configs/conversation_policy.yaml` (157 lines)

```yaml
question_weights:
  website:      {key_features: 9, integrations: 8, languages: 7, timeline: 5, authority: 4, scale: 4}
  ecommerce:    {key_features: 9, integrations: 8, languages: 7, timeline: 6, authority: 5, scale: 5}
  mobile:       {key_features: 9, integrations: 7, languages: 5, timeline: 6, authority: 5, scale: 6}
  business_system: {key_features: 9, integrations: 8, languages: 4, timeline: 4, authority: 3, scale: 6}
  automation:   {key_features: 9, integrations: 8, languages: 4, timeline: 5, authority: 4, scale: 5}
  _default:     {key_features: 9, integrations: 6, scale: 5, languages: 5, timeline: 5, authority: 4}

commercial_boost: {budget_band: 9, timeline: 8, authority: 7}
budget_weight_outside_commercial: 0

service_categories:
  website:      {keywords: [موقع, موقع إلكتروني, صفحة, website, ...], brain_service_id: business_website_system}
  ecommerce:    {keywords: [متجر, إلكتروني, سوق, ecommerce, ...], brain_service_id: ecommerce_store}
  mobile:       {keywords: [تطبيق, موبايل, هاتف, app, mobile, ...], brain_service_id: mobile_app}
  business_system: {keywords: [نظام, ERP, برنامج, software, ...], brain_service_id: business_system_mini_erp}
  automation:   {keywords: [أتمتة, automation, روبوت, chatbot, ...], brain_service_id: ai_automation_suite}

commercial_signals: [سعر, price, cost, budget, التكلفة, تسعير, estimate, quote, ...]
suggestion_triggers: [لا أدري, ما أعرف, اقترح, أنت تقترح, عليك الاختيار, suggest, you decide, ...]
suggestion_clarifiers: {restaurant, association_ngo, _default: [...]}
```

**What it controls**: Question field weights (priority), commercial mode triggers, suggestion/ delegation detection, service category keyword mapping, budget gating (weight 0 outside COMMERCIAL).

**Which code reads it**: `ConversationPolicy.load()` → DEFAULTS dict is shallow-merged with YAML overrides.

### `configs/models.yaml`

```yaml
task_routing:
  routine:     {primary: google, secondary: glm, fallback: null}
  extraction:  {primary: google, secondary: glm, fallback: null}
providers:
  google: {model: gemini-3.6-flash, ...}
  glm:    {model: glm-5.3-flash, ...}
```

**What it controls**: LLM provider selection per task class. ROUTINE = reply drafting. EXTRACTION = fact extraction (gated).

**Which code reads it**: `build_providers(cfg)` → `ModelRouter(cfg, ...)`. The coordinator's `_drafter()` loads this.

### `amancore/business_brain/data/v1.yaml` (437 lines)

**Top-level keys**:
- `services` (line 1): 6 services with `id`, `name`, `features`, `typical_sections`, `cross_sell`, `relevant_services`, `objections`
- `price_bands_public` (line 212): T1 starting ranges per category (website 1500-4200, ecommerce 5100-14800, etc.) with optional `mini_scope` for small-scope variants
- `industry_profiles` (line 62): e.g., `association_ngo`, `restaurant`, `real_estate`, `ecommerce` with `typical_sections`, `features`, `goals`, `common_pain_points`, etc.
- `claims` (line 50): approved claims
- `objections` (line 200): objection response scripts
- `market_profiles` (line 40): market/region profiles with multipliers
- `forbidden_claims`: phrases never to use

**What it controls**: Pricing bands, service catalog, industry knowledge, approved claims, objection responses.

**Which code reads it**: `BrainStore.current()` → ConversationModel, QuoteFlow, KnowledgeRetriever, ChannelPolicyEngine.

### `knowledge/packs/` directory

Contains YAML extension packs:
- `service_details.v1.yaml` — service-specific required info to estimate, loaded by `_service_pack()` (coordinator) and `_pack_questions_for()` (T0)
- `interaction_rules.v1.yaml` — escalation, identity disclosure, response variation rules, loaded by `ResponsePlanner.interaction_rules`
- Industry pack extensions (e.g., `standards_web`) — loaded by KnowledgeRetriever

**What it controls**: Service-level detail questions, interaction behaviors, web standards knowledge.

**Which code reads it**: `KnowledgeRetriever`, `ResponsePlanner.interaction_rules`, coordinator `_service_pack`.

---

## 20. Test Coverage

### Tests found and what they cover:

| Test file | Tests | Coverage |
|---|---|---|
| `tests/unit/test_p0_live_parity.py` | 6 tests | Canonical 5-message conversation: greeting → request → structure → delegation → confirmation. Price regex completeness. Mode transitions (OPENING→NEED→SHAPING→COMMERCIAL). |
| `tests/unit/test_p03_pricing_tiers.py` | ~12 tests | T0 (no figure, defer), T1 (public band, no approval), T2 (Gate-B estimate + owner approval), T3 (approved snapshot short-circuit). Price shortcut via `handle_inbound`. |
| `tests/unit/test_p02_hybrid_extraction.py` | ~6 tests | Extraction gating: when LLM extraction is skipped vs. called. Vague budget, indirect authority, uncertain cues. |
| `tests/unit/test_p05_quality_guard.py` | ~6 tests | QualityGuard rules: unauthorized numbers, foreign names, question budget, budget outside COMMERCIAL, scope_under_review, reask_known, T1/T2 wording. |
| `tests/unit/test_conversation_p01.py` | ~8 tests | Mode transitions, value payload, question selection via planner. Legacy path. |
| `tests/unit/test_p1_unlocks.py` | ~8 tests | T1 bands, industry packs, suggest-intake (I don't know delegation), followup seeding, identity disclosure. |
| `tests/unit/test_p15_decision_roles.py` | 3 tests | Decision roles are TONE-ONLY (zero decision diff). Knowledge pack loads from `knowledge/packs/`. |
| `tests/unit/test_interaction_realism.py` | ~6 tests | Recap fires on scope delta, escalation detection, cross-sell guard, small scope detection, consultation intent. |
| `tests/evals/test_sales_evals.py` | 3 tests | Sales evaluation: recommendation relevance, question quality. Uses `sales_scenarios.json` fixture. |
| `tests/evals/test_pricing_evals.py` | 2 tests | Pricing evaluation: estimate accuracy, T1/T2 band coverage. |
| `tests/evals/test_scope_change_probe.py` | 4 tests | Scope change (A/B/C/D): delta capture, snapshot invalidation, recap on scope change, in-category scope change. |
| `tests/unit/test_p12_standards_web.py` | ~6 tests | Web standards data only (WCAG/OWASP/SEO/NIST), never claims. Trigger-only. |
| `tests/unit/test_followup_handoff.py` | ~4 tests | Followup scheduling (need_think, not_ready), handoff request detection, channel AI settings. |
| `tests/unit/test_objection_handling.py` | ~5 tests | Objection classification: price_high, want_discount, need_think, not_ready, skeptical. |

### Tests that DO NOT exist (per investigation):

| Test case | Exists? | Evidence |
|---|---|---|
| 3-message conversations | YES (canonical trace T1-T3, plus price shortcut T0/T1/T2/T3) | `test_p0_live_parity.py`, `test_p03_pricing_tiers.py` |
| 10-message conversations | LIMITED (canonical trace is 5 messages; scope change probe is 4) | `test_p0_live_parity.py` (5 turns), `test_scope_change_probe.py` (4 turns) |
| 20-message conversations | NO | `[CONFIRMED]` No test with >7 messages found |
| 40-message conversations | NO | `[CONFIRMED]` No test |
| 60-message conversations | NO | `[CONFIRMED]` No test |
| 100-message conversations | NO | `[CONFIRMED]` No test |
| Long-horizon discovery | NO | `[CONFIRMED]` No test beyond ~7 messages |
| Ambiguous clients | PARTIAL (unclear/vague budget cues tested in test_p02) | `test_p02_hybrid_extraction.py` |
| "I don't know" | YES (`test_p1_unlocks.py` SuggestIntakeTests) | SUGGEST-INTAKE with "لا أدري، اقترح لي" |
| Customer changing requirements | PARTIAL (`test_scope_change_probe.py` Test A) | Scope delta + snapshot invalidation, but not contradiction per se |
| Topic switching | NO | `[CONFIRMED]` No test for multi-topic conversation |
| Implicit requirements | PARTIAL (scope delta detection tested) | `test_scope_change_probe.py` Test C, Test D |
| Recommendations | YES (eval tests, sales flow) | `test_sales_evals.py`, `test_conversation_p01.py` |
| Pricing before scope completion | YES (T0/T1/T2 tests) | `test_p03_pricing_tiers.py` — T1 fires with minimal context |
| Pricing after scope completion | YES (T2/T3 tests) | `test_p03_pricing_tiers.py` Test B (scope-complete T2), T3 snapshot |
| Human handover | YES | `test_followup_handoff.py` |
| Session recovery | YES (persistence is SQLite) | Implied by CRM persistence; `test_conversation_memory.py` may test it |

---

## 21. Real Conversation Evidence

### Canonical trace (`test_p0_live_parity.py`)

```
Turn 1: "مرحبا"                         → OPENING: "Hi! 👋 What can I help you with today?"
Turn 2: "أريد بناء موقع لجمعية..."        → NEED: value-first + ONE question about key_features
Turn 3: "نعم، ولكن نريد صفحة متطوعين..."    → SHAPING: propose structure, confirmation question
Turn 4: "لا أدري، اقترح لي"              → SHAPING + SUGGEST-INTAKE: 3 easy-choice questions
Turn 5: "وافقتنا على الاقتراح"            → COMMERCIAL: present recommendation, no price figure
```

**Message count**: 5 turns.
**Price introduced at which point**: NOT introduced (5 messages, no price question).
**Discovery continued after price questions**: N/A.
**Felt like a questionnaire?**: PARTIALLY — Turn 2 asks ONE high-value question; Turn 4 asks easy-choice questions; not a rigid field-by-field questionnaire.

### Scope change probe (`test_scope_change_probe.py` Test A)

```
T1: "عندي مطعم وأبغى موقع بسيط مع قائمة الطعام"
T2: "أبغى المنيو الإلكتروني مهم، ~6 صفحات، نسلم خلال شهر"
T3: "أبغى أضيف كمان نظام حجز طاولات وطلبات أونلاين"
T4: "طيب كم صار السعر الآن؟"  → PRICE SHORTCUT
```

**Result at T4**: Returns T1 band for `business_system` (12100-42600) — **NO approval**. `[CONFIRMED]` The price shortcut fires on "سعر" at T4, and T1 returns a public band.

**Key finding**: After only 3 turns of discovery (greeting, scope, timeline from T2; booking/payments from T3), the customer asks about price and gets a number immediately. The price shortcut bypasses Gate-B entirely — T1 doesn't check for key_features or timeline.

### pricing_evals (`test_pricing_evals.py`)

```
Test case: "أريد متجر إلكتروني لبيع التسوق عبر الهاتف" with 5 subsequent questions
→ After discovery, T2 estimate is computed with confidence "high"
```

**Result**: T2 fires after full discovery (Gate-B met). Estimate computed with AI hour estimation + deterministic engine.

But the T1 path fires BEFORE full discovery — it only needs the category.

---

## 22. Exact Root Cause of Premature Pricing

### Ranking the causes (most → least impactful)

**1. `[CONFIRMED]` — Price-intent shortcut regex is a hard bypass (PRIMARY CAUSE)**

`_PRICE_INTENT` (coordinator.py line 80-84) matches 16+ price-related words. The check at line 610 is:
```python
if _PRICE_INTENT.search(text):
    reply = self._localize(self._price_or_proposal_reply(...), language)
    self._queue_reply(lead, mem, msg, reply, corr, ..., plan=price_plan)
    return {...}  # ← COMPLETELY bypasses RIL, SalesAgent, planner
```

This fires BEFORE the ConversationModel planner runs. The mode state machine never advances. Question selection never runs. The customer gets a price without discovering scope, timeline, authority, or budget.

**2. `[CONFIRMED]` — T1 band requires NO approval and NO scope completeness**

`_t1_band_reply` (line 1152) returns the public starting range from `price_bands_public` for ANY known category. A category is detectable from a single word (e.g., "موقع" → website). The Gate-B check (`gate_b_ready`) only applies to T2, not T1. The test `test_t1_engages_in_commercial_brief` confirms: `facts: {}` (empty) still produces T1.

**3. `[CONFIRMED]` — QualityGuard is bypassed when scope_under_review is False**

`_queue_reply` (line 1583): `if plan is not None: QualityGuard.check(...)`. The price branch passes `plan=None` (when scope is not under review, which is the normal case). QualityGuard returns `{"allowed": True, "violations": []}` when `plan is None` — meaning the guard does NOTHING.

**4. `[CONFIRMED]` — Category persists in working_memory across turns**

Once a service category is detected in any message (e.g., "أريد موقع"), `working_memory.service_category` is set. Any later price question (even "كم؟" alone) finds the category in working memory and triggers T1.

**5. `[CONFIRMED]` — T2 Gate-B is checked AFTER scope review, but T1 is checked BEFORE T2**

The order in `_price_or_proposal_reply`:
1. Scope under review → HARD gate (blocks figures)
2. T3 snapshot
3. T2 (Gate-B) → returns None if Gate-B not met
4. T1 → fires with only category known
5. T0 fallback

T1 is the "easy exit" — it fires when Gate-B is NOT met but category IS known. This is the common case: the customer has mentioned what they want (e.g., "موقع") but hasn't provided scope details yet.

**6. `[INFERRED]` — The price shortcut does NOT update facts for the current message**

Since the price shortcut returns before `SalesAgent.process_message()` is called, the customer's price-related message is not processed for fact extraction. The system uses whatever facts were accumulated from PREVIOUS turns.

---

## 23. Current Behavioral Model

### The real behavioral loop (production, with ConversationModel):

**Step 1**: Receive message via webhook → `_process_inbound(msg)`

**Step 2**: Load state
```
lead = CRM.find_lead_by_identity(channel, external_user_id)
mem = ConversationMemory.get_or_create(lead_id)
  → reads conversations.working_memory, facts, summary from SQLite
```

**Step 3**: Update scope review (`_update_scope_review`)
```
scope deltas = detect_scope_delta(text)
pending = existing scope_review_fields + new deltas - withdrawn - resolved(facts)
wm.scope_under_review = bool(pending)
```

**Step 4**: Detect price intent
```
if _PRICE_INTENT.search(text):  → PRICE SHORTCUT (bypasses steps 5-10)
```

**Step 5** (if not price): RIL processing
```
RequirementsService.process_message() → requirements, conflicts, coverage, next_question
```

**Step 6** (if not price): SalesAgent
```
SalesAgent.process_message(lead, text):
  → extract_facts (regex + optional LLM)
  → merge_facts → facts in CRM (conflict detection → open_questions)
  → QualificationEngine.qualify() → BANT score
  → ObjectionHandlingSkill.classify()
  → select_offer() (if qualified) → recommendation
  → state_machine.transition() → CRM stage
```

**Step 7** (if not price): Plan
```
ConversationModel.plan(lead, mem, agent_result, text, ...):
  → ModeManager.advance() → mode (OPENING→NEED→SHAPING→COMMERCIAL→NEGOTIATION)
  → detect service_category + industry
  → generate value_payload (industry pack)
  → policy.next_question() → weighted question selection
  → determine commercial tier (T0/T1/T2/T3)
  → _with_interaction() → memory context, escalation, industry data
  → produce ResponsePlan {mode, brief, base, question, quality, working_memory}
→ persist working_memory to CRM
```

**Step 8** (if price): Price decision tree
```
_price_or_proposal_reply():
  1. scope_under_review? → scope review question (NO figures)
  2. approved snapshot + fingerprint match? → T3 (deterministic price, NO LLM)
  3. Gate-B met (key_features + timeline/scale)? → T2 (estimate + owner approval)
  4. category known? → T1 (public band, NO approval)
  5. fallback → T0 (ONE requirement question)
```

**Step 9**: Draft reply
```
_draft_reply(intent_note=brief, base=base):
  → cost governor check
  → ModelRouter.route(ROUTINE) → LLM
  → System: "You are AmanCode's assistant... max 55 words..."
  → User: "CUSTOMER MESSAGE: ... DRAFT CONTENT: ... RECENT CHAT: ..."
  → fallback if LLM fails
```

**Step 10**: Validate + deliver
```
_queue_reply(plan=plan):
  → response_filter.check(text) → leak prevention
  → if plan is not None: QualityGuard.check(text, plan) → one redraft or fallback
  → if plan is None: QualityGuard BYPASSED (logs "guard_not_applied")
  → channel_policy.evaluate_send() → allow/deny/approval_required
  → outbox.enqueue() → OutboxWorker → adapter.send()
```

### The actual behavioral difference:

When price is detected → **Step 8** fires, bypassing Steps 5-7. The mode state machine doesn't advance. Question selection doesn't run. The customer gets a price (T1 or T2) or a scope review question (if scope changed) — never a discovery question, unless T0 fires (no category known).

When price is NOT detected → Steps 5-10 run in sequence. The system discovers, asks questions, builds value, and only enters pricing when the mode transitions to COMMERCIAL (via `commercial_signal` detection in the planner).

---

## 24. Unknowns / Missing Evidence

| Unknown | Status |
|---|---|
| Exact production LLM response times and error handling | `[UNVERIFIED]` — ModelRouter routing logic read, but not live provider behavior |
| Whether the canonical conversation trace has been validated against live production | `[UNVERIFIED]` — Test docstring says "byte-stable against live data" but no evidence of validation |
| Whether `outbox.worker.drain()` reliably sends all messages | `[UNVERIFIED]` — Code reads outbox.enqueue, but worker drain behavior not fully traced |
| Whether `recent_learnings_summary()` (ops/learning.py) pulls real customer data into prompts | `[UNVERIFIED]` — Module not read in full; only its existence is confirmed via import |
| Whether `business_context()` (ops/telegram_console.py) injects live business facts | `[UNVERIFIED]` — Module not read; only imported in `_draft_reply` |
| Whether the `requirements_service` (RIL) is actually wired in production `build_runtime` | `[INFERRED]` — Coordinator defaults to `RequirementsService(self.crm)` if not passed; `build_runtime` passes `requirements_service`? |
| Whether `channel_ai_settings` overrides exist per channel in production | `[UNVERIFIED]` — Schema has the table, but production config not inspected |
| Whether `interaction_rules.v1.yaml` pack has rules that affect decisions | `[UNVERIFIED]` — Loaded by planner, but the file content not read |
| Whether `service_details.v1.yaml` pack exists in production | `[UNVERIFIED]` — `_service_pack()` loads it but we couldn't find the file |
| Exact content of `configs/models.yaml` (provider keys, fallback chain) | `[PARTIAL]` — Coordinator loads it, but full file content not verified |
| Whether `cost_governor` is active in production | `[UNVERIFIED]` — `_drafter()` and `build_runtime` check for it, but not confirmed |
| Whether there are integration tests for 20+ message conversations | `[CONFIRMED]` — No tests found beyond ~7 messages |
| Whether contradiction handling actually asks the customer | `[CONFIRMED]` — NOT IMPLEMENTED (open_questions stored but never surfaced) |

---

## 25. LLM vs Deterministic Control (Expanded Matrix)

| Decision | LLM | Python | Config | DB State | Hybrid | Evidence |
|---|---|---|---|---|---|---|
| Next question selection | ✗ (wording only) | ✓ (`policy.next_question`) | ✓ (`question_weights`) | ✓ (`facts`, `last_question_field`) | ✓ | planner.py:254, policy.py:312 |
| Question wording | ✓ | ✗ | ✗ | ✗ | ✓ | `_draft_reply` with `hint` |
| Requirement extraction | ✓ (optional, gated) | ✓ (regex `_deterministic_facts`) | ✗ | ✓ (`facts` persisted) | ✓ | `_ExtractionGateRouter`, `extract_facts` |
| Category detection | ✗ | ✓ (`detect_service_category`) | ✓ (`service_categories` keywords) | ✓ (`wm.service_category`) | ✓ | policy.py:219, planner.py:106 |
| Industry detection | ✗ | ✓ (`detect_industry_with`) | ✓ (`industry_aliases` in brain) | ✓ (`wm.industry`) | ✓ | policy.py:238, planner.py:126 |
| Mode transition | ✗ | ✓ (`ModeManager.advance`) | ✓ (mode-specific briefs) | ✓ (`wm.mode`) | ✓ | modes.py:36 |
| Value payload (sections/features) | ✗ | ✓ (`_industry_pack`) | ✓ (`industry_profiles` in brain) | ✓ (`wm.industry`) | ✓ | planner.py:240-252 |
| Recommendation (offer selection) | ✗ | ✓ (`select_offer`) | ✓ (`services` in brain) | ✓ (`qualification` result) | ✓ | pricing/offer.py:15 |
| Recommendation wording | ✓ | ✗ | ✗ | ✗ | ✓ | `_draft_reply` with `rec.message` |
| SUGGEST-INTAKE question | ✗ | ✓ (`suggestion_clarifiers`) | ✓ (`suggestion_clarifiers` in yaml) | ✓ (`wm.suggestion_pending`) | ✓ | planner.py:303-344 |
| Discovery completion | ✗ | ✓ (`next_question` returns None when all known) | ✓ (`question_weights`) | ✓ (`facts`) | ✓ | policy.py:312-327, planner.py:280 |
| Price intent detection | ✗ | ✓ (`_PRICE_INTENT` regex) | ✗ | ✗ | ✗ | coordinator.py:610 |
| T1 band decision | ✗ | ✓ (`public_band`, `_t1_band_reply`) | ✓ (`price_bands_public`) | ✓ (`wm.service_category`) | ✓ | coordinator.py:1152 |
| T2 estimate decision | ✗ | ✓ (`gate_b_ready`, `QuoteFlow.estimate`) | ✓ (`services.hours`) | ✓ (`facts`) | ✓ | coordinator.py:1307, pricing_flow.py:1328 |
| T3 snapshot decision | ✗ | ✓ (`snapshots.get_for_opportunity`, fingerprint) | ✓ (brain data) | ✓ (snapshots table) | ✓ | coordinator.py:1055 |
| Final price (T1) | ✗ (wording only) | ✓ (brain `price_bands_public`) | ✓ | ✓ (`snap.approved_price` for T3) | ✓ | coordinator.py:1152-1218 |
| Final price (T2) | ✗ (wording only) | ✓ (`PricingEngine.price`) | ✓ (brain `services`, `market_profiles`) | ✓ | ✓ | pricing/engine.py:35, pricing_flow.py |
| Final price (T3) | ✗ (NO LLM — deterministic) | ✓ | ✓ | ✓ (snapshots table) | ✓ | coordinator.py:1102-1129 |
| Human handover | ✓ (wording) | ✓ (`_HUMAN_INTENT` regex, `HandoffService`) | ✗ | ✓ (`channel_ai_settings`) | ✓ | coordinator.py:586, sales/handoff.py |
| QualityGuard enforcement | ✗ | ✓ (`QualityGuard.check`) | ✓ (`forbidden_claims`, weights) | ✓ (`plan.quality`) | ✓ | quality_guard.py:53, coordinator.py:1600 |

---

## 26. State Machines (Expanded)

### Three overlapping state machines

**State machine 1: CRM Lead Stage** (`sales/state_machine.py`)
- `new → contacted → engaged → discovery → qualification → offer_recommended → proposal → negotiation → awaiting_decision → won/lost/onboarding`
- Driven by `SalesAgent.process_message()` → `state_machine.transition()`
- **Bypassed** by price-intent shortcut

**State machine 2: Conversation MODE** (`conversation/modes.py`)
- `OPENING → NEED → SHAPING → COMMERCIAL → NEGOTIATION`
- Driven by `ModeManager.advance()` inside `ConversationModel.plan()`
- **Bypassed** by price-intent shortcut

**State machine 3: Human Handover** (`sales/handoff.py`)
- `AI_ACTIVE → HUMAN_REQUESTED → HUMAN_ACTIVE → AI_RESUMED → CLOSED`
- Driven by `_HUMAN_INTENT` regex + `HandoffService`
- Check BEFORE price-intent shortcut (line 581)

**How they interact**: All three write to different storage layers:
- CRM stage → `leads.stage` column
- MODE → `conversations.working_memory.mode` JSON field
- Handover → `channel_ai_settings.mode` table

The price shortcut bypasses FSM 1 and FSM 2 entirely. FSM 3 is checked BEFORE the price shortcut (line 581), so if the human takeover is active, the price shortcut never fires.

---

## 27. Price Intent Detection — Per Case

> "Whenever the customer mentions price, AmanCore attempts to enter the pricing flow."

**Test this against the actual code:**

| Customer message | `_PRICE_INTENT` matches? | What happens |
|---|---|---|
| "How much would something like this cost?" | YES (`cost`) | Price shortcut fires. T1/T2/T0/T3 path. |
| "By the way, later we can discuss the price." | YES (`price`) | Price shortcut fires. Entire normal conversation is aborted. |
| "My budget is $10,000." | NO (`budget` NOT in regex) | Normal flow. `budget` extracted as fact. Mode may advance to COMMERCIAL (via `commercial_signals` in policy). Planner handles it. |
| "Is this expensive?" | NO | No price intent. Normal flow. No price figure shown. |
| "Give me a rough idea." | NO | No price intent. Normal flow. T0 if in COMMERCIAL mode. |

**The statement is TRUE for cases 1-2** — any mention of the 16 matched words triggers the price shortcut.

**The statement is FALSE for case 3** — "budget" is NOT in `_PRICE_INTENT` (the regex uses `budget` only in `commercial_signals` for mode transition, not in the shortcut).

**The statement is FALSE for cases 4-5** — "expensive" and "rough idea" are not in the regex.

**Critical nuance**: The `_PRICE_INTENT` regex is MUCH narrower than the `commercial_signals` list in the policy. The policy's `commercial_signals` includes more words (ميزانية/budget, التكلفة, etc.). But only `_PRICE_INTENT` triggers the shortcut. The policy's `commercial_signals` only triggers mode transitions within the normal flow.

---

## 28. Final Capability Table

| Capability | Current Implementation | Evidence | Confidence |
|---|---|---|---|
| Long conversations | Facts persist in SQLite; recent 8 msgs to LLM; summary every 10 msgs; but no explicit test beyond ~7 messages | `channel_messages` table, `summary` field, `inject_context`, `test_p0_live_parity` (5 turns), `test_scope_change_probe` (4 turns) | **[CONFIRMED]** |
| Context retention | `working_memory` + `facts` JSON persisted; recent 8 msgs in context; summary capped 220 chars | `conversations.working_memory`, `conversations.facts`, `_recent_history`, `summary[:220]` | **[CONFIRMED]** |
| Requirement extraction | Hybrid: deterministic regex (`_deterministic_facts`) + optional LLM (`extract_facts`) via extraction gate; RIL (RequirementsService) for structured tracking | `conversation_memory.py:38,74`, `_ExtractionGateRouter`, `requirements/service.py:33` | **[CONFIRMED]** |
| Implicit requirement detection | Limited: `detect_scope_delta` captures booking/payments/integrations/languages/member_areas/dynamic_content; no brand/semantic inference | `SCOPE_DELTA_MAP`, `detect_scope_delta`, `scope/memory_reducer.py` | **[CONFIRMED]** |
| Recommendation | Industry pack `value_payload` (sections/features/goals); `select_offer` based on qualification; SUGGEST-INTAKE for delegation | `planner.py:240-252,200-217`, `pricing/offer.py:15`, `v1.yaml:industry_profiles` | **[CONFIRMED]** |
| Handling "I don't know" | SUGGEST-INTAKE flow: `suggestion_triggers` detection → easy-choice questions with options → full structure proposal | `planner.py:298-368`, `policy.suggestion_clarifiers` | **[CONFIRMED]** |
| Contextual follow-up | `recent_history` (last 8 msgs) fed to LLM with "NEVER repeat a question already present"; `question_hints` provide intent | `_recent_history`, planner brief instructions | **[CONFIRMED]** |
| Contradiction handling | `merge_facts` adds `clarify_{field}` to open_questions on value change; `_withdrawn_fields` sets facts=False for negated fields; `scope_fingerprint` invalidates snapshots | `conversation_memory.py:106`, `coordinator.py:109`, `pricing/registry.py:scope_fingerprint` | **[PARTIAL]** |
| Topic switching | `intent_queue` in working_memory holds multi-intent categories; resumed on later turns; cross-sell hint acknowledges noted items | `planner.py:111-124,456-490` | **[PARTIAL]** |
| Discovery completion | `next_question` returns None when all weighted fields satisfied OR all weights ≤ 0 | `policy.py:312-327` | **[CONFIRMED]** |
| Premature pricing protection | SCOPE UNDER REVIEW (hard gate on numbers when scope changes unconfirmed); but price shortcut bypasses mode FSM, question selection, and QualityGuard (when scope_not_under_review) | `coordinator.py:610,824,1046`, `quality_guard.py:56-57` | **[WEAK]** |
| Rough estimate | T1: public starting band from Brain (no approval); T2: Gate-B estimate + owner approval | `coordinator.py:1152-1218, 1307-1375`, `v1.yaml:price_bands_public` | **[CONFIRMED]** |
| Final quote | T3: approved snapshot (deterministic, no LLM); T2: estimate pending owner approval | `coordinator.py:1055-1138`, `snapshots` table | **[CONFIRMED]** |
| Human handover | `_HUMAN_INTENT` regex → `HandoffService.request_human` → channel AI disabled → AI hold | `coordinator.py:586-597`, `sales/handoff.py` | **[CONFIRMED]** |
| Project state | `working_memory` (mode/industry/category), `facts` (BANT+scope), `requirements` (RIL), `decisions`, `objections` | `conversations` table schema, `conversation_memory.py` | **[CONFIRMED]** |

---

## 29. Answer: Why Does AmanCore Behave This Way?

**Because the price-intent shortcut (`_PRICE_INTENT.search(text)` at coordinator.py line 610) is a hard regex-based bypass that fires BEFORE the conversation planner, question selection, mode state machine, and quality guard.**

When a customer uses ANY of 16 price-related words (price, cost, berapa, harga, سعر, بكم, كم تسوى, كم تكلف, كم ثمن, كم سعر, سيكلف, يكلف, quote, proposal, تسعير, estimate), the system:

1. **Immediately** returns from `_process_inbound`, never reaching `ConversationModel.plan()`.
2. Calls `_price_or_proposal_reply()` which follows: scope-under-review → T3 snapshot → T2 Gate-B → T1 band → T0 question.
3. **T1 fires with only a service category known** — no scope completeness check, no owner approval, no QualityGuard (plan=None bypass).
4. The category can come from a single word in the current message OR from `working_memory.service_category` persisted from any previous message.

The normal conversation flow (steps 5-10 in section 23) is well-designed: it uses weighted question selection, mode-aware behavior, value-first approach, and QualityGuard enforcement. The problem is that the price shortcut **completely bypasses** this well-designed flow.

The root cause is NOT that the system "asks too few questions." The system asks the right questions in the normal flow. The root cause is that the price shortcut **bypasses question selection entirely** — it doesn't ask questions, it goes straight to pricing.

---

## 30. Summary of Key Mechanisms

### Price Intent Shortcut (THE mechanism)

```
Customer message
  ↓
_PRICE_INTENT.search(text)  ← regex, 16+ words
  ↓  (matches ANY price word)
_price_or_proposal_reply()  ← bypasses EVERYTHING below
  ↓
scope_under_review? → SCOPE REVIEW QUESTION (hard gate)
  ↓  (No)
approved snapshot? → T3 deterministic price (no LLM)
  ↓  (No)
Gate-B (key_features + timeline/scale)? → T2 estimate + owner approval
  ↓  (No — common case)
T1 public band (category known only) → PRICE RANGE, NO APPROVAL, NO QualityGuard
  ↓  (category unknown)
T0 → ONE requirement question
  ↓
_queue_reply(plan=None) → QualityGuard BYPASSED
```

### Normal Flow (well-designed)

```
Customer message
  ↓
_PRICE_INTENT.search(text)  ← regex, 16+ words
  ↓  (does NOT match)
RIL → SalesAgent → ConversationModel.plan() → ModeManager
  ↓
  mode = OPENING/NEED/SHAPING/COMMERCIAL/NEGOTIATION
  → next_question() → highest-weight MISSING field
  → T1/T2/T3 only when mode = COMMERCIAL + proper gates
  → QualityGuard enforced (plan is not None)
  → LLM drafts with brief + base (wording only)
```

The normal flow is correct. The price shortcut is the problem.

---

*This report is based on a complete read-only inspection of the AmanCore source code at `aman-core/amancore/`. No code was modified.