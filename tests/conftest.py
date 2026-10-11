import pytest


@pytest.fixture
def anyio_backend():
    # Run async tests on asyncio only, so the anyio plugin does not need trio.
    return "asyncio"
