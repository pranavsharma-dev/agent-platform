from pathlib import Path

from pydantic import BaseModel, Field

from src.tools.base import BaseTool

_DEFAULT_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "docs"


def _load_documents(docs_dir: Path) -> dict[str, str]:
    docs = {}
    if not docs_dir.is_dir():
        return docs
    for fpath in docs_dir.iterdir():
        if fpath.suffix == ".txt" and fpath.is_file():
            docs[fpath.stem] = fpath.read_text(encoding="utf-8")
    return docs


def _score(query: str, text: str) -> int:
    query_words = query.lower().split()
    text_lower = text.lower()
    return sum(1 for w in query_words if w in text_lower)


def _find_relevant_chunk(query: str, text: str, chunk_size: int = 500) -> str:
    lines = text.split("\n")
    best_start = 0
    best_score = -1
    query_lower = query.lower()
    query_words = query_lower.split()

    for i, line in enumerate(lines):
        line_lower = line.lower()
        score = sum(1 for w in query_words if w in line_lower)
        if score > best_score:
            best_score = score
            best_start = i

    start = max(0, best_start - 2)
    chunk_lines = []
    total_len = 0
    for line in lines[start:]:
        chunk_lines.append(line)
        total_len += len(line)
        if total_len >= chunk_size:
            break

    return "\n".join(chunk_lines)


class DocLookupInput(BaseModel):
    query: str = Field(description="Search query to find relevant documentation")


class DocLookupTool(BaseTool):
    name = "doc_lookup"
    description = "Look up information in the local document collection. Returns the most relevant passage."

    def __init__(self, docs_dir: Path | None = None):
        self._docs_dir = docs_dir or _DEFAULT_DOCS_DIR
        self._documents: dict[str, str] | None = None

    @property
    def _docs(self) -> dict[str, str]:
        if self._documents is None:
            self._documents = _load_documents(self._docs_dir)
        return self._documents

    def input_model(self) -> type[BaseModel]:
        return DocLookupInput

    async def execute(self, validated_input: DocLookupInput) -> str:
        query = validated_input.query
        if not self._docs:
            return "No documents available."

        scored = [
            (name, _score(query, text), text)
            for name, text in self._docs.items()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        best_name, best_score, best_text = scored[0]
        if best_score == 0:
            return "No relevant documents found."

        chunk = _find_relevant_chunk(query, best_text)
        return f"[Source: {best_name}]\n{chunk}"
