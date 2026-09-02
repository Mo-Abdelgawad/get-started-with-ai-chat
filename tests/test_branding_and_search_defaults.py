import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_qarar_defaults_are_applied():
    parameters = json.loads((ROOT / "infra" / "main.parameters.json").read_text())

    assert parameters["parameters"]["useSearchService"]["value"] == "${USE_AZURE_AI_SEARCH_SERVICE=true}"
    assert parameters["parameters"]["aiSearchIndexName"]["value"] == "${AZURE_AI_SEARCH_INDEX_NAME=qarar-citations-v1}"

    html = (ROOT / "src" / "api" / "templates" / "index.html").read_text()
    assert "QARAR AI" in html


def test_existing_ai_project_preserves_search_endpoint_when_service_name_is_known():
    bicep = (ROOT / "infra" / "main.bicep").read_text()

    assert "var searchServiceEndpoint = !useSearchService" in bicep
    assert "!empty(searchServiceName)" in bicep
    assert "https://${searchServiceName}.search.windows.net" in bicep
    assert "empty(azureExistingAIProjectResourceId)" in bicep
    assert "ai!.outputs.searchServiceEndpoint" in bicep


def test_page_aware_citation_formatting():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from api.search_index_manager import SearchIndexManager

    assert SearchIndexManager.format_source_reference("aleppo_healthcare.md", None) == "aleppo_healthcare.md"
    assert SearchIndexManager.format_source_reference("Ministry_Report_2026.pdf", "17") == "Ministry_Report_2026.pdf, page 17"
    assert SearchIndexManager.format_source_reference("Ministry_Report_2026.pdf", 17) == "Ministry_Report_2026.pdf, page 17"


def test_qarar_pdf_dataset_contains_healthcare_statistics():
    pdf_path = ROOT / "data" / "healthcare_market_statistics_2026.pdf"
    assert pdf_path.exists()

    try:
        import fitz
    except ImportError:
        pytest = __import__("pytest")
        pytest.skip("PyMuPDF not installed in this environment")

    with fitz.open(str(pdf_path)) as doc:
        text = "\n".join(page.get_text("text") for page in doc)

    assert "Aleppo" in text
    assert "Damascus" in text
    assert "Latakia" in text
    assert "Hospitals" in text
