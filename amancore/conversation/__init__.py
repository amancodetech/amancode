"""Conversation Operating Model — P0-1 kernel.

Single decision source for every turn:

    Context -> Intent/Context detection -> ConversationPolicy
            -> ModeManager -> ResponsePlanner (WHAT)
            -> LLM wording (HOW)

This package deliberately contains no pricing math, no send logic and no
compliance rules: those stay in their authoritative owners (PricingEngine,
approvals, guard services). Strategy lives in ConversationPolicy (config),
business knowledge lives exclusively in the Business Brain.
"""

from .planner import ConversationModel, ResponsePlanner  # noqa: F401
