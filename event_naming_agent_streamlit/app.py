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


def secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, os.getenv(name, default)))
    except Exception:
        return os.getenv(name, default)


def reset_after_files() -> None:
    for key in ("parsed", "questions", "answers", "result", "xlsx"):
        st.session_state.pop(key, None)


st.title("Агент нейминга продуктовых событий")
st.caption("Черновая разметка по БТ и регламенту · результат требует проверки системного аналитика")
st.warning("Используйте только синтетические или обезличенные учебные данные. Приложение ничего не отправляет в Jira и не согласовывает события автоматически.")
image_description = ""
ASSETS_DIR = Path(__file__).parent / "assets"
REGULATION_TEXT = (ASSETS_DIR / "regulation.md").read_text(encoding="utf-8")
TEMPLATE_BYTES = (ASSETS_DIR / "tracking_plan_template.xlsx").read_bytes()

with st.sidebar:
    st.subheader("О прототипе")
    st.markdown("**Результат:** XLSX с листами `Events` и `Риски`.\n\n**Модель:** OpenRouter.\n\n**Ограничение:** бесплатная квота может закончиться.")
    model = secret("OPENROUTER_MODEL", "openrouter/free")
    st.code(model, language=None)
    if st.button("Начать заново", use_container_width=True):
        st.session_state.clear()
        st.rerun()

st.subheader("1. Данные запуска")
left, right = st.columns(2)
with left:
    feature = st.text_input("Название фичи *", placeholder="Оформление кредита")
with right:
    product = st.text_input("Код Product", placeholder="Только утверждённый код")

bt_file = st.file_uploader("Бизнес-требования *", type=["pdf", "docx"], on_change=reset_after_files)
catalog_file = st.file_uploader("Актуальный каталог существующих событий *", type=["xlsx", "csv"], on_change=reset_after_files)
st.caption("Регламент нейминга и шаблон итогового XLSX уже встроены в приложение.")

if st.button("Проверить файлы", type="primary", use_container_width=True):
    missing = [label for value, label in ((bt_file, "БТ"), (catalog_file, "каталог событий")) if value is None]
    if missing:
        st.error("Загрузите обязательные файлы: " + ", ".join(missing))
    elif not feature.strip():
        st.error("Укажите название фичи.")
    else:
        try:
            bt = parse_text_document(bt_file)
            catalog = parse_catalog(catalog_file)
            report = validate_inputs(bt.text, REGULATION_TEXT, catalog.dataframe)
            st.session_state.parsed = {"bt": bt, "regulation_text": REGULATION_TEXT, "catalog": catalog, "report": report}
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
        st.success("Обязательные файлы читаются. Можно переходить к анализу требований.")
    for warning in parsed["bt"].warnings + parsed["catalog"].warnings + report.warnings:
        st.warning(warning)
    with st.expander("Что распознано"):
        st.write({"Символов в БТ": len(parsed["bt"].text), "Символов во встроенном регламенте": len(parsed["regulation_text"]), "Строк в каталоге": len(parsed["catalog"].dataframe), "Изображений в БТ": len(parsed["bt"].images)})
    if parsed["bt"].images:
        image_description = st.text_area(
            "Описание информации со скриншотов",
            help="Если выбранная бесплатная модель не поддерживает изображения, кратко опишите экран и выделенные элементы текстом.",
            key="image_description",
        )

    st.subheader("2. Уточняющие вопросы")
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
        st.error(questions.blocked_reason)
    elif not questions.questions:
        st.info("Обязательных уточнений не найдено.")
    else:
        st.info("Ответьте на вопросы. Если решения нет, оставьте неопределённость в рисках.")
        with st.form("answers_form"):
            answers = {}
            for question in questions.questions:
                st.markdown(f"**{question.requirement_id or 'Общий вопрос'} — {question.question}**")
                if question.reason:
                    st.caption(question.reason)
                options = question.options + (["Не знаю — вынести в риски"] if "Не знаю — вынести в риски" not in question.options else [])
                selected = st.selectbox("Ответ", options=["Выберите ответ"] + options + ["Другой ответ"], key=f"choice_{question.id}", label_visibility="collapsed")
                custom = st.text_input("Свой ответ", key=f"custom_{question.id}") if selected == "Другой ответ" else ""
                answers[question.id] = custom or selected
            if st.form_submit_button("Сохранить ответы", use_container_width=True):
                st.session_state.answers = {key: ("Не знаю — вынести в риски" if value == "Выберите ответ" else value) for key, value in answers.items()}
                st.success("Ответы сохранены.")

if "parsed" in st.session_state and st.session_state.parsed["report"].ok:
    st.subheader("3. Черновик разметки")
    if st.button("Сформировать черновик", type="primary", use_container_width=True):
        if not secret("OPENROUTER_API_KEY"):
            st.error("Не настроен OPENROUTER_API_KEY.")
        elif "questions" in st.session_state and st.session_state.questions.questions and "answers" not in st.session_state:
            st.error("Сначала сохраните ответы на уточняющие вопросы.")
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

