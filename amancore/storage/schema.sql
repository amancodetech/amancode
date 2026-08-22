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
    facts TEXT,
    preferences TEXT,
    requirements TEXT,
    unknowns TEXT,
    decisions TEXT,
    open_questions TEXT,
    summary TEXT,
    current_state TEXT,
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
    next_attempt_at TEXT,
    idempotency_key TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
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
