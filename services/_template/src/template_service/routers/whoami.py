"""Example protected route: returns the verified claims for the bearer token."""

from typing import Annotated

from fastapi import APIRouter, Depends

from auth import Claims

from ..main_deps import current_user

router = APIRouter(prefix="/whoami", tags=["whoami"])


@router.get("", summary="Return the calling user's verified claims")
async def whoami(claims: Annotated[Claims, Depends(current_user)]) -> dict[str, object]:
    return {
        "sub": str(claims.sub),
        "tid": str(claims.tid),
        "roles": claims.roles,
        "scope": claims.scope,
        "mfa": claims.mfa,
        "iss": claims.iss,
    }
