from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from docx import Document
from pypdf import PdfReader


@dataclass
class ParsedDocument:
    text: str
    images: list[tuple[str, bytes, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CatalogData:
    dataframe: pd.DataFrame
    source_name: str
    workbook_bytes: bytes | None = None
    warnings: list[str] = field(default_factory=list)


def _read_bytes(uploaded_file) -> bytes:
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    if isinstance(uploaded_file, bytes):
        return uploaded_file
    return Path(uploaded_file).read_bytes()


def _name(uploaded_file) -> str:
    return getattr(uploaded_file, "name", str(uploaded_file))


def parse_text_document(uploaded_file) -> ParsedDocument:
    name = _name(uploaded_file)
    suffix = Path(name).suffix.lower()
    data = _read_bytes(uploaded_file)
    if suffix == ".txt":
        for encoding in ("utf-8", "cp1251"):
            try:
                return ParsedDocument(text=data.decode(encoding))
            except UnicodeDecodeError:
                continue
        raise ValueError("Не удалось определить кодировку TXT-файла")
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        text = "\n\n".join(f"[Страница {i}]\n{page}" for i, page in enumerate(pages, 1) if page)
        warnings = [] if text.strip() else ["В PDF не найден текстовый слой; возможно, требуется OCR."]
        return ParsedDocument(text=text, warnings=warnings)
    if suffix == ".docx":
        document = Document(io.BytesIO(data))
        blocks: list[str] = []
        for paragraph in document.paragraphs:
            value = paragraph.text.strip()
            if value:
                blocks.append(value)
        for table_index, table in enumerate(document.tables, 1):
            blocks.append(f"[Таблица {table_index}]")
            for row in table.rows:
                blocks.append(" | ".join(cell.text.strip() for cell in row.cells))
        images: list[tuple[str, bytes, str]] = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.namelist():
                    if member.startswith("word/media/"):
                        raw = archive.read(member)
                        ext = Path(member).suffix.lower().lstrip(".") or "png"
                        mime = "image/jpeg" if ext in {"jpg", "jpeg"} else f"image/{ext}"
                        images.append((Path(member).name, raw, mime))
        except zipfile.BadZipFile:
            pass
        warnings = []
        if images:
            warnings.append(f"Из DOCX извлечено изображений: {len(images)}. Их связь с пунктами БТ проверяется моделью и аналитиком.")
        return ParsedDocument(text="\n".join(blocks), images=images, warnings=warnings)
    raise ValueError(f"Неподдерживаемый формат: {suffix or 'без расширения'}")


def parse_catalog(uploaded_file) -> CatalogData:
    name = _name(uploaded_file)
    suffix = Path(name).suffix.lower()
    data = _read_bytes(uploaded_file)
    if suffix == ".csv":
        decoded = None
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                decoded = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            raise ValueError("Не удалось определить кодировку CSV")
        dialect = csv.Sniffer().sniff(decoded[:4096], delimiters=",;\t")
        frame = pd.read_csv(io.StringIO(decoded), sep=dialect.delimiter)
        return CatalogData(frame, name)
    if suffix == ".xlsx":
        excel = pd.ExcelFile(io.BytesIO(data))
        sheet = "Events" if "Events" in excel.sheet_names else excel.sheet_names[0]
        frame = pd.read_excel(io.BytesIO(data), sheet_name=sheet)
        warnings = []
        if "Events" not in excel.sheet_names:
            warnings.append(f"Лист Events не найден; для проверки дублей используется лист «{sheet}».")
        return CatalogData(frame, name, workbook_bytes=data, warnings=warnings)
    raise ValueError("Каталог должен быть в XLSX или CSV")


def catalog_as_text(catalog: CatalogData, max_rows: int = 500) -> str:
    frame = catalog.dataframe.fillna("").head(max_rows)
    return frame.to_csv(index=False)


def normalize_feature_filename(feature_name: str) -> str:
    value = re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]+", "_", feature_name.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "feature"

