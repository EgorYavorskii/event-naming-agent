from __future__ import annotations

import io
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .schemas import AgentResponse


EVENT_HEADERS = ["№", "Event name", "Product", "Screen", "Object", "Action", "Trigger", "Dimensions", "Проверка"]
RISK_HEADERS = ["№", "Строка БТ", "Тип", "Суть проблемы", "Вариант агента", "У кого уточнить", "Решение аналитика"]
YELLOW_FILL = PatternFill("solid", fgColor="FFF2CC")
RED_FILL = PatternFill("solid", fgColor="F4CCCC")
HEADER_FILL = PatternFill("solid", fgColor="E9EAEC")


def _ensure_sheet(workbook: Workbook, name: str, headers: list[str]):
    if name in workbook.sheetnames:
        sheet = workbook[name]
        existing = [sheet.cell(1, i).value for i in range(1, sheet.max_column + 1)]
        if not any(existing):
            for i, header in enumerate(headers, 1):
                sheet.cell(1, i, header)
        elif existing[: len(headers)] != headers:
            raise ValueError(f"Структура листа «{name}» не совпадает с ожидаемой: {headers}")
    else:
        sheet = workbook.create_sheet(name)
        for i, header in enumerate(headers, 1):
            sheet.cell(1, i, header)
    return sheet


def _clear_data(sheet) -> None:
    if sheet.max_row > 1:
        sheet.delete_rows(2, sheet.max_row - 1)


def _format_sheet(sheet) -> None:
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="18191B")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    widths = {1: 7, 2: 42, 3: 18, 4: 20, 5: 22, 6: 14, 7: 55, 8: 48, 9: 45}
    for index in range(1, sheet.max_column + 1):
        sheet.column_dimensions[get_column_letter(index)].width = widths.get(index, 28)
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def build_workbook(result: AgentResponse, template_bytes: bytes | None = None) -> bytes:
    if template_bytes:
        workbook = load_workbook(io.BytesIO(template_bytes))
    else:
        workbook = Workbook()
        workbook.active.title = "Events"
    events_sheet = _ensure_sheet(workbook, "Events", EVENT_HEADERS)
    risks_sheet = _ensure_sheet(workbook, "Риски", RISK_HEADERS)
    for sheet_name in list(workbook.sheetnames):
        if sheet_name not in {"Events", "Риски"}:
            del workbook[sheet_name]
    _clear_data(events_sheet)
    _clear_data(risks_sheet)

    for index, event in enumerate(result.events, 1):
        values = [index, event.event_name, event.product, event.screen, event.object, event.action, event.trigger, event.dimensions, event.check]
        events_sheet.append(values)
        if event.check != "OK":
            for cell in events_sheet[events_sheet.max_row]:
                cell.fill = YELLOW_FILL

    for risk in result.risks:
        risks_sheet.append([risk.number, risk.requirement_id, risk.type, risk.problem, risk.agent_suggestion, risk.owner, risk.analyst_decision])
        for cell in risks_sheet[risks_sheet.max_row]:
            cell.fill = RED_FILL if risk.type == "Расхождение с регламентом" else YELLOW_FILL

    for sheet in (events_sheet, risks_sheet):
        _format_sheet(sheet)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()

