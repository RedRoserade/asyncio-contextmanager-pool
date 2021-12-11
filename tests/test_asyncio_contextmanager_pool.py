import asyncio
import pytest
from asyncio_contextmanager_pool import Pool


@pytest.mark.asyncio
async def test_usage():
    """
    Test basic usage:

    Calling the get method multiple times with the same argument values
    must produce the same instance, if within the TTL.

    Calling the get method with different arguments must produce two different
    instances.

    After the Pool exits, all instances must be closed.
    """
    async with Pool(_Test) as c:

        async with c.get("hello") as h:
            assert h.message == "hello"

        async with c.get("hello") as h2:
            assert h2.message == "hello"

        assert h2 is h

        async with c.get("world") as h3:
            assert h3.message == "world"

        assert h3 is not h

        assert h.enter_called == 1
        assert h.exit_called == 0

        assert h3.enter_called == 1
        assert h3.exit_called == 0

    # After the Pool exits, all instances must be closed.
    assert h.enter_called == 1
    assert h.exit_called == 1

    assert h3.enter_called == 1
    assert h3.exit_called == 1


@pytest.mark.asyncio
async def test_ttl():
    """
    Test TTL.

    Calling the get method twice within the TTL must produce the same instance.
    Calling it after the TTL expires must produce a new instance.
    """

    async with Pool(_Test, ttl=1) as c:

        async with c.get("hello") as h:
            assert h.message == "hello"

        # Less than the TTL
        await asyncio.sleep(0.1)

        assert h.enter_called == 1
        assert h.exit_called == 0

        async with c.get("hello") as h2:
            assert h2.message == "hello"

        assert h2 is h

        # More than the TTL
        await asyncio.sleep(2)

        assert h.enter_called == 1
        assert h.exit_called == 1

        async with c.get("hello") as h3:
            assert h3.message == "hello"

        assert h3 is not h


class _Test:
    def __init__(self, message: str) -> None:
        self.message = message

        self.enter_called = 0
        self.exit_called = 0

    async def __aenter__(self):
        self.enter_called += 1
        return self

    async def __aexit__(self, *args, **kwargs):
        self.exit_called += 1
