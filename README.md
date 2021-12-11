# asyncio-contextmanager-pool

A library providing a pool-like object for holding `AsyncContextManager` instances.

## Why?

Some objects, like MongoDB connections to a Replica Set, are expensive to create, time-wise. As a result, they are usually created once and then used across the entire application. This mitigates, or eliminates, the costs associated with creating and setting up such objects.

However, there are situations where one may need to dynamically create such objects. One such example would be a multi-tenant API that can talk to multiple instances.

One could use `cachetools` to hold the references, perhaps in a `TTLCache`, so that not "too many" instances are kept (especially when not used), but then they must also make sure that instances are cleaned up properly, sometimes with some leniency (TTL).

## Features

- Async Context Manager (`async with`) support to manage objects
- Memoizes instances based on the arguments used to create them, which prevents duplicates and saves init time
- Provides TTL support, so that objects are kept for a set period of time after not being used, which again helps preventing duplication

## Usage

```python
import asyncio
from asyncio_contextmanager_pool import Pool


class Example:
    """
    A dummy implementation of an AsyncContextManager
    that "knows" when it was used.
    """
    def __init__(self, message: str) -> None:
        self.message = message

        self.enter_called = 0
        self.exit_called = 0

    async def __aenter__(self):
        self.enter_called += 1
        return self

    async def __aexit__(self, *args, **kwargs):
        self.exit_called += 1


async with Pool(Example, ttl=5) as p:
    # Get an instance of Example
    async with p.get("hello, world") as inst_1:
        # Use it
        assert inst_1.message == "hello, world"

    # Here, under normal circumstances, `inst_1` is still alive
    assert inst_1.exit_called == 0

    # So, if I `get` it again...
    async with p.get("hello, world") as inst_2:
        # And use it...
        assert inst_2.message == "hello, world"
    
    # I will get the exact same object
    assert inst_1 is inst_2

    # Now, let's assume some time passes...
    await asyncio.sleep(10)

    # Here, inst_1 already expired, so inst_3
    # will be a new object...
    async with p.get("hello, world") as inst_3:
        assert inst_3.message == "hello, world"

    assert inst_1 is not inst_3
    assert inst_1.exit_called == 1

# And after the `async with` block, everything is cleaned:
assert inst_3.exit_called == 1
```

## Notes

### Pickle support

If a `Pool` instance is copied via Pickle (e.g., through `multiprocessing.Process` or a `concurrent.futures.ProcessPoolExecutor`), the instances are not copied.

This is by design, because:

- Some objects should not be copied between processes (e.g., `pymongo.MongoClient`)
- Object expiration uses `asyncio`'s Timer functions, which are attached to the Event Loop. Event Loops cannot be shared between processes.
