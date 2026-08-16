import pytest

from src.tools.doc_lookup import DocLookupTool

from pathlib import Path


class TestDocLookupTool:
    @pytest.fixture
    def lookup(self):
        return DocLookupTool()

    def test_schema_has_required_fields(self, lookup):
        schema = lookup.schema()
        assert schema["type"] == "function"
        func = schema["function"]
        assert func["name"] == "doc_lookup"
        assert "query" in func["parameters"]["properties"]

    async def test_finds_python_docs(self, lookup):
        result = await lookup({"query": "Python programming language"})
        assert "[Source: python_overview]" in result
        assert "Python" in result

    async def test_finds_fastapi_docs(self, lookup):
        result = await lookup({"query": "FastAPI web framework"})
        assert "[Source: fastapi_guide]" in result

    async def test_finds_postgresql_docs(self, lookup):
        result = await lookup({"query": "PostgreSQL database JSONB"})
        assert "[Source: postgresql_essentials]" in result

    async def test_finds_opentelemetry_docs(self, lookup):
        result = await lookup({"query": "OpenTelemetry tracing spans"})
        assert "[Source: opentelemetry_basics]" in result

    async def test_no_match_returns_message(self, lookup):
        result = await lookup({"query": "xyzzy nonexistent"})
        assert "No relevant documents found" in result

    async def test_empty_docs_dir(self, tmp_path):
        lookup = DocLookupTool(docs_dir=tmp_path / "empty")
        result = await lookup({"query": "anything"})
        assert "No documents available" in result

    async def test_validates_input(self, lookup):
        with pytest.raises(Exception):
            await lookup({})
