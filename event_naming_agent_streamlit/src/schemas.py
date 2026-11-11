from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ALLOWED_ACTIONS = ("view", "click", "select", "submit", "success", "error", "start", "complete")
RISK_TYPES = ("Неоднозначность", "Неполнота", "Расхождение с регламентом", "Возможный дубль")


class ClarificationQuestion(BaseModel):
    id: str
    requirement_id: str = ""
    question: str
    reason: str = ""
    options: list[str] = Field(default_factory=list)


class QuestionsResponse(BaseModel):
    status: Literal["ok", "blocked"] = "ok"
    blocked_reason: str = ""
    questions: list[ClarificationQuestion] = Field(default_factory=list)


class EventDraft(BaseModel):
    requirement_id: str
    event_name: str = ""
    product: str = ""
    screen: str = ""
    object: str = ""
    action: str = ""
    trigger: str = ""
    dimensions: str = ""
    check: str = "Требует согласования"
    comment: str = ""


class RiskDraft(BaseModel):
    number: int
    requirement_id: str = ""
    type: str
    problem: str
    agent_suggestion: str = ""
    owner: str = "Системный аналитик"
    analyst_decision: str = ""


class AgentResponse(BaseModel):
    status: Literal["ok", "blocked"] = "ok"
    blocked_reason: str = ""
    events: list[EventDraft] = Field(default_factory=list)
    risks: list[RiskDraft] = Field(default_factory=list)


QUESTIONS_JSON_SCHEMA = QuestionsResponse.model_json_schema()
RESULT_JSON_SCHEMA = AgentResponse.model_json_schema()

