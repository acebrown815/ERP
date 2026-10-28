"""Display-name resolution across modules without import dependencies.

Owning modules register a resolver at startup (e.g. "party" -> names by id); readers such as ledger
reports call `resolve` and get {} for kinds nobody registered.
"""

import uuid
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

Resolver = Callable[[AsyncSession, list[uuid.UUID]], Awaitable[dict[uuid.UUID, str]]]
_resolvers: dict[str, Resolver] = {}


def register(kind: str, resolver: Resolver) -> None:
    _resolvers[kind] = resolver


async def resolve(session: AsyncSession, kind: str, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = list({i for i in ids if i is not None})
    resolver = _resolvers.get(kind)
    if not wanted or resolver is None:
        return {}
    return await resolver(session, wanted)
