import abc

from pydantic import BaseModel


class BaseTool(abc.ABC):

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def description(self) -> str: ...

    @abc.abstractmethod
    def input_model(self) -> type[BaseModel]:
        """Return the Pydantic model class that validates this tool's input."""
        ...

    def schema(self) -> dict:
        model = self.input_model()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": model.model_json_schema(),
            },
        }

    async def __call__(self, input_data: dict) -> str:
        model = self.input_model()
        validated = model(**input_data)
        return await self.execute(validated)

    @abc.abstractmethod
    async def execute(self, validated_input: BaseModel) -> str: ...
