import io

from openpyxl import load_workbook

from src.excel_output import EVENT_HEADERS, RISK_HEADERS, build_workbook
from src.schemas import AgentResponse, EventDraft, RiskDraft


def test_workbook_has_required_sheets_and_headers():
    result = AgentResponse(
        events=[EventDraft(requirement_id="1", event_name="credits_application_view", product="credits", screen="application", action="view", trigger="Пользователь увидел экран.", check="OK")],
        risks=[RiskDraft(number=1, requirement_id="1", type="Неполнота", problem="Не подтверждены dimensions")],
    )
    workbook = load_workbook(io.BytesIO(build_workbook(result)))
    assert workbook.sheetnames == ["Events", "Риски"]
    assert [c.value for c in workbook["Events"][1]] == EVENT_HEADERS
    assert [c.value for c in workbook["Риски"][1]] == RISK_HEADERS

