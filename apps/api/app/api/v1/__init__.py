"""Version 1 HTTP API."""

from fastapi import APIRouter, Depends

from app.api.dependencies import authenticate_request
from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.organizations import router as organizations_router

router = APIRouter(prefix="/api/v1", dependencies=[Depends(authenticate_request)])
router.include_router(organizations_router)
router.include_router(api_keys_router)
