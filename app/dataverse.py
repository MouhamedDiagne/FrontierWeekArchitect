from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from azure.identity import ClientSecretCredential
from PowerPlatform.Dataverse.client import DataverseClient

from .config import (
    DATAVERSE_CLIENT_ID,
    DATAVERSE_CLIENT_SECRET,
    DATAVERSE_FEEDBACK_TABLE,
    DATAVERSE_TENANT_ID,
    DATAVERSE_URL,
)
from .errors import _log_error
from .models import FeedbackAnalysisResult
from .utils import _log


class DataversePersistenceError(RuntimeError):
    """Raised when a completed analysis cannot be saved to Dataverse."""


class FeedbackRepository(Protocol):
    def save(
        self,
        *,
        raw_comment: str,
        analysis: FeedbackAnalysisResult,
        received_at: datetime,
    ) -> str:
        ...


class DataverseFeedbackRepository:
    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        table_logical_name: str,
        verbose: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._table_logical_name = table_logical_name
        self._client_secret = client_secret
        self._credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        self._verbose = verbose

    @classmethod
    def from_environment(
        cls,
        *,
        verbose: bool = True,
    ) -> "DataverseFeedbackRepository":
        values = {
            "DATAVERSE_URL": DATAVERSE_URL,
            "DATAVERSE_TENANT_ID": DATAVERSE_TENANT_ID,
            "DATAVERSE_CLIENT_ID": DATAVERSE_CLIENT_ID,
            "DATAVERSE_CLIENT_SECRET": DATAVERSE_CLIENT_SECRET,
            "DATAVERSE_FEEDBACK_TABLE": DATAVERSE_FEEDBACK_TABLE,
        }
        missing = [name for name, value in values.items() if not value]

        if missing:
            raise RuntimeError(
                f"Dataverse configuration missing: {', '.join(missing)}."
            )

        return cls(
            base_url=str(DATAVERSE_URL),
            tenant_id=str(DATAVERSE_TENANT_ID),
            client_id=str(DATAVERSE_CLIENT_ID),
            client_secret=str(DATAVERSE_CLIENT_SECRET),
            table_logical_name=str(DATAVERSE_FEEDBACK_TABLE),
            verbose=verbose,
        )

    @staticmethod
    def _to_utc_iso8601(value: datetime) -> str:
        if value.tzinfo is None:
            raise ValueError("Dataverse timestamps must include a timezone.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def save(
        self,
        *,
        raw_comment: str,
        analysis: FeedbackAnalysisResult,
        received_at: datetime,
        analyzed_at: datetime
    ) -> str:

        # Replace every agil_* key with your real Dataverse column logical name.
        payload = {
            "agil_feedbackreference": f"feedback-{uuid4()}",
            "agil_rawcomment": raw_comment,
            "agil_receivedat": self._to_utc_iso8601(received_at),
            "agil_analyzedat": self._to_utc_iso8601(analyzed_at),
            "agil_softwareid": analysis.software.id,
            "agil_softwarename": analysis.software.name,
            "agil_sentiment": analysis.sentiment.value,
            "agil_confidence": analysis.percentage,
            "agil_extractedfunctionalities": json.dumps(
                [
                    {"id": item.id, "name": item.name}
                    for item in analysis.functionalities
                ],
                ensure_ascii=False,
            ),
            "agil_language": analysis.language,
        }

        try:
            _log(
                "persistence",
                "Creating the feedback-analysis record in Dataverse.",
                verbose=self._verbose,
            )

            with DataverseClient(
                base_url=self._base_url,
                credential=self._credential,
            ) as client:
                record_id = client.records.create(
                    self._table_logical_name,
                    payload,
                )

            _log(
                "persistence",
                f"Dataverse record created: {record_id}.",
                verbose=self._verbose,
            )
            return record_id

        except Exception as error:
            _log_error(
                "dataverse",
                "feedback_save_failed",
                error,
                sensitive_values=(raw_comment, self._client_secret),
            )
            raise DataversePersistenceError(
                "The analysis succeeded but could not be saved to Dataverse."
            ) from error