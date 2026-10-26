# Created by appgen once. appgen never changes or deletes this file.
# @trace:manual app file
"""The hand-written routers of the app.

`app/main.py` includes each router of `ROUTERS` after the generated
routers, so the middleware of the app (the CORS, the rate limit, and the
log) applies to them too. Add a router here for an
endpoint that the definition does not describe, for example a collect
endpoint for a tracking script. appgen creates this file once and never
changes it.

Example:

    from fastapi import APIRouter

    from app.core.db import SessionDep

    router = APIRouter(prefix="/extensions", tags=["extensions"])


    @router.get("/ping")
    async def ping(session: SessionDep) -> dict[str, str]:
        return {"status": "ok"}


    ROUTERS: list[APIRouter] = [router]
"""

from fastapi import APIRouter

ROUTERS: list[APIRouter] = []
"""The hand-written routers, in the order that the app includes them."""
