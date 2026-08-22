"""Business Brain structural constants."""

# Top-level sections the validator requires.
REQUIRED_SECTIONS = [
    "company",
    "services",
    "offers",
    "pricing_policy",
    "market_profiles",
    "icp",
    "sales_policy",
    "negotiation_rules",
    "faqs",
    "objections",
    "brand_voice",
    "approved_claims",
    "forbidden_claims",
    "claims_requiring_verification",
    "portfolio",
    "case_studies",
    "policies",
    "agent_policies",
    "decision_policies",
]

SUPPORTED_MARKETS = {"indonesia", "gcc", "malaysia", "singapore"}

OFFER_TIERS = {"entry", "core", "premium", "custom", "recurring"}

SERVICE_TYPES = {"core", "premium", "custom"}
