import json

from pydantic import BaseModel, Field

from src.tools.base import BaseTool

_CANNED_RESULTS: dict[str, list[dict]] = {
    "python programming language": [
        {
            "title": "Python (programming language) - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
            "snippet": "Python is a high-level, general-purpose programming language. Its design philosophy emphasizes code readability with the use of significant indentation.",
        },
        {
            "title": "Welcome to Python.org",
            "url": "https://www.python.org/",
            "snippet": "Python is a programming language that lets you work quickly and integrate systems more effectively.",
        },
    ],
    "machine learning": [
        {
            "title": "Machine learning - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Machine_learning",
            "snippet": "Machine learning is a subset of artificial intelligence that provides systems the ability to automatically learn and improve from experience without being explicitly programmed.",
        },
        {
            "title": "What is Machine Learning? | IBM",
            "url": "https://www.ibm.com/topics/machine-learning",
            "snippet": "Machine learning is a branch of AI and computer science that focuses on using data and algorithms to enable AI to imitate the way that humans learn.",
        },
    ],
    "opentelemetry tracing": [
        {
            "title": "OpenTelemetry",
            "url": "https://opentelemetry.io/",
            "snippet": "OpenTelemetry is a collection of APIs, SDKs, and tools to instrument, generate, collect, and export telemetry data (metrics, logs, and traces).",
        },
    ],
    "fastapi python": [
        {
            "title": "FastAPI",
            "url": "https://fastapi.tiangolo.com/",
            "snippet": "FastAPI is a modern, fast (high-performance), web framework for building APIs with Python based on standard Python type hints.",
        },
    ],
    "population of france": [
        {
            "title": "Demographics of France - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Demographics_of_France",
            "snippet": "The population of metropolitan France was estimated at 68.4 million as of January 2024.",
        },
    ],
}


def _normalize(query: str) -> str:
    return query.lower().strip()


def _match(query: str) -> list[dict]:
    normalized = _normalize(query)
    if normalized in _CANNED_RESULTS:
        return _CANNED_RESULTS[normalized]
    for key, results in _CANNED_RESULTS.items():
        if key in normalized or normalized in key:
            return results
    return []


class WebSearchInput(BaseModel):
    query: str = Field(description="Search query string")


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for information. Returns a list of results with title, URL, and snippet."

    def input_model(self) -> type[BaseModel]:
        return WebSearchInput

    async def execute(self, validated_input: WebSearchInput) -> str:
        results = _match(validated_input.query)
        if not results:
            return json.dumps({"results": [], "message": "No results found"})
        return json.dumps({"results": results})
