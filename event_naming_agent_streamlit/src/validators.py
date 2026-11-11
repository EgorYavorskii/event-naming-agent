from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .schemas import ALLOWED_ACTIONS, AgentResponse, RiskDraft


EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
SNAKE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
DIMENSION_PATTERN = re.compile(r"^dimension_([1-9]|1[0-9]|20)=([a-z][a-z0-9_]*)$")
SENSITIVE_TERMS = {
    "client_pin": "ПИН клиента",
    "pin клиента": "ПИН клиента",
    "пин клиента": "ПИН клиента",
    "номер карты": "номер карты",
    "card_number": "номер карты",
    "номер счета": "номер счёта",
    "номер счёта": "номер счёта",
    "телефон": "телефон",
    "phone": "телефон",
    "e-mail": "e-mail",
    "email": "e-mail",
    "фио": "ФИО",
    "full_name": "ФИО",
}


@dataclass
class ValidationReport:
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocking_errors


def find_sensitive_references(text: str) -> list[str]:
    lowered = text.lower()
    return sorted({label for term, label in SENSITIVE_TERMS.items() if term in lowered})


def validate_inputs(bt_text: str, regulation_text: str, catalog: pd.DataFrame) -> ValidationReport:
    report = ValidationReport()
    if not bt_text.strip():
        report.blocking_errors.append("В БТ не найден читаемый текст с требованиями к событиям.")
    if not regulation_text.strip():
        report.blocking_errors.append("В регламенте не найден читаемый текст.")
    if catalog.empty:
        report.blocking_errors.append("Каталог событий пуст.")
    if len(bt_text.strip()) < 40:
        report.warnings.append("Текст БТ очень короткий — проверьте, что все пункты распознаны.")
    sensitive = find_sensitive_references(bt_text)
    if sensitive:
        report.warnings.append("В БТ упомянуты потенциально чувствительные поля: " + ", ".join(sensitive) + ". Они не будут добавлены в dimensions.")
    return report


def _existing_event_names(catalog: pd.DataFrame) -> set[str]:
    candidates = [c for c in catalog.columns if str(c).strip().lower() in {"event name", "event_name", "событие", "имя события"}]
    if not candidates:
        return set()
    return {str(v).strip().lower() for v in catalog[candidates[0]].dropna() if str(v).strip()}


def validate_agent_result(result: AgentResponse, catalog: pd.DataFrame) -> AgentResponse:
    existing = _existing_event_names(catalog)
    seen: set[str] = set()
    next_risk = max((risk.number for risk in result.risks), default=0) + 1

    def add_risk(req_id: str, kind: str, problem: str, suggestion: str = "") -> None:
        nonlocal next_risk
        if any(r.requirement_id == req_id and r.problem == problem for r in result.risks):
            return
        result.risks.append(RiskDraft(number=next_risk, requirement_id=req_id, type=kind, problem=problem, agent_suggestion=suggestion))
        next_risk += 1

    for event in result.events:
        problems: list[str] = []
        expected = "_".join(part for part in (event.product, event.screen, event.object, event.action) if part)
        if not EVENT_PATTERN.fullmatch(event.event_name):
            problems.append("Event name нарушает формат a-z, 0-9, snake_case или длину 100 символов")
        if event.event_name != expected:
            problems.append("Event name не совпадает с Product / Screen / Object / Action")
        if event.action not in ALLOWED_ACTIONS:
            problems.append("Action не входит в разрешённый справочник")
        if not event.product or not SNAKE_PATTERN.fullmatch(event.product):
            problems.append("Product отсутствует или не подтверждён в snake_case")
        if not event.screen and not event.object:
            problems.append("Screen и Object одновременно пустые")
        for value, label in ((event.screen, "Screen"), (event.object, "Object")):
            if value and not SNAKE_PATTERN.fullmatch(value):
                problems.append(f"{label} должен быть в snake_case")
        dimension_items = [x.strip() for x in event.dimensions.split(";") if x.strip()]
        dimension_numbers: list[int] = []
        for item in dimension_items:
            match = DIMENSION_PATTERN.fullmatch(item)
            if not match:
                problems.append(f"Некорректная запись dimension: {item}")
            else:
                dimension_numbers.append(int(match.group(1)))
        if dimension_numbers != sorted(set(dimension_numbers)):
            problems.append("Dimensions должны идти по возрастанию и без повторов")
        sensitive = find_sensitive_references(event.event_name + " " + event.dimensions)
        if sensitive:
            problems.append("Обнаружены запрещённые чувствительные поля: " + ", ".join(sensitive))
        if event.event_name in existing or event.event_name in seen:
            problems.append("Возможный дубль Event name")
            add_risk(event.requirement_id, "Возможный дубль", f"Событие {event.event_name} уже встречается в каталоге или текущем результате.")
        seen.add(event.event_name)
        if not event.trigger.strip():
            problems.append("Не указан конкретный Trigger")
        if problems:
            event.check = "Требует согласования: " + "; ".join(dict.fromkeys(problems))
            add_risk(event.requirement_id, "Расхождение с регламентом", "; ".join(dict.fromkeys(problems)), event.comment)
        elif event.check.strip().upper() == "OK":
            event.check = "OK"
        else:
            event.check = "Требует согласования"
    return result

