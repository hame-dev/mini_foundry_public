import uuid

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from app.auth.models import User
import app.ai.router as ai


@pytest.fixture(autouse=True)
def _patch_side_effects(monkeypatch):
    monkeypatch.setattr(ai, "log_event", AsyncMock())


def _admin():
    return User(id=uuid.uuid4(), email="a@example.com")


def _session():
    s = AsyncMock()
    s.flush = AsyncMock()
    s.commit = AsyncMock()
    return s


# --- runs scoping ----------------------------------------------------------

@pytest.mark.asyncio
async def test_get_run_forbidden_for_non_owner(monkeypatch):
    monkeypatch.setattr(ai, "get_user_roles", AsyncMock(return_value=[]))
    run = MagicMock()
    run.user_id = uuid.uuid4()  # someone else
    session = _session()
    session.get.return_value = run
    with pytest.raises(HTTPException) as exc:
        await ai.get_ai_run(uuid.uuid4(), session, User(id=uuid.uuid4(), email="v@example.com"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_run_404(monkeypatch):
    monkeypatch.setattr(ai, "get_user_roles", AsyncMock(return_value=["admin"]))
    session = _session()
    session.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        await ai.get_ai_run(uuid.uuid4(), session, _admin())
    assert exc.value.status_code == 404


# --- prompt templates ------------------------------------------------------

@pytest.mark.asyncio
async def test_create_prompt_requires_fields():
    session = _session()
    with pytest.raises(HTTPException) as exc:
        await ai.create_prompt(ai.PromptIn(name=" ", template=""), session, _admin())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_prompt_bumps_version(monkeypatch):
    session = _session()
    # max(version) for this name returns 2 -> new version 3
    result = MagicMock()
    result.scalar.return_value = 2
    session.execute.return_value = result
    out = await ai.create_prompt(ai.PromptIn(name="greeter", template="hi {{x}}"), session, _admin())
    assert out.version == 3
    assert out.name == "greeter"


# --- evaluations -----------------------------------------------------------

@pytest.mark.asyncio
async def test_create_evaluation_requires_name():
    session = _session()
    with pytest.raises(HTTPException) as exc:
        await ai.create_evaluation(ai.EvaluationIn(name="  "), session, _admin())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_evaluation_persists():
    session = _session()
    out = await ai.create_evaluation(
        ai.EvaluationIn(name="quality", provider="ollama", model="llama3", score=0.9), session, _admin()
    )
    assert out.name == "quality"
    assert out.score == 0.9


# --- output models never leak internals ------------------------------------

def test_run_out_has_no_cost_estimate():
    # token_estimate surfaced; cost_estimate intentionally not exposed.
    assert "cost_estimate" not in ai.AiRunOut.model_fields


@pytest.mark.asyncio
async def test_prompt_preview_redacts_sensitive_values():
    session = _session()
    out = await ai.preview_prompt(
        ai.PromptPreviewIn(template="Contact {{user.email}}", context={"user": {"email": "analyst@example.com"}}),
        session,
        _admin(),
    )
    assert "[REDACTED:email]" in out.redacted_prompt
    assert out.redactions[0].type == "email"


@pytest.mark.asyncio
async def test_run_evaluation_records_results():
    ev = ai.AiEvaluation(
        id=uuid.uuid4(),
        name="guard",
        cases={"cases": [{"template": "Hello {{name}}", "context": {"name": "World"}, "expected_contains": "World"}]},
        status="draft",
    )
    session = _session()
    session.get.return_value = ev
    out = await ai.run_evaluation(ev.id, session, _admin())
    assert out.status == "completed"
    assert out.score == 1.0
    assert ev.results["case_count"] == 1
