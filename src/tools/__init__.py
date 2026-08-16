from src.tools.base import BaseTool
from src.tools.calculator import CalculatorTool
from src.tools.doc_lookup import DocLookupTool
from src.tools.web_search import WebSearchTool

ALL_TOOLS: list[type[BaseTool]] = [
    CalculatorTool,
    WebSearchTool,
    DocLookupTool,
]


def build_tool_map() -> dict[str, BaseTool]:
    return {tool_cls().name: tool_cls() for tool_cls in ALL_TOOLS}
