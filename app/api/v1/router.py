"""Aggregates every v1 router."""

from fastapi import APIRouter

from app.api.v1 import (
    audit,
    auth,
    biomarkers,
    documents,
    emergency,
    family,
    insurance,
    internal_ai,
    medications,
    patients,
    records,
    sharing,
    wellness,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(patients.router)
api_router.include_router(documents.router)
api_router.include_router(records.router)
api_router.include_router(biomarkers.router)
api_router.include_router(medications.router)
api_router.include_router(wellness.router)
api_router.include_router(family.router)
api_router.include_router(sharing.router)
api_router.include_router(emergency.router)
api_router.include_router(insurance.router)
api_router.include_router(audit.router)
api_router.include_router(internal_ai.router)

__all__ = ["api_router"]
