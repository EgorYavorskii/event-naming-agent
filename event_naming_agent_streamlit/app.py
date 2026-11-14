from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from src.excel_output import build_workbook
from src.openrouter_client import OpenRouterError, call_openrouter
from src.parsers import catalog_as_text, normalize_feature_filename, parse_catalog, parse_text_document
from src.prompts import SYSTEM_PROMPT, build_generation_prompt, build_questions_prompt
from src.schemas import AgentResponse, QUESTIONS_JSON_SCHEMA, RESULT_JSON_SCHEMA, QuestionsResponse
from src.validators import validate_agent_result, validate_inputs


st.set_page_config(page_title="Агент нейминга событий", page_icon="🧭", layout="wide")

ASSETS_DIR = Path(__file__).parent / "assets"
DEFAULT_REGULATION_TEXT = (ASSETS_DIR / "regulation.md").read_text(encoding="utf-8")
TEMPLATE_BYTES = (ASSETS_DIR / "tracking_plan_template.xlsx").read_bytes()
EMBEDDED_CATALOG = parse_catalog(ASSETS_DIR / "existing_events_catalog.xlsx")


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, os.getenv(name, default)))
    except Exception:
        return os.getenv(name, default)


def reset_analysis() -> None:
    for key in ("parsed", "questions", "answers", "result", "xlsx"):
        st.session_state.pop(key, None)


def apply_regulation() -> None:
    edited_text = st.session_state.get("regulation_editor", "").strip()
    if not edited_text:
        st.session_state.regulation_notice = ("error", "Регламент не может быть пустым.")
        return
    st.session_state.regulation_text = edited_text
    st.session_state.regulation_notice = ("success", "Изменения регламента применены к текущему запуску.")
    reset_analysis()


def restore_regulation() -> None:
    st.session_state.regulation_editor = DEFAULT_REGULATION_TEXT
    st.session_state.regulation_text = DEFAULT_REGULATION_TEXT
    st.session_state.regulation_notice = ("success", "Восстановлена встроенная версия регламента.")
    reset_analysis()


if "regulation_text" not in st.session_state:
    st.session_state.regulation_text = DEFAULT_REGULATION_TEXT
if "regulation_editor" not in st.session_state:
    st.session_state.regulation_editor = st.session_state.regulation_text


st.title("Агент нейминга продуктовых событий")
st.caption("Черновая разметка по БТ и регламенту · результат требует проверки системного аналитика")
st.warning("Используйте только синтетические или обезличенные учебные данные. Приложение ничего не отправляет в Jira и не согласовывает события автоматически.")
image_description = ""

with st.sidebar:
    st.subheader("О прототипе")
    st.markdown("**Результат:** XLSX с листами `Events` и `Риски`.\n\n**Модель:** OpenRouter.\n\n**Ограничение:** бесплатная квота может закончиться.")
    model = secret("OPENROUTER_MODEL", "openrouter/free")
    st.code(model, language=None)
    if st.button("Начать заново", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.subheader("1. Регламент разметки")
with st.expander("Открыть и отредактировать регламент"):
    st.caption("Изменения действуют только в текущей пользовательской сессии и будут переданы модели при следующем анализе.")
    with st.form("regulation_form"):
        st.text_area(
            "Текст регламента",
            key="regulation_editor",
            height=420,
            help="Отредактируйте правила и нажмите «Применить изменения». После изменения нужно заново проверить БТ.",
        )
        apply_column, restore_column = st.columns(2)
        with apply_column:
            st.form_submit_button("Применить изменения", type="primary", use_container_width=True, on_click=apply_regulation)
        with restore_column:
            st.form_submit_button("Вернуть встроенную версию", use_container_width=True, on_click=restore_regulation)

if "regulation_notice" in st.session_state:
    notice_type, notice_text = st.session_state.pop("regulation_notice")
    if notice_type == "error":
        st.error(notice_text)
    else:
        st.success(notice_text)

st.subheader("2. Данные запуска")
left, right = st.columns(2)
with left:
    feature = st.text_input("Название фичи *", placeholder="Оформление кредита")
with right:
    product = st.text_input("Код Product", placeholder="Только утверждённый код")

bt_file = st.file_uploader("Бизнес-требования *", type=["pdf", "docx"], on_change=reset_analysis)
st.caption("Регламент предзаполнен и доступен для редактирования выше. Синтетический каталог и шаблон итогового XLSX встроены в приложение.")

if st.button("Проверить файлы", type="primary", use_container_width=True):
    if bt_file is None:
        st.error("Загрузите обязательный файл: БТ")
    elif not feature.strip():
        st.error("Укажите название фичи.")
    else:
        try:
            bt = parse_text_document(bt_file)
            active_regulation = st.session_state.regulation_text
            report = validate_inputs(bt.text, active_regulation, EMBEDDED_CATALOG.dataframe)
            st.session_state.parsed = {"bt": bt, "regulation_text": active_regulation, "catalog": EMBEDDED_CATALOG, "report": report}
            st.session_state.pop("questions", None)
            st.session_state.pop("result", None)
        except Exception as exc:
            st.error(f"Не удалось прочитать файлы: {exc}")

if "parsed" in st.session_state:
    parsed = st.session_state.parsed
    report = parsed["report"]
    if report.blocking_errors:
        for error in report.blocking_errors:
            st.error(error)
    else:
        st.success("БТ читается, встроенные материалы подключены. Можно переходить к анализу требований.")
    for warning in parsed["bt"].warnings + parsed["catalog"].warnings + report.warnings:
        st.warning(warning)
    with st.expander("Что распознано"):
        st.write({"Символов в БТ": len(parsed["bt"].text), "Символов в активном регламенте": len(parsed["regulation_text"]), "Строк во встроенном каталоге": len(parsed["catalog"].dataframe), "Изображений в БТ": len(parsed["bt"].images)})
    if parsed["bt"].images:
        image_description = st.text_area(
            "Описание информации со скриншотов",
            help="Если выбранная бесплатная модель не поддерживает изображения, кратко опишите экран и выделенные элементы текстом.",
            key="image_description",
        )

    st.subheader("3. Уточняющие вопросы")
    api_key = secret("OPENROUTER_API_KEY")
    if st.button("Проанализировать требования", disabled=not report.ok, use_container_width=True):
        if not api_key:
            st.error("Не настроен OPENROUTER_API_KEY. Добавьте ключ в Secrets приложения.")
        else:
            bt_for_model = parsed["bt"].text + ("\n\nОПИСАНИЕ СКРИНШОТОВ ОТ АНАЛИТИКА:\n" + image_description if image_description.strip() else "")
            prompt = build_questions_prompt(feature, product, bt_for_model, parsed["regulation_text"], catalog_as_text(parsed["catalog"]))
            try:
                with st.spinner("Ищу неоднозначности и неполные требования..."):
                    raw = call_openrouter(api_key=api_key, model=model, system_prompt=SYSTEM_PROMPT, user_prompt=prompt, schema=QUESTIONS_JSON_SCHEMA)
                    st.session_state.questions = QuestionsResponse.model_validate(raw)
            except (OpenRouterError, ValidationError) as exc:
                st.error(str(exc))

if "questions" in st.session_state:
    questions = st.session_state.questions
    if questions.status == "blocked":
        st.warning(questions.blocked_reason or "В требованиях есть критическая неопределённость. Можно уточнить её ниже или сразу вынести в риски.")
    if not questions.questions:
        st.info("Обязательных уточнений не найдено.")
    else:
        st.info("Можно ответить на вопросы ниже или сразу сформировать черновик. Пропущенные ответы попадут в раздел «Риски».")
        with st.form("answers_form"):
            answers = {}
            for question in questions.questions[:3]:
                st.markdown(f"**{question.requirement_id or 'Общий вопрос'} — {question.question}**")
                if question.reason:
                    st.caption(question.reason)
                if question.options:
                    st.caption("Возможные варианты: " + " · ".join(question.options))
                answers[question.id] = st.text_input(
                    "Ваш ответ",
                    placeholder="Можно оставить пустым — вопрос попадёт в риски",
                    key=f"answer_{question.id}",
                )
            if st.form_submit_button("Сохранить ответы и продолжить", use_container_width=True):
                st.session_state.answers = {
                    key: (value.strip() or "Не знаю — вынести в риски")
                    for key, value in answers.items()
                }
                st.success("Ответы сохранены. Теперь можно сформировать черновик.")

if "parsed" in st.session_state and st.session_state.parsed["report"].ok:
    st.subheader("4. Черновик разметки")
    if st.button("Сформировать черновик", type="primary", use_container_width=True):
        if not secret("OPENROUTER_API_KEY"):
            st.error("Не настроен OPENROUTER_API_KEY.")
        else:
            parsed = st.session_state.parsed
            answers_text = json.dumps(st.session_state.get("answers", {}), ensure_ascii=False, indent=2)
            image_description = st.session_state.get("image_description", "")
            bt_for_model = parsed["bt"].text + ("\n\nОПИСАНИЕ СКРИНШОТОВ ОТ АНАЛИТИКА:\n" + image_description if image_description.strip() else "")
            prompt = build_generation_prompt(feature, product, bt_for_model, parsed["regulation_text"], catalog_as_text(parsed["catalog"]), answers_text)
            try:
                with st.spinner("Формирую черновую разметку и проверяю её..."):
                    raw = call_openrouter(api_key=secret("OPENROUTER_API_KEY"), model=secret("OPENROUTER_MODEL", "openrouter/free"), system_prompt=SYSTEM_PROMPT, user_prompt=prompt, schema=RESULT_JSON_SCHEMA)
                    result = AgentResponse.model_validate(raw)
                    if result.status == "blocked":
                        st.error(result.blocked_reason)
                    else:
                        result = validate_agent_result(result, parsed["catalog"].dataframe)
                        xlsx = build_workbook(result, TEMPLATE_BYTES)
                        st.session_state.result = result
                        st.session_state.xlsx = xlsx
            except (OpenRouterError, ValidationError) as exc:
                st.error(str(exc))

if "result" in st.session_state:
    result = st.session_state.result
    st.subheader("Предпросмотр")
    event_rows = [{"№": i, "Event name": e.event_name, "Product": e.product, "Screen": e.screen, "Object": e.object, "Action": e.action, "Trigger": e.trigger, "Dimensions": e.dimensions, "Проверка": e.check} for i, e in enumerate(result.events, 1)]
    risk_rows = [{"№": r.number, "Строка БТ": r.requirement_id, "Тип": r.type, "Суть проблемы": r.problem, "Вариант агента": r.agent_suggestion, "У кого уточнить": r.owner, "Решение аналитика": r.analyst_decision} for r in result.risks]
    first, second = st.tabs([f"Events · {len(event_rows)}", f"Риски · {len(risk_rows)}"])
    with first:
        st.dataframe(pd.DataFrame(event_rows), use_container_width=True, hide_index=True)
    with second:
        st.dataframe(pd.DataFrame(risk_rows), use_container_width=True, hide_index=True)
    filename = f"разметка_{normalize_feature_filename(feature)}_черновик.xlsx"
    st.download_button("Скачать XLSX", data=st.session_state.xlsx, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
    st.caption("Файл является черновиком. OK означает только прохождение автоматических проверок, а не согласование человеком.")

