-- AmanCore Foundation schema (SQLite)
-- All ids are 32-hex UUID strings. Timestamps are ISO-8601 UTC strings.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'new',
    lead_score INTEGER NOT NULL DEFAULT 0,
    lead_stage TEXT NOT NULL DEFAULT 'nurture',
    source_channel TEXT,
    source_campaign TEXT,
    source_content_id TEXT,
    source_referral_id TEXT,
    source_search_term TEXT,
    name TEXT,
    company TEXT,
    role TEXT,
    country TEXT,
    market TEXT,
    language TEXT,
    industry TEXT,
    website TEXT,
    contact_whatsapp TEXT,
    contact_email TEXT,
    contact_linkedin TEXT,
    contact_website TEXT,
    preferred_channel TEXT,
    opt_out INTEGER NOT NULL DEFAULT 0,
    service_interest TEXT,
    project_type TEXT,
    need TEXT,
    desired_outcome TEXT,
    urgency TEXT,
    budget_range TEXT,
    budget_confidence TEXT,
    authority TEXT,
    timeline TEXT,
    project_clarity TEXT,
    business_value TEXT,
    engagement TEXT,
    score_breakdown TEXT,
    fit_signals TEXT,
    provenance TEXT,
    owner TEXT,
    next_action TEXT,
    last_contact_at TEXT,
    next_followup_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE CASCADE,
    channel TEXT,
    language TEXT,
    facts TEXT,
    preferences TEXT,
    requirements TEXT,
    unknowns TEXT,
    decisions TEXT,
    open_questions TEXT,
    objections TEXT,
    summary TEXT,
    current_state TEXT,
    last_message_at TEXT,
    next_action TEXT,
    next_followup_at TEXT,
    external_thread_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    company TEXT,
    market TEXT,
    language TEXT,
    currency TEXT,
    contacts TEXT,
    support_status TEXT,
    relationship_status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id TEXT PRIMARY KEY,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    customer_id TEXT REFERENCES customers(customer_id) ON DELETE SET NULL,
    service TEXT,
    offer_id TEXT,
    scope_summary TEXT,
    estimated_value REAL,
    currency TEXT,
    pricing_status TEXT,
    proposal_status TEXT,
    stage TEXT,
    probability REAL,
    expected_close_date TEXT,
    reason TEXT,
    owner TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(customer_id) ON DELETE SET NULL,
    opportunity_id TEXT REFERENCES opportunities(opportunity_id) ON DELETE SET NULL,
    service TEXT,
    scope TEXT,
    deliverables TEXT,
    timeline TEXT,
    status TEXT,
    milestones TEXT,
    hours_logged REAL NOT NULL DEFAULT 0,
    planned_cost REAL,
    actual_cost REAL,
    margin REAL,
    support_plan_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS care_plans (
    care_plan_id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(customer_id) ON DELETE CASCADE,
    plan_tier TEXT,
    services TEXT,
    billing_cycle TEXT,
    price REAL,
    currency TEXT,
    status TEXT,
    start_date TEXT,
    renewal_date TEXT,
    usage TEXT,
    support_limits TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    requested_by TEXT,
    requested_at TEXT NOT NULL,
    risk_level TEXT,
    reason TEXT,
    payload TEXT,
    policy_reference TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    approved_by TEXT,
    decision TEXT,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    payload TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    locked_by TEXT,
    locked_until TEXT,
    started_at TEXT,
    next_attempt_at TEXT,
    idempotency_key TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    severity TEXT NOT NULL,
    category TEXT,
    title TEXT,
    summary TEXT,
    evidence TEXT,
    action_required TEXT,
    related_entity TEXT,
    correlation_id TEXT,
    fingerprint TEXT,
    dedup_key TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    transport TEXT,
    delivered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    component TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    description TEXT,
    evidence TEXT,
    action_taken TEXT,
    owner TEXT,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backups (
    backup_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT,
    size_bytes INTEGER,
    status TEXT NOT NULL DEFAULT 'created',
    verified_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source TEXT,
    channel TEXT,
    actor_type TEXT,
    actor_id TEXT,
    timestamp TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    idempotency_key TEXT,
    risk_level TEXT,
    payload TEXT,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    actor TEXT,
    agent TEXT,
    action TEXT,
    resource TEXT,
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    approval_id TEXT,
    correlation_id TEXT,
    result TEXT
);

CREATE TABLE IF NOT EXISTS content_items (
    content_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'draft',
    content_type TEXT,
    market TEXT,
    language TEXT,
    platform TEXT,
    title TEXT,
    topic TEXT,
    angle TEXT,
    hook TEXT,
    body TEXT,
    cta TEXT,
    source_research_ids TEXT,
    claim_status TEXT,
    approval_status TEXT,
    risk_level TEXT,
    quality_json TEXT,
    content_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_results (
    research_result_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    company_name TEXT,
    website TEXT,
    industry TEXT,
    country TEXT,
    city TEXT,
    market TEXT,
    public_contact TEXT,
    social_profiles TEXT,
    digital_presence_signals TEXT,
    likely_needs TEXT,
    service_fit TEXT,
    confidence TEXT,
    source TEXT,
    source_url TEXT,
    research_method TEXT,
    retrieved_at TEXT,
    fit_json TEXT,
    payload TEXT,
    content_hash TEXT,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pricing_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    opportunity_id TEXT REFERENCES opportunities(opportunity_id) ON DELETE SET NULL,
    pricing_version TEXT,
    business_brain_version INTEGER,
    inputs TEXT,
    calculated_result TEXT,
    approved_price REAL,
    currency TEXT,
    approved_by TEXT,
    approved_at TEXT,
    expiration_at TEXT,
    status TEXT NOT NULL DEFAULT 'approved',
    scope_fingerprint TEXT,
    superseded_at TEXT,
    superseded_by TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    opportunity_id TEXT REFERENCES opportunities(opportunity_id) ON DELETE SET NULL,
    version INTEGER NOT NULL DEFAULT 1,
    pricing_snapshot_id TEXT,
    business_brain_version INTEGER,
    status TEXT NOT NULL DEFAULT 'draft',
    body TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS message_outbox (
    message_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    recipient TEXT,
    message_type TEXT NOT NULL DEFAULT 'text',
    payload TEXT,
    idempotency_key TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    lead_id TEXT,
    conversation_id TEXT,
    correlation_id TEXT,
    provider_message_id TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    claimed_at TEXT,
    claim_token TEXT,
    initiation TEXT,
    delivery_status TEXT
);

CREATE TABLE IF NOT EXISTS intake_events (
    intake_id TEXT PRIMARY KEY,
    ip TEXT,
    email TEXT,
    lead_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,
    operation TEXT,
    result TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_records (
    request_id TEXT PRIMARY KEY,
    provider TEXT,
    model TEXT,
    task_class TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost REAL,
    latency_ms INTEGER,
    status TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- legacy-compat default kept ONLY so fresh and upgraded databases share
    -- one authoritative shape; every writer MUST pass an explicit channel.
    channel TEXT NOT NULL DEFAULT 'whatsapp',
    direction TEXT NOT NULL CHECK (direction IN ('in','out')),
    external_user_id TEXT NOT NULL,
    lead_id TEXT,
    external_message_id TEXT,
    body TEXT NOT NULL,
    status TEXT,
    created_at TEXT NOT NULL,
    media_kind TEXT,
    media_ref TEXT,
    outbox_message_id TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    reaction TEXT,
    quoted_external_message_id TEXT
);

-- Channel-neutral customer identity: one row per (channel, provider user id).
-- The Core resolves customers through this table; leads.contact_whatsapp is
-- a legacy display/fallback column only.
CREATE TABLE IF NOT EXISTS platform_identities (
    identity_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(lead_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    external_user_id TEXT NOT NULL,
    external_username TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(channel, external_user_id)
);


CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(lead_stage);
CREATE INDEX IF NOT EXISTS idx_leads_next_followup ON leads(next_followup_at);
CREATE INDEX IF NOT EXISTS idx_leads_website ON leads(website);
CREATE INDEX IF NOT EXISTS idx_conversations_lead ON conversations(lead_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_stage ON opportunities(stage);
CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_content_status ON content_items(status);
CREATE INDEX IF NOT EXISTS idx_content_hash ON content_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_research_lead ON research_results(lead_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_opportunity ON pricing_snapshots(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_proposals_opportunity ON proposals(opportunity_id);
CREATE TABLE IF NOT EXISTS support_cases (
    case_id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(customer_id) ON DELETE SET NULL,
    lead_id TEXT REFERENCES leads(lead_id) ON DELETE SET NULL,
    project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
    conversation_id TEXT,
    category TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'LOW',
    status TEXT NOT NULL DEFAULT 'open',
    summary TEXT,
    description TEXT,
    requested_action TEXT,
    owner TEXT,
    escalated INTEGER NOT NULL DEFAULT 0,
    sla_policy TEXT,
    resolved_at TEXT,
    reopened_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_support_status ON support_cases(status);
CREATE INDEX IF NOT EXISTS idx_support_customer ON support_cases(customer_id);
CREATE INDEX IF NOT EXISTS idx_support_priority ON support_cases(priority);
CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    evidence TEXT,
    metrics TEXT,
    period TEXT,
    segment TEXT,
    confidence TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'LOW',
    business_impact TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    recommendation_id TEXT,
    related_entities TEXT,
    fingerprint TEXT,
    expires_at TEXT,
    superseded_by TEXT,
    detected_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id TEXT PRIMARY KEY,
    insight_id TEXT,
    type TEXT NOT NULL,
    title TEXT,
    problem TEXT,
    evidence TEXT,
    proposed_action TEXT,
    alternatives TEXT,
    expected_benefit TEXT,
    expected_risk TEXT,
    dependencies TEXT,
    confidence TEXT,
    requires_owner_approval INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'new',
    decision TEXT,
    decided_by TEXT,
    decided_at TEXT,
    approval_id TEXT,
    brain_change_proposal_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decision_log (
    decision_id TEXT PRIMARY KEY,
    entity_type TEXT,
    entity_id TEXT,
    decision TEXT,
    decided_by TEXT,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_insights_status ON insights(status);
CREATE INDEX IF NOT EXISTS idx_insights_fingerprint ON insights(fingerprint);
CREATE INDEX IF NOT EXISTS idx_insights_category ON insights(category);
CREATE INDEX IF NOT EXISTS idx_recommendations_status ON recommendations(status);
CREATE INDEX IF NOT EXISTS idx_recommendations_insight ON recommendations(insight_id);
CREATE INDEX IF NOT EXISTS idx_decision_entity ON decision_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(type);
CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_backups_status ON backups(status);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON message_outbox(status);
CREATE INDEX IF NOT EXISTS idx_outbox_idem ON message_outbox(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_intake_ip ON intake_events(ip);
CREATE INDEX IF NOT EXISTS idx_intake_email ON intake_events(email);

CREATE INDEX IF NOT EXISTS idx_outbox_ready
  ON message_outbox (status, next_attempt_at, created_at);

-- DB-301 (D3): hot-path indexes — previously manual-only in prod; a fresh
-- deploy silently lost them and every inbound message did a full SCAN.
CREATE INDEX IF NOT EXISTS idx_channel_messages_ext ON channel_messages(external_user_id);
CREATE INDEX IF NOT EXISTS idx_channel_messages_dir ON channel_messages(direction);
CREATE INDEX IF NOT EXISTS idx_channel_messages_lead ON channel_messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_leads_whatsapp ON leads(contact_whatsapp);
CREATE INDEX IF NOT EXISTS idx_conversations_last_msg ON conversations(last_message_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_messages_external
  ON channel_messages (channel, external_message_id) WHERE external_message_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_outbox_idem
  ON message_outbox (idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS channel_ai_settings (
    channel TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

-- ── Bridge migration (owner spec §40) — additive only ────────────────────────
-- Ownership: AmanCore owns business state; the bridge owns platform session
-- state (secrets stay in bridge session dirs, NEVER in these tables);
-- the browser agent owns temporary runtime state.

CREATE TABLE IF NOT EXISTS channel_accounts (
    channel TEXT NOT NULL,              -- whatsapp | facebook | instagram
    account_id TEXT NOT NULL,           -- platform account identity
    display_name TEXT,
    transport TEXT,                     -- baileys | private | realtime | browser
    mode TEXT,                          -- bridge | graph | mock
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (channel, account_id)
);

CREATE TABLE IF NOT EXISTS provider_health (
    channel TEXT NOT NULL,
    component TEXT NOT NULL,            -- bridge_process | bridge_session | browser_agent
    state TEXT NOT NULL,                -- UP | DOWN | CONNECTED | AUTH_REQUIRED | ...
    detail TEXT,
    checked_at TEXT,
    PRIMARY KEY (channel, component)
);

CREATE TABLE IF NOT EXISTS browser_tasks (
    task_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,              -- facebook (extensible)
    task_type TEXT NOT NULL,            -- publish_post | publish_story | read_insights | ads_prepare
    payload TEXT NOT NULL DEFAULT '{}', -- JSON task spec (no secrets)
    status TEXT NOT NULL DEFAULT 'QUEUED',
    -- QUEUED CLAIMED STARTING AUTH_CHECK EXECUTING VERIFYING
    -- SUCCEEDED FAILED AUTH_REQUIRED TIMEOUT UNCERTAIN
    attempts INTEGER NOT NULL DEFAULT 0,
    result TEXT,                        -- JSON structured result / evidence
    failure_step TEXT,
    failure_detail TEXT,
    screenshot_ref TEXT,
    created_at TEXT,
    updated_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_browser_tasks_status ON browser_tasks(status);
CREATE INDEX IF NOT EXISTS idx_provider_health_state ON provider_health(state);
