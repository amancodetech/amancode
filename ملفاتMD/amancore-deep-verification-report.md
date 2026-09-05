1. Executive Summary
AmanCore at runtime is a deterministic, missing-field-driven discovery loop with LLM wording, plus a parallel price-dispatch branch that fires on any price-word. CONFIRMED
One inbound message flows:
webhook_server.do_POST() → coordinator.handle_inbound()/handle_bridge_event() → _intake_single_event() → _process_inbound() → lead lookup → ConversationMemory.get_or_create() → _update_scope_review() → guards → IntentRouter.classify_domain() → RequirementsService.process_message() → SalesAgent.process_message() → ConversationModel.plan()/persist() → either _price_reply_after_planning() or _draft_reply() → _queue_reply() (filter + QualityGuard + policy + Outbox.enqueue()) → OutboxWorker.drain() → Adapter.send(). CONFIRMED
Conversation behavior is controlled by deterministic Python + config + DB state; the LLM never decides. The LLM only phrases a brief/base built deterministically. Question = highest-weight missing field (ConversationPolicy.next_question()). Price = T0/T1/T2/T3 dispatch in _price_or_proposal_decision(). Both allow figures after very little scope (T1 = category + any 1 of 14 facts; T2 = category + scope + (timeline|users)). Any message matching _PRICE_INTENT enters the pricing decision, even mid-discovery, even incidentally ("later we can discuss the price"). CONFIRMED
There is no analogy inference ("like Airbnb/Noon/Haraj"), no architecture/MVP/trade-off recommender, no confidence-gated discovery completion, no real long-horizon memory (LLM sees 8 msgs × 90 chars + 220-char summary + facts). Contradictions are not resolved; topic-switching is a shallow intent_queue. CONFIRMED
2. Relevant Files
File	Relevant Functions / Classes	Responsibility	Called From	Calls	Importance
amancore/channels/webhook_server.py	do_POST(), _bridge_inbound(), _bridge_envelope_ack(), build_runtime(), build_conversation_stack()	HTTP transport, composition root, outbox drain trigger	provider webhooks	coordinator.handle_inbound/handle_bridge_event, OutboxWorker.drain	Critical — entry
amancore/channels/coordinator.py	MessageCoordinator.handle_inbound/handle_bridge_event/_intake_single_event/_process_inbound/_price_or_proposal_decision/_t1_band_reply/_t2_estimate_reply/_requirement_reply/_scope_review_reply/_price_reply_after_planning/_price_guard_plan/_draft_reply/_queue_reply/_recent_history/_update_scope_review/_withdrawn_fields/_deterministic_voice_reply, _PRICE_INTENT/_HUMAN_INTENT/_OPT_OUT/_ExtractionGateRouter	Full orchestration, pricing dispatch, drafting, guard wiring, outbox enqueue	webhook_server	CRM, memory, RIL, SalesAgent, ConversationModel, QuoteFlow, ModelRouter, QualityGuard, outbox	Critical — core loop
amancore/channels/canonical.py	InboundMessage.from_event()	CanonicalEvent → InboundMessage	_intake_single_event	—	High
amancore/channels/whatsapp.py, telegram.py, meta_channels.py, bridge_envelope.py, bridge_whatsapp.py	receive_webhook(), _inbound(), send(), normalize_envelope()	Provider normalize → CanonicalEvent; send	handle_inbound, _bridge_envelope_ack	CanonicalEvent	High
amancore/conversation/policy.py	ConversationPolicy.next_question/weights_for/field_known/t1_min_scope/gate_b_like_scope/detect_service_category/detect_industry_with/commercial_signal	Live question algorithm, weights, gates	planner, coordinator T1/T2	conversation_policy.yaml	Critical
amancore/conversation/planner.py	ResponsePlanner.plan/_with_interaction, ConversationModel.plan/persist/public_band	Deterministic brief builder (mode+value+question+tier+quality contract)	_process_inbound	policy, modes, brain, retriever, memory_reducer	Critical
amancore/conversation/modes.py	ModeManager.initial_mode/advance/hydrate, MODES	Conversation MODE machine	planner	policy	Critical
amancore/conversation/pricing_flow.py	QuoteFlow.gate_b_ready/estimate/request_owner_approval/finalize	T2 math + approval + T3 snapshot	_t2_estimate_reply	PricingEngine, registry, fx, approvals, snapshots	Critical
amancore/conversation/quality_guard.py	QualityGuard.check	Pre-send number/currency/question/language/scope gate	_queue_reply	plan contract	High
amancore/conversation/memory_reducer.py	reduce_memory/inject_context, SUMMARY_LIMIT=220	Rolling summary → brief tag	planner	—	High
amancore/conversation/knowledge_retriever.py	KnowledgeRetriever.retrieve/decision_roles_prior	Per-mode industry slice	planner	knowledge packs	Medium
amancore/sales/conversation_memory.py	ConversationMemory.get_or_create/save/merge_facts, extract_facts/_deterministic_facts/detect_scope_delta, SCOPE_DELTA_MAP	Fact memory, scope-delta capture	coordinator, SalesAgent	ModelRouter (extraction)	Critical
amancore/sales/discovery.py	DiscoveryEngine.missing_fields/next_question, PRIORITY/TEMPLATES	Legacy question engine (still live inside SalesAgent)	SalesAgent.process_message	—	High
amancore/sales/qualification.py	QualificationEngine.qualify, _REQUIRED_FOR_READINESS	BANT readiness	SalesAgent	—	High
amancore/sales/state_machine.py	transition/STATES/TRANSITIONS	CRM deal FSM	SalesAgent	—	Medium
amancore/agents/sales.py	SalesAgent.process_message/_recommend/_upsert_opportunity	Discovery→recommend+opportunity	coordinator	memory, discovery, qualification, offer	High
amancore/agents/support.py	SupportAgent.process_message	Support lane	_support_flow	IntentRouter	Medium
amancore/requirements/service.py	RequirementsService.process_message	RIL orchestration	_process_inbound	extractor, conflicts, coverage, questions, scope_builder, CRM	High
amancore/requirements/extractor.py	RequirementsExtractor.extract/parse_llm_json, MODULE_RULES/DECISION_RULES/NEGATION_PATTERN	Regex requirement+decision capture	RIL service	models	High
amancore/requirements/models.py	Certainty/Priority/Status/Requirement/ProjectDecision/OpenQuestion	RIL types	extractor/service	—	High
amancore/requirements/questions.py	QuestionEngine.select_best_question, QUESTION_BANK	RIL clarification bank (7 fixed Qs)	RIL service	—	Medium
amancore/requirements/coverage.py	CoverageAnalyzer.analyze/_is_domain_covered, TIER_DOMAINS	Coverage % + readiness (70 + no critical gaps)	RIL service	—	Medium
amancore/requirements/conflicts.py	ConflictDetector.detect_conflicts, CONFLICT_RULES (3 pairs)	Contradiction detection	RIL service	—	Medium
amancore/requirements/decisions.py	DecisionTracker.record_decision	Decision supersede chain	RIL service	CRM	Medium
amancore/pricing/registry.py	service_for_category/offer_for_service/calculate_dynamic_hours/scope_fingerprint/complexity_level	Service identity, hours, fingerprint	QuoteFlow, coordinator	Brain	Critical
amancore/pricing/engine.py	PricingEngine.price	Pure pricing math	QuoteFlow	Brain policy	High
amancore/pricing/fx.py	resolve_market/usd_to_idr/get_usd_idr_rate	USD-base + IDR freeze	planner, T1/T2, QuoteFlow	Brain fx_rates	High
amancore/pricing/offer.py	select_offer/recommendation_message	Keyword offer pick (4 branches)	SalesAgent	Brain services/offers	High
amancore/pricing/snapshot.py, proposal.py, negotiation.py	PricingSnapshotStore/ProposalStore+Generator/NegotiationEngine	T3 freeze, proposal render, scope-before-price ladder	QuoteFlow, coordinator	—	High
amancore/channels/handover.py	HandoverService.can_send_ai/request_human/get_mode/set_mode, MODES	Human-takeover machine	_process_inbound, _support_flow	CRM conversations.mode	High
amancore/channels/outbox.py	MessageOutbox.enqueue/claim_batch/mark_sent/mark_failed, OutboxWorker.process_one/drain	Idempotent delivery	_queue_reply, handle_inbound	adapters, policy, valve	High
amancore/routing/router.py, providers.py, models.py	ModelRouter.route/_order, UsageTracker	LLM routing + fallback	_complete_draft, extract_facts	configs/models.yaml	High
amancore/channels/language.py	LanguageDetector.detect	ar/id/en regex	_process_inbound, pricing	—	Medium
amancore/support/intent.py	IntentRouter.classify_domain/classify_category	sales vs support vs legal/billing/complaint	_process_inbound, SupportAgent	—	High
amancore/skills/objection_handling.py, localization.py	ObjectionHandlingSkill.classify/handle, LocalizationSkill.localize	Objection ladder text; ar/id adapt	SalesAgent, _localize	Brain objections	Medium
configs/conversation_policy.yaml	weights, boosts, hints, signals, clarifiers	Strategy override of policy DEFAULTS	ConversationPolicy.load	—	Critical
configs/models.yaml	task_routing (all ROUTINE→gemini/glm)	Model selection	_drafter	—	High
amancore/business_brain/data/v1.yaml	services/offers/pricing_profiles/price_bands_public/industry_profiles/objections	All business values	planner, registry, engine, offer	—	Critical
knowledge/packs/*, knowledge/interaction/*	service_details, industry packs, interaction_rules	DATA-only phrasing slices	planner retriever	—	Medium
Unrelated files (analytics, content, social, voice, insights, ops consoles, scheduler) excluded — they do not steer a customer turn except business_context() facts + learnings garnish + followup seeding. CONFIRMED
3. Actual Runtime Message Flow
Main path = WhatsApp text; bridge path identical after normalization. CONFIRMED
1.
File: amancore/channels/webhook_server.py
Function: WebhookRequestHandler.do_POST()
Input: HTTP POST /webhook/whatsapp (JSON body + X-Hub-Signature-256) or /bridge/inbound (X-Bridge-Token)
Action: GET→verify_webhook; POST→coordinator.handle_inbound(channel,body,headers,raw) or handle_bridge_event(envelope); then OutboxWorker.drain(limit=10), sync_channel_messages, owner notify
State changed? No. DB changed? No. LLM called? No.
Next: coordinator.handle_inbound / handle_bridge_event

2.
File: amancore/channels/whatsapp.py / bridge_envelope.py
Function: WhatsAppAdapter.receive_webhook() / normalize_envelope()
Input: provider JSON
Action: object==whatsapp_business_account → _inbound per message → CanonicalEvent(message.received, idempotency wa:{wamid}); statuses → message.sent/delivered/read/failed
State changed? No. DB changed? No. LLM called? No.
Next: coordinator._intake_single_event()

3.
File: amancore/channels/coordinator.py
Function: _intake_single_event()
Input: CanonicalEvent
Action: reaction→recorder; status→status_recorder; else IdempotencyStore.check(wa:{id}); InboundMessage.from_event(); _process_inbound(); IdempotencyStore.store()
State changed? Idempotency key stored. DB changed? Yes (idempotency_keys). LLM called? Downstream.
Next: _process_inbound()

4.
File: amancore/channels/coordinator.py + amancore/crm/service.py
Function: _process_inbound() lead lookup
Input: InboundMessage(channel, external_user_id, text)
Action: find_lead_by_identity → find_lead_by_whatsapp (legacy backfill) → else create_lead + add_lead_identity + consent_at=inbound_first_message; record inbound channel_messages
State changed? lead/conversation rows. DB changed? Yes. LLM called? No.
Next: guards

5.
File: amancore/channels/coordinator.py
Function: _process_inbound() guards
Input: text, lead, mem=ConversationMemory.get_or_create()
Action: lang.detect (ar regex else id keywords else en); _update_scope_review (detect_scope_delta + _withdrawn_fields → wm.scope_review_fields/scope_under_review, save); opt_out hold; _OPT_OUT → opt_out=1; handover.can_send_ai (AI_ACTIVE|AI_RESUMED + channel flag) else hold; _HUMAN_INTENT → request_human + draft+queue handoff reply
State changed? wm.scope_* + summary bookkeeping; possible opt_out/mode. DB changed? Yes (conversations). LLM called? Only handoff draft.
Next: intent routing

6.
File: amancore/support/intent.py
Function: IntentRouter.classify_domain()
Input: text
Action: regex priority: security→support, legal/billing/complaint→owner lane, support/technical/project_status→support, sales keywords (buy,price,quote,website,سعر,موقع…)→sales, else general; customer+support/general→SupportAgent else sales
State changed? No. DB changed? No. LLM called? No.
Next: _support_flow() OR sales+RIL+planner path

7.
File: amancore/requirements/service.py
Function: RequirementsService.process_message()
Input: lead_id, message, conversation_id, source_message_id, language
Action: extractor.extract (12 MODULE_RULES + DECISION_RULES, negation window, explicit 0.98 vs inferred 0.85) → dedup by subcategory (confidence=max) / source_message_id → DecisionTracker.record → ConflictDetector (3 hardcoded pairs) → CoverageAnalyzer (tier=website default — caller passes tier="website" always in live path) → QuestionEngine first-match bank → persist open_questions → ScopeBuilder if score≥60 or ≥3 reqs
State changed? requirements/decisions/conflicts/open_questions/scope_versions. DB changed? Yes. LLM called? No (LLM parse path exists but live process_message uses deterministic extract only).
Next: SalesAgent.process_message()

8.
File: amancore/agents/sales.py + amancore/sales/conversation_memory.py
Function: SalesAgent.process_message() (wrapped by _ExtractionGateRouter)
Input: lead, text
Action: get_or_create(internal); _advance new→contacted→engaged→discovery; extract_facts (deterministic budget/authority/timeline/problem/outcome + scope-delta + optional LLM run_json extraction — skipped when confident+single-category+no-digits); merge_facts (conflict→append "clarify {k}", else overwrite); handoff.detect→needs_human; objection_skill.classify→objection return; qualify (readiness = problem+outcome+authority+budget+timeline); not ready→DiscoveryEngine.next_question (PRIORITY first-missing) state=discovery; ready→transition→offer_recommended + score_lead + select_offer + upsert opportunity
State changed? facts/open_questions/current_state/next_action/lead_score/opportunity. DB changed? Yes. LLM called? Sometimes (extraction task, gated).
Next: ConversationModel.plan()

9.
File: amancore/conversation/planner.py + modes.py + policy.py
Function: ConversationModel.plan() → ResponsePlanner.plan()
Input: lead, mem (facts+wm), agent_result, text, language, channel, ril_question/coverage
Action: multi-intent detect (all categories; primary leads, rest → wm.intent_queue); industry via brain aliases; initial_mode (commercial_signal→COMMERCIAL; category/verb→NEED; else OPENING) or advance (OPENING→NEED→SHAPING→COMMERCIAL; COMMERCIAL sticky; objection→NEGOTIATION); ask=policy.next_question(category,mode,facts,exclude=last_question_field); build mode brief (OPENING greeting / NEED value-first+1Q / SHAPING co-build or SUGGEST-INTAKE / COMMERCIAL T0/T1/T2 tiering + exactly-one-question) + _with_interaction 12 layers (memory tag, register, variation seed, recap, escalation, sentiment, identity, industry slice, decision-roles, standards, consultation, RIL) + quality contract (allowed_numbers, forbidden catalog/claims)
State changed? None yet (pure). DB changed? No. LLM called? No.
Next: ConversationModel.persist() then draft dispatch

10.
File: amancore/conversation/planner.py
Function: ConversationModel.persist()
Input: working_memory
Action: re-read get_or_create then save wm (never clobber fresh facts); _relationship_maintenance (followup seed on objection/recommendation; 10-msg rollup summary ≤500 chars)
State changed? working_memory, summary, next_followup_at. DB changed? Yes. LLM called? No.
Next: price_request? _price_reply_after_planning : _draft_reply

11a. Non-price path
File: amancore/channels/coordinator.py
Function: _draft_reply()
Input: intent_note=plan.brief, base=plan.base, history=_recent_history(8×90ch)
Action: cost_governor.allow → block→deterministic voice/deferral; else ModelRouter ROUTINE with system (brand, language-lock, convey DRAFT exactly, never invent price, RECENT CHAT do-not-repeat, LEARNINGS background-only, COMPANY FACTS) + user (CUSTOMER+DRAFT+RECENT+LEARNINGS); cap 700ch; record usage
State changed? usage/cost counters. DB changed? Yes (usage_records). LLM called? Yes (1 call).
Next: _queue_reply(reply, plan)

11b. Price path (price_request = _PRICE_INTENT match)
File: amancore/channels/coordinator.py
Function: _price_reply_after_planning() → _price_or_proposal_decision()
Input: fresh mem re-read, wm, facts, opp, snapshot
Action: scope_under_review→scope_review_reply zero figures; elif T3 snapshot fingerprint match→frozen approved_price+specs+infra verbatim; elif approved proposal→ready text; elif _t2_estimate_reply (Gate-B → AI hours override 5–500 else dynamic hours → QuoteFlow.estimate low=floor/high=target → scope_fingerprint → request_owner_approval final_price + owner /qapprove alert) ; elif _t1_band_reply (category + t1_min_scope + public_band + market localize) ; else _requirement_reply (pack required_info_to_estimate[0] → legacy → generic) ; then _localize + _price_guard_plan (T1/T2 allow only low/high; T3 trust reply digits; T0/scope_review allow none; mode=COMMERCIAL) 
State changed? approvals/opportunities/snapshots supersede. DB changed? Sometimes. LLM called? T1/T2 wording via _draft_reply (1 call); T0/T3/scope_review deterministic (0 calls).
Next: _queue_reply(reply, price_plan)

12.
File: amancore/channels/coordinator.py
Function: _queue_reply()
Input: text, plan (never None on planned/price turns)
Action: ExternalResponseFilter leak check; QualityGuard.check + one strict redraft else _SAFE_FALLBACK localize; ChannelPolicyEngine.evaluate_send (low→allow); outbox.enqueue idempotency {channel}-reply:{salt}
State changed? outbox row. DB changed? Yes. LLM called? At most 1 redraft.
Next: OutboxWorker.drain() → Adapter.send()
4. Actual Call Graph
webhook_server.do_POST()
    ↓
coordinator.handle_inbound() | coordinator.handle_bridge_event() [UNVERIFIED which provider hits which in prod; both converge]
    ↓
whatsapp/telegram/meta/bridge_envelope.receive/normalize → CanonicalEvent
    ↓
coordinator._intake_single_event()
    ├─→ IdempotencyStore.check/store() [CONFIRMED]
    ├─→ InboundMessage.from_event() [CONFIRMED]
    ↓
coordinator._process_inbound()
    ├─→ crm.find_lead_by_identity/find_lead_by_whatsapp/create_lead/add_lead_identity [CONFIRMED]
    ├─→ message_recorder (channel_messages in) [CONFIRMED]
    ├─→ lang.detect() [CONFIRMED]
    ├─→ memory.get_or_create() [CONFIRMED]
    ├─→ _update_scope_review() → detect_scope_delta() + _withdrawn_fields() → memory.save() [CONFIRMED]
    ├─→ handover.can_send_ai() → hold [CONFIRMED]
    ├─→ _HUMAN_INTENT → handover.request_human() → _draft_reply() → _queue_reply() [CONFIRMED]
    ├─→ crm.get_customer_for_lead() + intent_router.classify_domain()
    │       ↓ legal/billing/complaint OR customer+support/general
    │   coordinator._support_flow() → support_agent.process_message() → support_filter.check() → _localize() → _queue_reply() [CONFIRMED]
    ├─→ requirements_service.process_message() → extractor.extract() → crm.create/update_requirement → decision_tracker → conflict_detector → coverage_analyzer → question_engine → scope_builder [CONFIRMED]
    ├─→ _ExtractionGateRouter.wrap(router) → sales_agent.process_message() → extract_facts(+run_json extraction if not gated) → merge_facts() → handoff/objection/qualify → discovery.next_question() OR select_offer()+score+upsert_opportunity [CONFIRMED]
    ├─→ intent_rules.classify_approval() → summary approved → handover.request_human() (no price auto-send) [CONFIRMED]
    ├─→ conversation.plan() (planner.plan: policy.next_question + modes + brain + retriever + reducer) [CONFIRMED]
    ├─→ conversation.persist() + _relationship_maintenance() (followup seed + 10-msg rollup) [CONFIRMED]
    ├─→ price_request? NO → _draft_reply() via ModelRouter ROUTINE [CONFIRMED]
    │              YES → _price_reply_after_planning() → _price_or_proposal_decision()
    │                       ├─→ scope_under_review → _scope_review_reply() [CONFIRMED]
    │                       ├─→ snapshots.get_for_opportunity() + scope_fingerprint compare → T3 verbatim | supersede() [CONFIRMED]
    │                       ├─→ _t2_estimate_reply() → _estimate_hours_with_ai() (ROUTINE) → quote_flow.estimate() → request_owner_approval() [CONFIRMED]
    │                       ├─→ _t1_band_reply() → conversation.public_band() → _draft_reply() [CONFIRMED]
    │                       └─→ _requirement_reply() → _pack_questions_for() [CONFIRMED]
    │                       → _price_guard_plan() [CONFIRMED]
    ↓
coordinator._queue_reply()
    ├─→ response_filter.check() [CONFIRMED]
    ├─→ quality_guard.check() → strict redraft via _draft_reply() once → fallback [CONFIRMED]
    ├─→ channel_policy.evaluate_send() [CONFIRMED]
    └─→ outbox.enqueue() [CONFIRMED]
    ↓
OutboxWorker.drain()/process_one() → valve.check_all_outbound() → adapter.send() → mark_sent/mark_failed/mark_uncertain() [CONFIRMED]
UNVERIFIED: exact production adapter mix (bridge vs direct) per channel; owner-console manual send path is separate (inbox_send_message) and not on the customer loop.
5. Conversation State Machines
There are multiple overlapping machines, not one. CONFIRMED
Machine 1 — Conversation MODE (behavior). amancore/conversation/modes.py:16 MODES=(OPENING,NEED,SHAPING,COMMERCIAL,OFFER,NEGOTIATION,DECISION,FOLLOW_UP). Persisted in conversations.working_memory.mode (db.py:159, planner._wm). CONFIRMED
State	Purpose	Entry	Exit	Who changes
OPENING	greeting, one soft opening Q	first turn, no category/verb/commercial signal	category/verb/commercial → NEED/COMMERCIAL	initial_mode, advance
NEED	value-first + typical structure + 1 high-value Q	request detected	structure_proposed → SHAPING; recommendation_ready → COMMERCIAL	planner + hydrate(structure_proposed)
SHAPING	co-build / SUGGEST-INTAKE choices / confirm	NEED+structure_proposed	recommendation/commercial_signal/affirm+price → COMMERCIAL	planner + modes
COMMERCIAL	progressive T0/T1/T2 + 1 commercial Q	commercial signal, recommendation, SHAPING exit	sticky — never leaves	modes
NEGOTIATION	objection ladder (value→scope→phased→smallest, never discount)	objection in COMMERCIAL/OFFER (+return_mode saved)	sticky	planner wrap
OFFER/DECISION/FOLLOW_UP	reserved identifiers	OFFER entry NOT wired in modes (needs approved snapshot, handled in pricing dispatch); DECISION/FOLLOW_UP reserved	—	—
Diagram (actually implemented):
OPENING → NEED → SHAPING → COMMERCIAL ⇆ NEGOTIATION (sticky)
   ↓_______________↑ (commercial_signal jumps straight to COMMERCIAL)
recommendation → COMMERCIAL/T0 (wrap, bypasses SHAPING)
OFFER/DECISION/FOLLOW_UP: declared, not transitioned by ModeManager
Machine 2 — CRM deal FSM. amancore/sales/state_machine.py:7-26 new→contacted→engaged→discovery→qualification→offer_recommended→proposal→negotiation→awaiting_decision→won/lost→onboarding, strict transition(), owner overrides won/lost. Live use in SalesAgent: new→contacted→engaged→discovery per message; discovery→qualification→offer_recommended only when decision_readiness true; else pinned discovery/ask_next_question. Persisted conversations.current_state. CONFIRMED Interaction with Machine 1: none directly — SalesAgent state feeds agent_result (recommendation/objection) which planner maps to MODE jumps; the two can disagree (e.g. MODE=COMMERCIAL while CRM=discovery). INFERRED from code paths
Machine 3 — Handover (AI vs human). amancore/channels/handover.py:8 AI_ACTIVE,HUMAN_REQUESTED,HUMAN_ACTIVE,AI_RESUMED,CLOSED. Persisted conversations.mode (DB column, distinct from working_memory.mode). can_send_ai = mode in (AI_ACTIVE,AI_RESUMED) + channel flag. Set by human intent, needs_human, support escalate, summary approval. Overrides everything: AI sends nothing while HUMAN_* (except manual owner sends). CONFIRMED
Machine 4 — Pricing tiers T0/T1/T2/T3 + scope_review. Not a persisted enum; computed per price turn in _price_or_proposal_decision (pricing_flow.py:1-11, coordinator 1052+). scope_review (wm.scope_under_review) hard-blocks all figures. T3 = approved snapshot replay; T2 = Gate-B estimate+approval; T1 = public band; T0 = requirement question. Interacts by forcing price_plan.mode=COMMERCIAL regardless of planner MODE. CONFIRMED
Machine 5 — RIL statuses. requirements/models.py + schema.sql: Requirement.certainty explicit|inferred|system_generated, status captured|clarified|approved|estimated|in_progress|delivered|rejected, Priority must|should|nice, conflicts open|resolved|dismissed, decisions active|superseded|revoked, open_questions open|asked|answered|dismissed, scope_versions draft|presented|approved|superseded. Only captured/active/open/draft + superseded (decisions, snapshots, scopes) observed live; clarified/approved/estimated/rejected are declared, not driven by conversation turns. CONFIRMED
6. Question Selection Mechanism
A. Fixed predefined questions? Yes. policy.question_hints (7 fields × ar/en/id), suggestion_clarifiers pools, RIL QUESTION_BANK (7), legacy DiscoveryEngine.TEMPLATES (12), _SCOPE_REVIEW_QUESTIONS (6), _REQUIREMENT_QUESTIONS + pack required_info_to_estimate[0]. LLM adapts wording only. CONFIRMED
B. Missing fields? Yes — core mechanism. next_question sorts weights desc, returns first weight>0 + not field_known. field_known = any mapped fact key present (key_features←scope, scale←users, languages←languages, integrations←integrations, timeline←timeline, authority←authority, budget_band←budget). CONFIRMED policy.py:295-327
C. Weighted fields? Yes. Per-category weights (website key_features 9/integrations 8/languages 7/timeline 5/authority 4/scale 4, etc., _default fallback) + commercial_boost (budget 9/timeline 8/authority 7 in COMMERCIAL; budget forced 0 outside COMMERCIAL). RIL bank has separate base_wt×impact×miss×amb but first-match wins so weights are ordinal. CONFIRMED
D. LLM reasoning? No for selection. LLM receives brief with [{field}] + "{hint}" and phrases it. It cannot pick a different field without violating reask_known/brief; guard does not enforce field identity, so drift is possible but not designed. CONFIRMED
E. Domain playbooks? Partially. Industry packs inject typical_sections/features/goals + extension slices as DATA; suggestion_clarifiers vary by industry (association_ngo/restaurant/real_estate/ecommerce/_default); service_details pack supplies T0 questions. No step-by-step playbook engine. CONFIRMED
F. Previous context? Minimally: exclude_field=wm.last_question_field (no immediate repeat), _recent_history "do NOT repeat" instruction, intent_queue resume, suggestion_answers/pending matching. No semantic "what did we already cover" beyond field_known. CONFIRMED
G. Project state? Yes via facts + wm(service_category,industry,small_scope,suggestion_*,scope_review_*,crosssell_done). CONFIRMED
H. Customer intent? Shallowly: multi-category detect → queue; customer_delegated (suggestion_triggers) switches SHAPING to choice-intake; suggestion_skip skips to proposal; consultation/escalation keywords append brief lines. No intent-weighted reprioritization of the missing-field order. CONFIRMED
I. Novel question? No as intent. Output sentence is novel phrasing, but the question intent is always one of the predefined fields/bank/clarifiers. RIL clarification can surface as requirements_clarification only when plan.question is empty in NEED/SHAPING. CONFIRMED
J. Decide NOT to ask? Yes. next_question returns None when all weighted fields known (or budget-gated out); planner then emits "Do NOT ask any question this turn" (NEED) or _confirm (SHAPING). Test test_no_question_when_all_known covers it. CONFIRMED
K. Follow-up on exact previous answer? No dedicated mechanism. Closest: suggestion option-match (o.lower() in low_text across outstanding clarifiers), scope-delta recap line, merge_facts "clarify {k}" on conflicting value (which paradoxically keeps old value and queues a generic clarify token, not a contextual question). CONFIRMED
L. Reprioritize topics? Only via static weights + COMMERCIAL boost + intent_queue order. No dynamic "this matters more than the missing field" reasoning. CONFIRMED
7. Requirement Extraction
Exact function: ConversationPolicy.next_question(category, mode, facts, exclude_field) in amancore/conversation/policy.py:312-327. Inputs: category (policy keywords or wm), mode, facts dict, exclude=last_question_field. Decision: weights_for (category base + commercial boost or budget-zeroing) → sorted desc → first unknown with weight>0 → (field, hint_en); hint localized via question_hint(field, language). Priority system = static ints above; missing-field = field_satisfied_by mapping; exclusion = exclude_field + weight<=0 (budget outside COMMERCIAL); output = single (field,hint) or None. Scoring reproduction: no arithmetic beyond sort; RIL bank formula round(base×impact×miss×amb) clamped 1–100 (e.g. core_structure 95×1.0×1.0×0.95≈90) but order is bank order with skip-if-known predicates. Config: configs/conversation_policy.yaml:35-82 overrides policy.DEFAULTS. CONFIRMED
8. Implicit Requirement Handling
Extractor: RequirementsExtractor.extract() — 12 MODULE_RULES regexes (ecommerce, booking, payments incl. مدى|mada, whatsapp, auth_members, admin, inventory, invoicing, mobile_app, ai_automation, shipping, dynamic_content) + DECISION_RULES (currency IDR/USD/SAR/AED; languages ar+en/id+en/ar-only). Negation window 25 chars skips. Certainty = explicit (0.98) if direct-ask verb (أريد|نحتاج|want|need|butuh…) else inferred (0.85). CONFIRMED
Per-probe behavior (traced, not guessed):
- "something like Airbnb / like Noon for spare parts / like Haraj": does nothing special. No analogy/reference-app inference exists (grep for Airbnb/Noon/Haraj/reference-site: zero hits). If message contains متجر|ecommerce|منتجات it may tag ecommerce; otherwise only generic problem=stated facts. No hidden-implication, architecture, or contextual follow-up branch. CONFIRMED
- "pay by card and Mada": matches payments rule (مدى|mada|payment|visa…) → Requirement(payments, explicit/inferred) + RIL persist. No gateway-choice reasoning; T0/T1 question may later ask payments via weights/bank. CONFIRMED
- "may add mobile app later": matches mobile_app rule (no future-vs-now distinction) → stored as current requirement; planner cross-sell guard (planner.py:502-518) suppresses the "handle X later" line if X is already active scope — i.e. the system treats "later" as now. No phased-roadmap logic. CONFIRMED
- "I don't know what payment I need" / "you decide": only SHAPING suggestion_triggers (لا أدري|اقترح|you decide|up to you…, policy.py:126-129) switch to SUGGEST-INTAKE choice questions; outside SHAPING or with other phrasings ("I'm not sure", "whatever you think") there is no match → normal missing-field question continues. No defaults, no inferred answer, no alternatives offered. CONFIRMED
Requirement state taxonomy asked for: explicit|inferred exist; system_generated declared but never produced by live extract (only via LLM parse path, unused live); unknown|confirmed|rejected|conflicting|assumed — NOT IMPLEMENTED as extraction states (Status.REJECTED exists as a string, never set by any conversation path; no assumed/unknown/confirmed states anywhere). CONFIRMED
9. Recommendation Behavior
Only implemented recommender: pricing/offer.py:select_offer() — 4-branch keyword match on need/scope/outcome (app|mobile→mobile_app; erp|inventory|accounting|نظام→mini_erp; portal|custom|منصة→web_app; else business_website_system) + registry.offer_for_service + generic recommendation_message ("Based on what you've shared, I recommend our {service_name}…"). Surfaced by planner as COMMERCIAL/T0 "present by name + one-line WHY, invite reaction, NO price, ≤1 timeline/authority Q". CONFIRMED
Asked	Answer + evidence
Recommend features?	Only via industry pack features[:4]/typical_sections listed as value payload / structure proposal. No feature-level recommender function. [CONFIRMED planner.py:240-252]
Recommend architecture?	No. No architecture/MVP/phasing/trade-off/challenge/alternative logic exists. [CONFIRMED — grep zero hits]
Recommend MVP?	No.
Recommend phased delivery?	Only as a canned negotiation-ladder sentence (planner objection wrap + negotiation.py + objection_handling.py ladder value→scope-reduce→phased→smallest). No real phasing plan. [CONFIRMED]
Explain trade-offs?	No.
Challenge a requirement?	No, except ConflictDetector's 3 hardcoded pairs (no_auth×auth_members, offline_only×payments, static_presence×inventory) which only create a requirement_conflicts row — nothing in the reply path reads conflicts. [CONFIRMED conflicts.py:16-36]
Say solution not optimal?	No.
Propose alternatives?	Only alternative_offer: Business Presence Starter string in objection ladder + one cross-sell "handle X later" line (once, suppressed if X is current scope). [CONFIRMED]
10. Memory Architecture
Layer	Stored where	Who writes / when	Who reads	Retention / survival
Raw messages	channel_messages(channel,direction,external_user_id,lead_id,body,hidden,status) unique (channel,external_message_id)	recorder every inbound; outbox every outbound	_recent_history(8), _recent_assistant_replies(2), rollup counter	Survives restart (SQLite); survives session while identity same; retention.yaml: active conv 90d, inactive lead 365d [CONFIRMED]
Recent messages (IN CONTEXT)	Not stored; built per turn: 8 rows × 90 chars + [:700] draft cap / [:600] quote	_recent_history per draft	LLM drafter only	Ephemeral [CONFIRMED]
Working memory	conversations.working_memory JSON: mode, industry, service_category, intent_queue, last_question_field, structure_proposed, small_scope, suggestion_*, scope_review_*, crosssell_done, return_mode	planner hydrate/_wm + persist (re-read-then-save) + _update_scope_review every turn	planner, T1/T2, pricing	Survives restart + multi-session (same lead) [CONFIRMED]
Facts	conversations.facts JSON (scope, users, languages, integrations, timeline, authority, budget, problem, outcome, scope-delta flags…)	extract_facts + merge_facts per turn	policy.next_question, gates, fingerprint, hours	Survives restart/session [CONFIRMED]
Conversation summary	conversations.summary TEXT: deterministic reducer (ordered keys, 220ch) + 10-msg rollup (≤500ch, industry/scope/budget/timeline/authority/mode)	reducer at brief build (read-time); rollup every 10th inbound	planner brief tag "Conversation context:"; OPENING relationship line	Survives restart [CONFIRMED]
Structured requirements	requirements/requirement_conflicts/project_decisions/open_questions/project_scopes/scope_versions/scope_items tables	RIL process_message per turn	coverage/question/scope_builder; planner receives only next_question string + coverage %	Survives restart; decisions supersede chain, requirements dedup by subcategory [CONFIRMED]
Project decisions/assumptions/open questions	Same tables; `decisions status active	superseded	revoked, decided_by customer	owner
Historical state	conversations.current_state/next_action/preferences/unknowns/objections, events/audit, learnings.jsonl, usage_records/cost_counters	agents/coordinator/learning per turn	followup, owner console, metrics	Audit+brain permanent per retention [CONFIRMED]
STORED ≠ RETRIEVED ≠ IN CONTEXT ≠ USED: all inbound text is STORED; RETRIEVED per turn = facts + wm + 8×90ch + 220ch summary + RIL question/coverage%; IN CONTEXT for LLM = brief + base + that slice (caps above); USED FOR DECISION = only facts/wm/coverage/brain/config (LLM output cannot change price/scope/approvals — guard enforces). CONFIRMED
11. Long-Horizon Conversation Handling
Genuine 20/40/60/100-msg, 2h, multi-session support? Stored yes; reasoned-over no. CONFIRMED
- Truncation: _recent_history(limit=8), body [:90], draft [:700]/[:600], known JSON [:350], summary [:220], rollup [:500]. No rolling compaction beyond reduce_memory + 10-msg rollup. No rehydration beyond get_or_create (same lead). No summary refresh except rollup. CONFIRMED
- 60-msg test: an early requirement survives only if captured into facts (field_known keys) or RIL requirements/decisions tables. Anything else (nuance, constraints, "no mobile app", budget context without digits) falls out of the 8×90ch window and the 220ch summary and never influences T1/T2/fingerprint/hours. INFERRED from caps + field lists; mechanism CONFIRMED
- Multi-session: same (channel, external_user_id) → same lead → facts/wm/summary resume (OPENING branch even acknowledges consent_at returnees). Different channel = new lead, no cross-link. No session-expiry test found. CONFIRMED
12. Contradiction Handling
"I do not need mobile app" (msg 10) → "Actually I want Android and iOS" (msg 35): CONFIRMED traces
- Deterministic extractor negation window (25 chars) skips creating a requirement for the negated mention; but SalesAgent merge_facts: on old != new it appends "clarify {k}" to open_questions and keeps the old value (conversation_memory.py:117-129). No overwrite, no history, no obsolete marking, no scope update from this path.
- RIL path: same subcategory → update_requirement(last_seen_at, confidence=max) — confidence only ratchets up; no value comparison, no supersede. Different subcategory (e.g. no_auth vs auth_members) → ConflictDetector only fires for its 3 hardcoded pairs; mobile yes/no is not one → no detection, no clarification question from this path (RIL question bank has no contradiction question).
- Scope withdrawal (_withdrawn_fields + _update_scope_review): handles negated booking/payments/integrations/languages/member_areas/dynamic_content by clearing facts[f]=False and dropping pending delta — the only true "change of mind" mechanism, and it covers 6 fields only.
- Net: the mobile-app flip adds a second value / leaves stale state / asks at most a generic next missing-field question; nothing detects the contradiction, records history, or updates scope version for it. CONFIRMED
13. Topic Switching
Realistic sequence (ecommerce → server → Mada → SEO → Noon → price → mobile app): CONFIRMED mechanics, outcome INFERRED per branch
- Context preserved as facts/wm; intent_queue captures multiple categories mentioned in one message (primary leads, extras queued with "noted, will cover next" ack + resume_note "continuing the topic…"). Sequential single-topic turns do not queue — each turn re-detects category from current text or falls back to wm; a server/SEO/Mada question with no service keyword keeps prior service_category (T2 parity fix explicitly does this).
- "What server do you recommend?" → no hosting-advisory logic; answered from brief + company facts generically; discovery does not advance (no fact captured). "Can you integrate Mada?" → payments fact/requirement captured; scope-delta only if addition signal (add/also/plus/أضيف/كمان) co-occurs, else treated as question, not scope change. "What about SEO?" → standards slice (Schema.org v30) appended as tagged DATA + generic reply. "Something like Noon" → no-op (see §8). "How much?" → full pricing dispatch from fresh state (scope_review first). "Also need mobile app" → mobile_app requirement added, but pricing fingerprint uses category (still ecommerce/website) — the app does not re-route the estimate; cross-sell guard may misfire-suppress.
- Return to main discovery: yes via wm.service_category persistence + exclude_field rotation, but the detour questions each consume a turn's single question budget and can flip MODE to COMMERCIAL prematurely if they contain price/budget/timeline words. No stack-based return; queue depth is at most the categories in one message. CONFIRMED
14. Pricing Trigger Logic
Every trigger found (exhaustive grep): CONFIRMED
- _PRICE_INTENT (coordinator.py:81-85): price|cost|berapa|harga|سعر|بكم|كم تسوى|كم تكلف|كم ثمن|كم سعر|سيكلف|يكلف|quote|proposal|تسعير|estimate → sets price_request → pricing decision after planning. This is the event that causes pricing entry.
- commercial_signals (policy.py:114-119 + yaml): adds كم تستغرق|مدة|متى|الميزانية|من يقرر|عرض سعر|دفعة|how long|timeline|budget… → MODE→COMMERCIAL + budget/timeline/authority boost (not itself a price reply).
- _SALES (support/intent.py:47-50): buy|price|quote|website|cost|أريد|سعر|موقع… → stays in sales lane (not support).
- Scope-withdraw/add, risk/policy/claim gates, approval-intent (موافق/نعم + negation-safe) → handover for official quote, never auto-price.
 Per-example: "How much would something like this cost?" (cost) → enters pricing decision. "Later we can discuss the price" (price) → also enters (false positive by design — regex has no tense/intent parsing). "My budget is $10,000" → budget fact captured; price_request false (budget ∉ _PRICE_INTENT) → no pricing reply, but MODE boosts commercial. "Is this expensive?" → no match → objection path (price_high), negotiation wrap, no figures. "Give me a rough idea" → no match → normal discovery (no pricing). CONFIRMED
Statement "Whenever the customer mentions price, AmanCore attempts to enter the pricing flow": TRUE for the regex's word list — every match runs _price_or_proposal_decision (which may still answer T0 with zero figures, but it is the pricing flow, with approval/snapshot side effects possible at T2). CONFIRMED
15. Pricing Readiness / Gate Logic
Decider: QuoteFlow.gate_b_ready() + ConversationPolicy.t1_min_scope() + scope_under_review + snapshot fingerprint, orchestrated in _price_or_proposal_decision → _t2 → _t1 → _requirement_reply. CONFIRMED
- Required for T1 (public starting band, no approval): category detected + t1_min_scope = any one of (scope,timeline,users,pages,page_count,languages,integrations,payment_gateways,gateways,booking,payments,member_areas,dynamic_content,budget). CONFIRMED policy.py:358-367
- Required for T2 (indicative low–high + owner final_price approval request): category + key_features known (facts.scope) + (timeline OR scale/users). CONFIRMED pricing_flow.py:42-49
- Required confidence/features/assumptions/timeline/scale: none beyond above. No confidence threshold, no required integrations/languages/authority/architecture, no coverage % gate on the live path (RIL is_ready ≥70 + no critical gaps is computed but never consulted by the pricing dispatch). CONFIRMED
- Can a price-range be generated while important architecture is unknown? Yes. T1 needs one fact (e.g. only timeline); T2 needs scope + timeline/users with zero knowledge of payments, integrations, languages, auth, scale, or constraints. T2 hours then come from _estimate_hours_with_ai (LLM guess 5–500) or calculate_dynamic_hours defaults. CONFIRMED
16. Complete Pricing Pipeline
Price intent (_PRICE_INTENT match)
   ↓  coordinator._price_or_proposal_decision() [re-reads fresh mem; scope_under_review→clarify, zero figures]
Gate: scope fingerprint vs approved snapshot → T3 replay verbatim OR supersede(scope_change) [snapshots.supersede, audit]
   ↓  no valid snapshot
T2 attempt: _t2_estimate_reply() — gate_b_ready? → _estimate_hours_with_ai() (ROUTINE JSON {total,frontend,backend,integrations,qa_deploy,summary_ar}, accept 5–500) else dynamic hours → QuoteFlow.estimate() (PricingEngine.price: shadow 40, revision .15, risk .15×RISK_FACTOR, markup/market_mult/min_mult by policy_key, rough=hours×shadow×markup×mult, fees, validate, confidence) → round100 low=floor/high=target → IDR convert+freeze (rate,date,usd_base) → scope_fingerprint → QuoteFlow.request_owner_approval() (INSERT approvals final_price/high + emit + Telegram /qapprove alert + opportunity auto-create)
   ↓  Gate-B fail
T1 attempt: _t1_band_reply() — category + t1_min_scope + public_band(Brain price_bands_public) + mini_scope if small + market localize (gcc USD, indonesia IDR frozen, else None→T0) → _draft_reply wording-only (digits verbatim, never final)
   ↓  no band
T0: _requirement_reply() — pack required_info_to_estimate[0] → legacy business_system Q → generic; zero figures
   ↓  every branch
_price_guard_plan() (T1/T2 allow only low/high; T3 trust reply digits; T0/scope_review allow none; mode=COMMERCIAL) → _queue_reply() → QualityGuard → outbox → owner approval (QuoteFlow.finalize: approve→snapshot create approved_price, expires+14d, opp→offer_ready) → next price ask replays T3 frozen text+specs+infra+50/50 terms
Each stage file/function/IO/persistence as in table §2; math is deterministic, LLM does wording (+hours guess) only. CONFIRMED
17. LLM vs Deterministic Control
Decision	LLM	Python	Config	DB State	Hybrid
Next question	 	● (policy.next_question; LLM phrases only)	● (weights/hints)	● (facts/wm)	 
Requirement extraction	 	● (regex + merge; LLM extraction gated/secondary)	 	● (persist/dedup)	 
Recommendation	 	● (select_offer keyword map; LLM phrases)	 	● (Brain services/offers)	 
Discovery completion	 	● (readiness=5 BANT facts; coverage unused live)	 	●	 
Pricing entry	 	● (_PRICE_INTENT regex)	 	 	 
Final price	 	● (engine + owner approval + snapshot replay)	 	● (Brain bands/policy, approvals, snapshots)	 
Human handover	 	● (human intent/needs_human/escalate/approval/summary)	 	● (mode)	 
LLM task classes: ROUTINE (drafts, hours estimate), extraction (facts, gated), reasoning (localize high-risk); configured pricing class is unused live. Validation chain on every planned turn: CostGovernor (pre) → ExternalResponseFilter → QualityGuard (+1 redraft) → ChannelPolicy. CONFIRMED
18. Prompt Inventory
File	Function	Purpose / behavioral instructions	Inputs	When called	Model
coordinator.py	_draft_reply system+user	Main drafter: brand AmanCode, 55 words, LANGUAGE LOCK same script, convey DRAFT exactly, never invent price/discount/deadline, steer unrelated back, do-not-repeat RECENT CHAT, LEARNINGS background-only, COMPANY FACTS	plan.brief, plan.base, text, history(8×90), learnings, business_context	every non-price turn + T1/T2 wording + handoff/support fallback + guard redraft	ROUTINE (gemini-3.6-flash → glm-5.3-flash)
coordinator.py	T1/T2 brief	T1: convey range digits verbatim, never final; T2: tentative, under engineering review, warm close	fixed low/high/currency	inside T1/T2	same
coordinator.py	_estimate_hours_with_ai	Senior estimator JSON-only {total,frontend,backend,integrations,qa_deploy,summary_ar} with per-category hour bands	category, message, facts, history	T2 only	ROUTINE
coordinator.py	_draft_quote_reply	Price-safe 40-word no-price + 1 qualifying Q (legacy/unused send path)	notes_summary, learnings	legacy	ROUTINE
planner.py	plan.brief	WHAT: mode behavior + value payload + exactly-one-question + tier + 12 interaction layers + polish + quality contract	lead/mem/agent_result/text/lang/channel/ril	every planned turn	— (steers drafter)
sales/conversation_memory.py	_FACT_PROMPT	Extract {problem,outcome,process,users,scope,timeline,budget,authority,constraints,integrations,languages…} JSON	message	per turn unless gated	extraction
skills/localization.py	_LOCALIZE_PROMPT	Market adapt, keep claims/CTA/brand	reply text	ar/id replies	routine/reasoning
ops/learning.py	learning prompt	One learning {category,value ≤8 words}	exchange	async after AI turn	primary provider
support/*, sales/discovery	templates	Canned safe replies / legacy questions	—	support lane / SalesAgent	none
skills/objection_handling	_LADDER	value→scope-reduce→phased→smallest texts	objection id	objection wrap	none (deterministic)
Huge prompts not reproduced; summaries accurate to source. CONFIRMED
19. Configuration Inventory
- configs/conversation_policy.yaml → controls categories/aliases, question weights + commercial boost + budget gate, field mapping, hints, verbs/signals, suggestion clarifiers/skip, small-scope triggers. Read by ConversationPolicy.load (missing-safe). Changes question order, MODE jumps, T1/T2 eligibility, suggest-intake. CONFIRMED
- configs/models.yaml → controls provider order + task routing + price table. Read by _drafter. Changes which LLM phrases drafts. CONFIRMED
- configs/channels.yaml → adapters, bridge vs production, outbox atomic, secrets. Read by build_runtime/provider_resolver. Changes deliverability, not wording. CONFIRMED
- configs/app.yaml → cost governor limits, warmup tiers, followup template. Read by governor/compliance. Changes send blocking + followup. CONFIRMED
- configs/support.yaml, lead_scoring.yaml, alerts/analytics/insights/retention/scheduler → support SLAs, score weights/thresholds, briefing/followup cadence. Read by respective services. Do not steer phrasing. CONFIRMED
- business_brain/data/v1.yaml (seed v1 immutable, owner-only writer, 22-section validator) → services/offers, pricing_policy (shadow 40, markups 2.5–4.0, minimums, market_mult), pricing_profiles/base_hours, add-ons, price_bands_public (website 1500–4200+mini 450–1200; ecommerce 5100–14800; mobile 6600–25800; business_system 12100–42600; automation 8100–28400 USD gcc), market_profiles, fx (USD_IDR 17650), industry_profiles (14), objections (12), claims, sales/negotiation/decision policies. Read by planner/registry/engine/offer/fx. Changes identity, bands, hours, gates. CONFIRMED
- knowledge/packs/* + interaction_rules.v1.yaml + brand_identity.yaml + sources.registry → DATA-only slices (sections, processes, pains, integrations, maturity, decision-roles, standards, register, variation, recap, escalation triggers). Read by retriever/planner. Change phrasing/pacing only by design. CONFIRMED
20. Test Coverage
Scale of conversation tested: max 3 messages (sales_scenarios clear_qualified_lead, 3 msgs); channel scenarios max 2 messages; pricing/object/handover/optout/duplicate/malformed/language all 1 message. No 10/20/40/60-msg, no long-horizon, no session-recovery, no multi-session tests. CONFIRMED — fixtures listed §19 + tests/fixtures/*.json
Asked	Exists?
3-message	Yes (sales_scenarios.clear_qualified_lead; pricing unit tiers) [CONFIRMED]
10/20/40/60-message, long-horizon discovery	No [CONFIRMED]
Ambiguous clients	Partial: vague-budget/indirect-authority gating unit (test_p02_hybrid_extraction), objection evals (24 ar/en scenarios), interaction realism (15) [CONFIRMED]
"I don't know"	Only via suggestion-trigger unit paths + SHAPING intake; no dedicated "don't know / you decide / not sure / whatever" E2E matrix [CONFIRMED]
Changing requirements	Only fingerprint/withdrawal/T1-T2 language unit (test_scope_change_probe, test_p03 scope supersede) [CONFIRMED]
Topic switching	Only multi-intent unit in planner tests; no realistic 7-topic E2E [CONFIRMED]
Implicit requirements	No (no analogy/reference tests) [CONFIRMED]
Recommendations	test_recommendation_engine + sales_flow discovery→recommend+opportunity+score (keyword mapping, not quality) [CONFIRMED]
Pricing before scope (T0/T1 guard)	Yes: test_p03 T0 deferral, T1 min-scope, Gate-B matrix, price-before-approval no-invent [CONFIRMED]
Pricing after scope (T2→approval→T3→supersede)	Yes unit+integration: approval→snapshot→proposal review, double-finalize reject, scope-change supersede [CONFIRMED]
Human handover	Yes: test_handover modes, approval-intent negation-safe, support escalate, sales_flow handoff [CONFIRMED]
Session recovery	No [CONFIRMED]
Gaps (missing E2E): live T1→T2→override→T3→scope-change→T2 with real router; custom /qapprove <price> override; IDR freeze round-trip; mini_scope branch; LLM-failure/cost-blocked price turn; pricing task-class routing (unused); concurrent duplicate price asks; Arabic scope_review numbers-blocked E2E; consultation booking E2E. CONFIRMED by absence
21. Real Conversation Evidence
No real customer transcripts exist in repo/fixtures/logs/exports/datasets. All fixtures synthetic (sales/pricing/channel/content/ops/insights/lead_research JSON, 1–3 msgs). Only production-derived corpora: storage/metrics/first_pass.jsonl + learnings.jsonl (not checked in, not inspected here). Therefore per-conversation message counts, durations, question/recommendation counts, missed requirements, price-introduction points, and "felt like questionnaire" judgments: UNVERIFIED — no evidence in repository. Anonymization N/A. CONFIRMED by exhaustive fixture listing
22. Exact Root Cause of Premature Pricing
Ranked causes (all CONFIRMED in code):
1. Price-word shortcut into pricing dispatch. _PRICE_INTENT fires on any of 16 substrings with no intent/tense/coverage check ("later we can discuss the price" counts). The turn still runs discovery first (P1 fix), but the reply comes from the pricing branch, and T2 performs approval-creating side effects. This is the dominant mechanism.
2. T1 gate = 1 fact. t1_min_scope needs any single scope-context fact; a bare "I want a website" + one timeline/users/budget word is enough for public-band figures on the next price ask.
3. Gate-B = 2 facts. scope + (timeline|users) unlocks a computed indicative range + owner approval request while payments/integrations/languages/authority/architecture remain unknown.
4. Instant COMMERCIAL jump. commercial_signal (price/cost/budget/timeline/مدة/متى…) forces initial_mode/advance → COMMERCIAL on turn 1, unlocking budget questions + T1/T2 framing in the planner brief even before NEED/SHAPING ran.
5. RIL readiness unused. CoverageAnalyzer.is_ready (≥70, no critical gaps) is computed and logged but never gates pricing; QualificationEngine.decision_readiness gates only the legacy SalesAgent recommendation, not T1/T2.
6. Sounding-final wording. T1/T2 briefs + deterministic Arabic openers present ranges confidently; only the guard's final-wording list (سعر نهائي/final price/السعر هو…) + "starting/tentative" phrasing separate them from quotes.
Mitigations that do work: scope_under_review hard block (any unresolved add-delta → zero figures), T0 fallback, _price_guard_plan + QualityGuard number allow-listing, snapshot fingerprint invalidation, owner-only finalize. They bound damage; they do not raise the entry bar. CONFIRMED
23. Current Behavioral Model
Real loop, plain language: CONFIRMED
1. Receive message (webhook/bridge → CanonicalEvent, dedup by wa:/fb:/ig:/tg: id)
2. Load/create lead by (channel, user id) + backfill consent; record inbound
3. Load memory (facts + working_memory + summary); detect language
4. Bookkeep scope delta every turn (addition-signal + 6-field keywords; negation clears; unresolved → scope_under_review block)
5. Apply hard gates (opt-out hold; AI-disabled/human-active hold; opt-out keyword; human-request → handoff reply)
6. Route intent (legal/billing/complaint or existing-customer support/general → SupportAgent lane; else sales lane)
7. Extract (RIL regex 12 modules + decisions → persist/dedup; SalesAgent deterministic facts + gated LLM extraction → merge; qualify BANT; legacy discovery question or keyword offer)
8. Plan deterministically (multi-intent queue; industry; MODE advance; ask = highest-weight missing field excl. last; COMMERCIAL tier T0/T1/T2 pre-check; brief + quality contract + 12 interaction garnishes)
9. Persist working_memory (re-read-then-save) + followup seed + 10-msg rollup
10. If price-word matched → pricing dispatch from fresh state (scope_review → T3 frozen replay/supersede → T2 Gate-B estimate+approval → T1 public band → T0 requirement question), guard-plan it
    Else → single LLM draft of the brief (language-locked, 55 words, do-not-repeat), cost-governed
11. Validate (leak filter → QualityGuard + one redraft → fallback), policy-check, enqueue idempotent outbox
12. Drain outbox (capability + policy + valve + send + mark_sent/failed/uncertain); approval → owner /qapprove → snapshot → future price asks replay frozen quote until scope fingerprint changes
Behavioral character: missing field → ask one question → fill field → next missing field, dressed with value-first structure proposals, industry DATA lines, and warm LLM phrasing; interrupted at any price-word by the pricing branch. CONFIRMED
24. Unknowns / Missing Evidence
- Production adapter mix + bridge-vs-direct volumes: UNVERIFIED (config-dependent, no prod dump inspected).
- Real conversation outcomes (counts, durations, recommendations, missed reqs, questionnaire feel): UNVERIFIED (no transcripts in repo).
- LLM phrasing variance in the wild (drift off-brief, language-lock failures): UNVERIFIED (fakes in tests, first_pass.jsonl not inspected).
- Timing/latency under load, cost-governor trip frequency, provider fallback frequency: UNVERIFIED (no prod metrics inspected).
- Owner approval latency/override behavior (/qapprove <price> custom): UNVERIFIED (untested path).
- Cross-channel identity merges: UNVERIFIED (no linking logic found; treated as separate leads — INFERRED).
Capability	Current Implementation	Evidence	Confidence
Long conversations	Stored fully; LLM sees 8×90ch + 220ch summary + facts; 10-msg rollup only	coordinator._recent_history, memory_reducer, _relationship_maintenance	[CONFIRMED]
Context retention	Facts/wm/RIL tables persist per lead; nuance outside them is lost	conversation_memory, RIL service, caps	[CONFIRMED]
Requirement extraction	12-regex modules + currency/language decisions + gated LLM facts; explicit 0.98 / inferred 0.85	requirements/extractor, sales/conversation_memory	[CONFIRMED]
Implicit requirement detection	None (no analogy/architecture/future-vs-now inference; Mada→payments keyword only)	grep zero + MODULE_RULES	[CONFIRMED]
Recommendation	4-branch keyword service pick + generic message + industry structure list; no MVP/architecture/trade-offs	pricing/offer, planner value payload	[CONFIRMED]
Handling "I don't know"	SUGGEST-INTAKE choices only on exact trigger phrases in SHAPING; else next missing-field Q	policy.suggestion_*, planner SHAPING	[CONFIRMED]
Contextual follow-up	None (exclude-last + do-not-repeat + option-match only)	next_question(exclude), _recent_history	[CONFIRMED]
Contradiction handling	Old value kept + "clarify k" token; 3 hardcoded conflict pairs (unread by replies); 6-field withdrawal only	merge_facts, conflicts, _withdrawn_fields	[CONFIRMED]
Topic switching	Per-turn re-detect + one-message intent_queue; no stack; price-word hijacks to pricing branch	planner intents, _PRICE_INTENT	[CONFIRMED]
Discovery completion	BANT 5-fact readiness (legacy recommend only); coverage % unused; planner can stop asking when all known	qualification, coverage, next_question→None	[CONFIRMED]
Premature pricing protection	scope_review block + T0 fallback + guards work; entry bars (T1=1 fact, T2=2 facts, any price-word) are low	coordinator pricing dispatch, policy gates	[CONFIRMED]
Rough estimate	T1 public band (no approval) + T2 indicative (approval-pending), both LLM-worded, guard-allow-listed	_t1/_t2_band_reply, pricing_flow	[CONFIRMED]
Final quote	Owner /qapprove → frozen snapshot replayed verbatim until fingerprint changes; proposal variant	QuoteFlow.finalize, _price_or_proposal_decision T3	[CONFIRMED]
Human handover	Human-intent/needs_human/escalate/summary-approval → HUMAN_REQUESTED (+channel kill-switch); AI silenced	handover, coordinator gu

ards	[CONFIRMED]
Project state	facts + working_memory + RIL tables + snapshots + scopes; versioned only for decisions/snapshots/scopes	schema + memory + RIL + pricing	[CONFIRMED]
Here is what the current implementation actually does.



ماذا اذا ارسل العميل برسالة بطريقة اخرى لاختلاف اللهجة او في رسالة مركبة كبيرة الن يعرف النظام هذا, لماذا لا تجعل الAI يقرر الى رسالة يعني مثلا يوجد كم السعر او السعر  لكن اذا ارسل العميل التطبيق هذا كم من الممكن ان يكون سعره او النظام هذا كم من الوقت وكم سيكون تكلفته هنالك الاف السيناريهوهات هل يعني اننا يجب ان نعمل كل هذه السيناريوهات او هل هنالك طريقة نجل الAI ينظر الى الرسالة ثم يقرر هل هو يسال عن السعر او عن سعر شيء معين فقط او عن وقت انتهاء المشروع او وقت شيء اخر اريد ان يكون ذكي جدا لكي يفهم مقصد العميل بالضبط او اذا كانو يتحدثون عن سلعة ما ثم يتحد العميل كم سعرها هل سيكون سعر السلعة او سعر النظام او التبطيق الذي يريده 
