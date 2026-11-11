from pathlib import Path

from src.parsers import parse_catalog


def test_embedded_synthetic_catalog_is_available():
    catalog_path = Path(__file__).parents[1] / "assets" / "existing_events_catalog.xlsx"
    catalog = parse_catalog(catalog_path)

    assert len(catalog.dataframe) == 27
    assert catalog.dataframe["Event name"].is_unique
    assert set(catalog.dataframe["Action"]) == {
        "view",
        "click",
        "select",
        "submit",
        "success",
        "error",
        "start",
        "complete",
    }
