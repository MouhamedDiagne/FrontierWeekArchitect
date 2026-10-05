from __future__ import annotations

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
from .models import FeedbackAnalysisResult, FeedbackType, ProblemCategory
from .utils import _log


class DataversePersistenceError(RuntimeError):
    """Raised when a completed analysis cannot be saved to Dataverse."""


# These labels must match the options configured in the Dataverse Choice columns.
# The installed Dataverse client resolves Choice labels to their option values.
# Keeping the mapping here means the rest of the application continues to use
# stable, language-neutral enum values.
_FEEDBACK_TYPE_CHOICE_LABELS: dict[FeedbackType, str] = {
    FeedbackType.ISSUE_REPORT: "Signalement de problème",
    FeedbackType.FEATURE_REQUEST: "Demande de fonctionnalité",
    FeedbackType.IMPROVEMENT_SUGGESTION: "Suggestion d’amélioration",
    FeedbackType.INFORMATION_REQUEST: "Question ou besoin d’information",
    FeedbackType.POSITIVE_FEEDBACK: "Éloge / retour positif",
    FeedbackType.OTHER_FEEDBACK: "Autre retour / non classable",
}

_PROBLEM_CATEGORY_CHOICE_LABELS: dict[ProblemCategory, str] = {
    ProblemCategory.BUG_ERROR: "Bug ou erreur",
    ProblemCategory.PERFORMANCE_SLOWDOWN: "Performance / lenteur",
    ProblemCategory.AVAILABILITY_RELIABILITY: "Indisponibilité / fiabilité",
    ProblemCategory.USABILITY_UX: "Difficulté d’usage / UX",
    ProblemCategory.ACCESS_AUTHENTICATION: "Accès / compte / authentification",
    ProblemCategory.DATA_QUALITY_REPORTING: "Données, rapports ou export",
    ProblemCategory.BILLING_PAYMENT: "Paiement / facturation",
    ProblemCategory.INTEGRATION: "Intégration / connecteurs / API",
    ProblemCategory.DOCUMENTATION_INFORMATION: (
        "Documentation ou information manquante"
    ),
    ProblemCategory.SUPPORT_EXPERIENCE: "Expérience avec le support",
    ProblemCategory.SECURITY_PRIVACY: "Sécurité / confidentialité",
    ProblemCategory.OTHER_PROBLEM: "Autre problème",
}


class FeedbackRepository(Protocol):
    def save(
        self,
        *,
        raw_comment: str,
        analysis: FeedbackAnalysisResult,
        received_at: datetime,
        analyzed_at: datetime,
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
        analyzed_at: datetime,
    ) -> str:
        try:
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
                "agil_language": analysis.language,
                "agil_feedbacktype": _FEEDBACK_TYPE_CHOICE_LABELS[
                    analysis.feedback_type
                ],
                "agil_feedbacksummary": analysis.feedback_summary,
            }

            if analysis.primary_functionality is not None:
                payload["agil_primaryfunctionality"] = (
                    analysis.primary_functionality.id
                )
                payload["agil_primaryfunctionalityname"] = (
                    analysis.primary_functionality.name
                )

            if analysis.problem_category is not None:
                payload["agil_problemcategory"] = _PROBLEM_CATEGORY_CHOICE_LABELS[
                    analysis.problem_category
                ]

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
