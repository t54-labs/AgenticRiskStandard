"""Typed response models for ARS client SDK."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class CreateJobResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    agreement_hash: str
    phase: str


class SignatureResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    phase: str
    signatures: dict[str, bool]


class LockFeeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    fee_track_state: str
    lock_ref: str


class SettleFeeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    phase: str
    fee_track_state: Optional[str] = None
    settlement_ref: str


class UWResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    principal_track_state: Optional[str] = None


class MandateTrackResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    mandate_track_state: Optional[str] = None


class EvaluateResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    phase: str
    verdict: str


class DeliverableResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    fee_track_state: str
    deliverable_ref: str


class CollateralResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    collateral_ref: str


class PrincipalReleaseResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_id: str
    transfer_ref: str
