from src.tools import build_tool_map
from src.tools.base import BaseTool


class TestToolRegistry:
    def test_build_tool_map_returns_all_tools(self):
        tools = build_tool_map()
        assert "calculator" in tools
        assert "web_search" in tools
        assert "doc_lookup" in tools

    def test_all_tools_are_base_tool_instances(self):
        tools = build_tool_map()
        for tool in tools.values():
            assert isinstance(tool, BaseTool)

    def test_all_tools_have_valid_schemas(self):
        tools = build_tool_map()
        for tool in tools.values():
            schema = tool.schema()
            assert schema["type"] == "function"
            assert "name" in schema["function"]
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]
