from __future__ import annotations
import asyncio
import logging
from asyncio.events import TimerHandle
from typing import (
    Callable,
    AsyncContextManager,
    Dict,
    Generic,
    Hashable,
    ParamSpec,
    TypeVar,
)

_log = logging.getLogger(__name__)


_TArgs = ParamSpec("_TArgs")
_TValue = TypeVar("_TValue")


def reduce_args(*args, **kwargs) -> int:
    """
    Call the built-in hash function on the arguments.

    Positional arguments are passed in order.
    Named arguments are passed in alphabetical order.
    """
    hash_values = [*args]

    kwargs_keys = sorted(kwargs)

    for k in kwargs_keys:
        hash_values.append(k)
        hash_values.append(kwargs[k])

    return hash(tuple(hash_values))


class _Holder(Generic[_TValue]):
    """
    Holder for a, AsyncContextManager of a value.

    Not to be used directly.
    """

    def __init__(
        self, cache: Pool, key: Hashable, value: AsyncContextManager[_TValue]
    ) -> None:
        self._value = value
        self._count = 0

        self._called_aenter = False
        self._managed_value = None
        self._cache = cache
        self._key = key

    async def __aenter__(self) -> _TValue:
        self._count += 1

        if not self._called_aenter:
            self._called_aenter = True
            self._managed_value = await self._value.__aenter__()

        if self._managed_value is None:
            raise RuntimeError("Not possible?")

        return self._managed_value

    async def close(self):
        await self._value.__aexit__(None, None, None)

    async def __aexit__(self, *args, **kwargs):
        self._count -= 1

        if self._count < 0:
            raise RuntimeError("__aexit__ called too many times")

        if self._count == 0:
            self._cache._mark_for_deletion(self._key)


class Pool(Generic[_TValue, _TArgs]):
    """
    A pool for AsyncContextManager instances.

    When instances are created, they are stored in this pool. The get method will return an AsyncContextManager (to be used with `async with`),
    which will keep track of the number of "references" to the object that it holds.

    Once all "references" to the object are removed (as per `__aexit__` semantics), the object is marked for deletion,
    and removed after a set TTL.
    """

    __slots__ = ("_getter", "_key", "_instances", "_timers", "_ttl", "_pickleable")

    def __init__(
        self,
        getter: Callable[_TArgs, AsyncContextManager[_TValue]],
        *,
        key: Callable[_TArgs, Hashable] = reduce_args,
        ttl: float = 30,
    ) -> None:
        """
        Create a pool for AsyncContextManager instances.

        :param getter: A callable that returns an AsyncContextManager. Can also be a class, whose __init__ will be used to get the instance.
        :param key: A function that will serialize the arguments to a hashable value (such as an int, str, etc.).
        :param ttl: A non-negative float value that will determine how long, in seconds, to keep an object once all "references" to it are removed.
        """
        self._getter = getter
        self._key = key
        self._instances: Dict[Hashable, _Holder] = {}
        self._timers: Dict[Hashable, TimerHandle] = {}
        self._ttl = ttl

    def get(self, *args, **kwargs) -> AsyncContextManager[_TValue]:
        """
        Get an AsyncContextManager object holding the instance associated with the specified arguments.

        If the instance does not exist in the pool, it is created and stored in the pool.

        To get access to the object itself, you must use the `async with` construct.
        """
        key = self._key(*args, **kwargs)

        # Prevent the instance from being deleted if it exists
        # and it didn't expire yet.
        self._stop_timer(key)

        if key not in self._instances:
            _log.debug("Creating key=%r", key)
            value = self._getter(*args, **kwargs)
            self._instances[key] = _Holder(self, key, value)

        return self._instances[key]

    def _mark_for_deletion(self, key: Hashable):
        """Mark an object for deletion."""
        self._stop_timer(key)

        loop = asyncio.get_event_loop()

        def _delete():
            return asyncio.create_task(self._delete(key))

        self._timers[key] = loop.call_later(self._ttl, _delete)

    def __len__(self) -> int:
        return len(self._instances)

    def _stop_timer(self, key: Hashable):
        timer = self._timers.pop(key, None)

        if timer is not None:
            _log.debug("Stopping timer for key=%r", key)
            timer.cancel()

    async def _delete(self, key: Hashable):
        self._stop_timer(key)

        instance = self._instances.pop(key, None)

        if instance is not None:
            _log.debug("Closing key=%r", key)
            await instance.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args, **kwargs):
        keys = list(self._instances)

        for k in keys:
            await self._delete(k)

    def __getstate__(self):

        state = {slot: getattr(self, slot) for slot in self.__slots__}

        # Asyncio cannot run between processes, and instances should not be pickled.
        blacklist = ("_instances", "_timers")

        for k in blacklist:
            state[k] = {}

        return state

    def __setstate__(self, state):
        for k, v in state.items():
            setattr(self, k, v)
