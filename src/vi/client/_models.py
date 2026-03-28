"""Typed response models for VI client SDK."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class CredentialTrackResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    credential_track_state: Optional[str] = None


class ChainVerificationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    credential_track_state: Optional[str] = None
    constraint_check: Optional[dict] = None


class SelectivePresentationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    l1_credential: Optional[str] = None
    l3a_payment: Optional[dict] = None
    l3b_checkout: Optional[dict] = None
    presentation_type: str
