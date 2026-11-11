import pandas as pd

from src.schemas import AgentResponse, EventDraft
from src.validators import find_sensitive_references, validate_agent_result


def test_sensitive_pin_is_detected():
    assert "ПИН клиента" in find_sensitive_references("Передавать client_pin")


def test_valid_event_stays_ok():
    result = AgentResponse(events=[EventDraft(requirement_id="1", event_name="credits_application_view", product="credits", screen="application", action="view", trigger="Пользователь увидел экран после загрузки данных.", dimensions="", check="OK")])
    checked = validate_agent_result(result, pd.DataFrame({"Event name": []}))
    assert checked.events[0].check == "OK"


def test_duplicate_becomes_risk():
    result = AgentResponse(events=[EventDraft(requirement_id="1", event_name="credits_application_view", product="credits", screen="application", action="view", trigger="Экран показан.", check="OK")])
    checked = validate_agent_result(result, pd.DataFrame({"Event name": ["credits_application_view"]}))
    assert checked.events[0].check.startswith("Требует согласования")
    assert any(r.type == "Возможный дубль" for r in checked.risks)


def test_sensitive_dimension_is_rejected():
    result = AgentResponse(events=[EventDraft(requirement_id="1", event_name="credits_application_view", product="credits", screen="application", action="view", trigger="Экран показан.", dimensions="dimension_1=client_pin", check="OK")])
    checked = validate_agent_result(result, pd.DataFrame({"Event name": []}))
    assert checked.events[0].check.startswith("Требует согласования")

