"""Shared demo-admission policy and non-sensitive operational record keys."""

from datetime import UTC, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


DAILY_JOB_LIMIT = 25


class DailyJobLimitExceeded(ValueError):
    def __init__(self) -> None:
        super().__init__("demo_daily_job_limit_reached")


class DemoAdmissionsPaused(ValueError):
    def __init__(self) -> None:
        super().__init__("demo_admissions_paused")


class AdmissionControl(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    schema_version: Literal["1"]
    enabled: bool


class DailyCounter(BaseModel):
    # Native DynamoDB numbers deserialize as Decimal; accept integral values.
    model_config = ConfigDict(extra="ignore")
    admitted_jobs: int = Field(ge=0)
    expires_at: int = Field(ge=0)


def utc_day(instant: datetime) -> str:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("admission_clock_requires_timezone")
    return instant.astimezone(UTC).date().isoformat()


def control_key() -> dict[str, str]:
    return {"pk": "CONTROL#QUESTION_ADMISSION", "sk": "CONFIG"}


def daily_counter_key(instant: datetime) -> dict[str, str]:
    return {"pk": f"ADMISSION#{utc_day(instant)}", "sk": "COUNTER"}


def counter_expires_at(instant: datetime) -> int:
    # Keep the closed day's count for at least another full day. TTL cleanup
    # cannot refill today's allowance; selecting the UTC date resets it.
    day = datetime.fromisoformat(utc_day(instant)).date() + timedelta(days=2)
    return int(datetime.combine(day, time.min, tzinfo=UTC).timestamp())
