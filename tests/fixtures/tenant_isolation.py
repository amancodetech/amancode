"""Multi-Tenant & Cross-Project Isolation Fixtures and Invariant Assertions."""

from __future__ import annotations

from typing import Any
from tests.factories.lead import lead_factory
from tests.factories.project import project_factory
from tests.factories.conversation import conversation_factory
from tests.factories.message import message_factory
from tests.factories.requirement import requirement_factory
from tests.factories.decision import decision_factory


def isolated_projects(crm) -> dict[str, dict[str, Any]]:
    """Fixture that generates two completely isolated customer project pipelines.
    
    Lead A: Enterprise Alpha, USD, E-Commerce
    Lead B: Retail Beta, IDR, Booking & Mobile
    """
    # 1. Lead A Setup
    lead_a = lead_factory(crm, name="Enterprise Alpha Corp")
    proj_a = project_factory(crm, service="Website System Starter")
    conv_a = conversation_factory(crm, lead_id=lead_a, channel="whatsapp")
    msg_a = message_factory(crm, lead_id=lead_a, body="We need an e-commerce store with USD currency")
    req_a = requirement_factory(
        crm,
        lead_id=lead_a,
        project_id=proj_a,
        category="core_module",
        subcategory="ecommerce",
        title="Alpha E-Commerce Catalog",
    )
    dec_a = decision_factory(crm, lead_id=lead_a, project_id=proj_a, topic="currency", decision="USD")

    # 2. Lead B Setup
    lead_b = lead_factory(crm, name="Retail Beta Ltd")
    proj_b = project_factory(crm, service="Custom Web Application")
    conv_b = conversation_factory(crm, lead_id=lead_b, channel="telegram")
    msg_b = message_factory(crm, lead_id=lead_b, body="Kami butuh sistem booking dengan mata uang IDR")
    req_b = requirement_factory(
        crm,
        lead_id=lead_b,
        project_id=proj_b,
        category="core_module",
        subcategory="booking",
        title="Beta Booking Engine",
    )
    dec_b = decision_factory(crm, lead_id=lead_b, project_id=proj_b, topic="currency", decision="IDR")

    return {
        "project_a": {
            "lead_id": lead_a,
            "project_id": proj_a,
            "conversation_id": conv_a,
            "message_id": msg_a["external_message_id"],
            "requirement_id": req_a,
            "decision_id": dec_a,
            "currency": "USD",
        },
        "project_b": {
            "lead_id": lead_b,
            "project_id": proj_b,
            "conversation_id": conv_b,
            "message_id": msg_b["external_message_id"],
            "requirement_id": req_b,
            "decision_id": dec_b,
            "currency": "IDR",
        },
    }


def assert_no_cross_project_requirements(crm, lead_a: str, lead_b: str) -> None:
    """Verify that requirement IDs for lead A and lead B are strictly disjoint."""
    reqs_a = {r["requirement_id"] for r in crm.list_requirements_for_lead(lead_a)}
    reqs_b = {r["requirement_id"] for r in crm.list_requirements_for_lead(lead_b)}
    intersection = reqs_a.intersection(reqs_b)
    if intersection:
        raise AssertionError(f"ISOLATION LEAK: Cross-project requirement IDs detected: {intersection}")


def assert_no_cross_project_decisions(crm, lead_a: str, lead_b: str) -> None:
    """Verify that decision IDs for lead A and lead B are strictly disjoint."""
    decs_a = {d["decision_id"] for d in crm.list_decisions_for_lead(lead_a)}
    decs_b = {d["decision_id"] for d in crm.list_decisions_for_lead(lead_b)}
    intersection = decs_a.intersection(decs_b)
    if intersection:
        raise AssertionError(f"ISOLATION LEAK: Cross-project decision IDs detected: {intersection}")


def assert_no_cross_project_questions(crm, lead_a: str, lead_b: str) -> None:
    """Verify that open question IDs for lead A and lead B are strictly disjoint."""
    qs_a = {q["question_id"] for q in crm.list_open_questions_for_lead(lead_a)}
    qs_b = {q["question_id"] for q in crm.list_open_questions_for_lead(lead_b)}
    intersection = qs_a.intersection(qs_b)
    if intersection:
        raise AssertionError(f"ISOLATION LEAK: Cross-project question IDs detected: {intersection}")


def assert_no_cross_project_conflicts(crm, lead_a: str, lead_b: str) -> None:
    """Verify that requirement conflicts for lead A do not reference lead B requirements."""
    confs_a = crm.list_conflicts_for_lead(lead_a)
    reqs_b = {r["requirement_id"] for r in crm.list_requirements_for_lead(lead_b)}
    for conf in confs_a:
        if conf["requirement_a_id"] in reqs_b or conf["requirement_b_id"] in reqs_b:
            raise AssertionError(f"ISOLATION LEAK: Conflict {conf['conflict_id']} references lead B requirements!")


def assert_no_cross_project_scopes(crm, lead_a: str, lead_b: str) -> None:
    """Verify that project scopes and version items for lead A and lead B are strictly disjoint."""
    scopes_a = crm.db.execute("SELECT scope_id FROM project_scopes WHERE lead_id = ?", (lead_a,)).fetchall()
    scopes_b = crm.db.execute("SELECT scope_id FROM project_scopes WHERE lead_id = ?", (lead_b,)).fetchall()
    ids_a = {r["scope_id"] for r in scopes_a}
    ids_b = {r["scope_id"] for r in scopes_b}
    intersection = ids_a.intersection(ids_b)
    if intersection:
        raise AssertionError(f"ISOLATION LEAK: Cross-project scope IDs detected: {intersection}")


def assert_project_isolated(crm, lead_a: str, lead_b: str) -> None:
    """Run all cross-project isolation assertion checks."""
    assert_no_cross_project_requirements(crm, lead_a, lead_b)
    assert_no_cross_project_decisions(crm, lead_a, lead_b)
    assert_no_cross_project_questions(crm, lead_a, lead_b)
    assert_no_cross_project_conflicts(crm, lead_a, lead_b)
    assert_no_cross_project_scopes(crm, lead_a, lead_b)
