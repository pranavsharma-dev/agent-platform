import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def no_db():
    """Disable database connections for unit tests."""
    with (
        patch("src.db.init_db", new_callable=AsyncMock),
        patch("src.db.close_db", new_callable=AsyncMock),
    ):
        yield
