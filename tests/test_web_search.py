import json

import pytest

from src.tools.web_search import WebSearchTool


class TestWebSearchTool:
    @pytest.fixture
    def search(self):
        return WebSearchTool()

    def test_schema_has_required_fields(self, search):
        schema = search.schema()
        assert schema["type"] == "function"
        func = schema["function"]
        assert func["name"] == "web_search"
        assert "parameters" in func
        assert "query" in func["parameters"]["properties"]

    async def test_known_query_returns_results(self, search):
        result = await search({"query": "python programming language"})
        data = json.loads(result)
        assert len(data["results"]) == 2
        assert "Python" in data["results"][0]["title"]

    async def test_partial_match_returns_results(self, search):
        result = await search({"query": "machine learning basics"})
        data = json.loads(result)
        assert len(data["results"]) > 0

    async def test_unknown_query_returns_empty(self, search):
        result = await search({"query": "xyzzy nonexistent topic 12345"})
        data = json.loads(result)
        assert data["results"] == []
        assert "No results" in data["message"]

    async def test_case_insensitive(self, search):
        result = await search({"query": "PYTHON PROGRAMMING LANGUAGE"})
        data = json.loads(result)
        assert len(data["results"]) == 2

    async def test_validates_input(self, search):
        with pytest.raises(Exception):
            await search({})
