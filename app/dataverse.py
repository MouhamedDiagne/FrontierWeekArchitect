from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from azure.identity import ClientSecretCredential
from PowerPlatform.Dataverse.client import DataverseClient

from .config import (
    CLUSTER_MAX_FEEDBACKS,
    DATAVERSE_CLIENT_ID,
    DATAVERSE_CLIENT_SECRET,
    DATAVERSE_FEEDBACK_TABLE,
    DATAVERSE_INSIGHT_ANALYSIS_TABLE,
    DATAVERSE_TENANT_ID,
    DATAVERSE_URL,
)
from .errors import _log_error
from .models import (
    FeedbackAnalysisResult,
    FeedbackInsightsFilters,
    FeedbackInsightsSnapshot,
    FeedbackRecordForInsights,
    FeedbackType,
    ProblemCategory,
    SentimentLabel,
)
from .utils import _log


class DataversePersistenceError(RuntimeError):
    """Raised when a completed analysis cannot be saved to Dataverse."""


class DataverseInsightsReadError(RuntimeError):
    """Raised when feedback records cannot safely be read for insights."""


class DataverseInsightsPersistenceError(RuntimeError):
    """Raised when a completed insights snapshot cannot be saved."""


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

class FeedbackReader(Protocol):
    def list_for_insights(
        self,
        filters: FeedbackInsightsFilters,
    ) -> list[FeedbackRecordForInsights]:
        ...


class InsightsSnapshotRepository(Protocol):
    """Persistence boundary for immutable POC historical-analysis snapshots."""

    def save_snapshot(self, *, snapshot: FeedbackInsightsSnapshot) -> str:
        ...

    def latest_snapshot(self) -> FeedbackInsightsSnapshot | None:
        ...

@dataclass(frozen=True)
class DataverseFeedbackColumnMap:
    """One location for the physical Dataverse column names used by this app.

    This does not create or alter Dataverse schema. It lets the application use
    stable, meaningful Python names while the table keeps its logical names.
    Optional client and segment columns are deliberately unset for the current
    single-table POC and can be configured when such fields are later added.
    """

    feedback_id: str = "agil_feedbackreference"
    raw_comment: str = "agil_rawcomment"
    received_at: str = "agil_receivedat"
    analyzed_at: str = "agil_analyzedat"
    software_id: str = "agil_softwareid"
    software_name: str = "agil_softwarename"
    feedback_summary: str = "agil_feedbacksummary"
    feedback_type: str = "agil_feedbacktype"
    problem_category: str = "agil_problemcategory"
    sentiment: str = "agil_sentiment"
    confidence: str = "agil_confidence"
    language: str = "agil_language"
    functionality: str = "agil_primaryfunctionality"
    functionality_name: str = "agil_primaryfunctionalityname"
    client_id: str | None = None
    segment: str | None = None

class DataverseFeedbackRepository:
    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        table_logical_name: str,
        column_map: DataverseFeedbackColumnMap | None = None,
        insights_max_records: int = CLUSTER_MAX_FEEDBACKS,
        verbose: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._table_logical_name = table_logical_name
        self._client_secret = client_secret
        self._columns = column_map or DataverseFeedbackColumnMap()
        if insights_max_records <= 0:
            raise ValueError("insights_max_records must be greater than zero.")
        self._insights_max_records = insights_max_records
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
            columns = self._columns
            payload = {
                columns.feedback_id: f"feedback-{uuid4()}",
                columns.raw_comment: raw_comment,
                columns.received_at: self._to_utc_iso8601(received_at),
                columns.analyzed_at: self._to_utc_iso8601(analyzed_at),
                columns.software_id: analysis.software.id,
                columns.software_name: analysis.software.name,
                columns.sentiment: analysis.sentiment.value,
                columns.confidence: analysis.percentage,
                columns.language: analysis.language,
                columns.feedback_type: _FEEDBACK_TYPE_CHOICE_LABELS[
                    analysis.feedback_type
                ],
                columns.feedback_summary: analysis.feedback_summary,
            }

            if analysis.primary_functionality is not None:
                payload[columns.functionality] = (
                    analysis.primary_functionality.id
                )
                payload[columns.functionality_name] = (
                    analysis.primary_functionality.name
                )

            if analysis.problem_category is not None:
                payload[columns.problem_category] = _PROBLEM_CATEGORY_CHOICE_LABELS[
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

    @staticmethod
    def _odata_escape(value: str) -> str:
        """Escape a trusted, validated string for a literal OData filter."""

        return value.replace("'", "''")

    @classmethod
    def _build_insights_filter(cls, filters: FeedbackInsightsFilters, columns: DataverseFeedbackColumnMap) -> str:
        conditions = [
            f"{columns.received_at} ge {cls._to_utc_iso8601(filters.start_date)}",
            f"{columns.received_at} lt {cls._to_utc_iso8601(filters.end_date)}",
        ]
        if filters.software_id is not None:
            conditions.append(
                f"{columns.software_id} eq '{cls._odata_escape(filters.software_id)}'"
            )
        if filters.functionality_id is not None:
            conditions.append(
                f"{columns.functionality} eq "
                f"'{cls._odata_escape(filters.functionality_id)}'"
            )
        return " and ".join(conditions)

    @staticmethod
    def _value_from_record(
        record: Any,
        column: str | None,
        *,
        formatted: bool = False,
    ) -> Any:
        if column is None:
            return None
        getter = getattr(record, "get", None)
        if not callable(getter):
            raise TypeError("Dataverse returned a record without mapping access.")

        if formatted:
            formatted_value = getter(
                f"{column}@OData.Community.Display.V1.FormattedValue"
            )
            if formatted_value not in (None, ""):
                return formatted_value
        return getter(column)

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError("received_at is missing or is not a timestamp.")
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("received_at is missing its timezone.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _normalise_choice_value(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.split()).casefold()
        return normalized or None

    @classmethod
    def _parse_feedback_type(cls, value: Any) -> FeedbackType | None:
        normalized = cls._normalise_choice_value(value)
        if normalized is None:
            return None
        for feedback_type, label in _FEEDBACK_TYPE_CHOICE_LABELS.items():
            if normalized in {
                feedback_type.value.casefold(),
                cls._normalise_choice_value(label),
            }:
                return feedback_type
        return None

    @classmethod
    def _parse_problem_category(cls, value: Any) -> ProblemCategory | None:
        normalized = cls._normalise_choice_value(value)
        if normalized is None:
            return None
        for category, label in _PROBLEM_CATEGORY_CHOICE_LABELS.items():
            if normalized in {
                category.value.casefold(),
                cls._normalise_choice_value(label),
            }:
                return category
        return None

    @classmethod
    def _parse_sentiment(cls, value: Any) -> SentimentLabel | None:
        normalized = cls._normalise_choice_value(value)
        if normalized is None:
            return None
        try:
            return SentimentLabel(normalized)
        except ValueError:
            return None

    def _record_for_insights(self, record: Any) -> FeedbackRecordForInsights:
        columns = self._columns
        feedback_id = self._value_from_record(record, columns.feedback_id)
        software_id = self._value_from_record(record, columns.software_id)
        if not isinstance(feedback_id, str) or not feedback_id.strip():
            raise ValueError("feedback_id is missing from the Dataverse record.")
        if not isinstance(software_id, str) or not software_id.strip():
            raise ValueError("software_id is missing from the Dataverse record.")

        return FeedbackRecordForInsights(
            feedback_id=feedback_id,
            received_at=self._parse_datetime(
                self._value_from_record(record, columns.received_at)
            ),
            software_id=software_id,
            feedback_summary=self._value_from_record(
                record,
                columns.feedback_summary,
            ),
            raw_comment=self._value_from_record(record, columns.raw_comment),
            sentiment=self._parse_sentiment(
                self._value_from_record(record, columns.sentiment, formatted=True)
            ),
            feedback_type=self._parse_feedback_type(
                self._value_from_record(record, columns.feedback_type, formatted=True)
            ),
            problem_category=self._parse_problem_category(
                self._value_from_record(
                    record,
                    columns.problem_category,
                    formatted=True,
                )
            ),
            primary_functionality=self._value_from_record(
                record,
                columns.functionality,
            ),
            primary_functionality_name=self._value_from_record(
                record,
                columns.functionality_name,
            ),
            client_id=self._value_from_record(record, columns.client_id),
            segment=self._value_from_record(record, columns.segment),
        )

    @staticmethod
    def _matches_in_memory_filters(
        record: FeedbackRecordForInsights,
        filters: FeedbackInsightsFilters,
    ) -> bool:
        """Apply Choice-backed filters after formatted labels have been decoded.

        Dataverse Choice values are stored as environment-specific integers. The
        application therefore applies intent and sentiment filters only after a
        narrowly date/software/functionality-filtered server query, instead of
        hard-coding Choice numbers or accepting arbitrary model OData.
        """

        if filters.sentiment is not None and record.sentiment != filters.sentiment:
            return False
        if (
            filters.feedback_type is not None
            and record.feedback_type != filters.feedback_type
        ):
            return False
        return True

    def list_for_insights(
        self,
        filters: FeedbackInsightsFilters,
    ) -> list[FeedbackRecordForInsights]:
        """Read normalized feedback records without altering any Dataverse row."""

        stage = "insights_read"
        try:
            columns = self._columns
            selected_columns = [
                columns.feedback_id,
                columns.raw_comment,
                columns.received_at,
                columns.software_id,
                columns.feedback_summary,
                columns.feedback_type,
                columns.problem_category,
                columns.sentiment,
                columns.functionality,
                columns.functionality_name,
            ]
            # Preserve order while avoiding duplicate select expressions when a
            # deployment uses the same physical column for two optional fields.
            selected_columns = list(dict.fromkeys(selected_columns))
            query_filter = self._build_insights_filter(filters, columns)

            _log(
                "dataverse",
                "Reading feedback records for temporary insights.",
                verbose=self._verbose,
            )
            with DataverseClient(
                base_url=self._base_url,
                credential=self._credential,
            ) as client:
                records = list(
                    client.records.list(
                        self._table_logical_name,
                        filter=query_filter,
                        select=selected_columns,
                        orderby=[f"{columns.received_at} asc"],
                        top=self._insights_max_records + 1,
                        include_annotations="OData.Community.Display.V1.FormattedValue",
                    )
                )

            if len(records) > self._insights_max_records:
                raise DataverseInsightsReadError(
                    "The requested period exceeds the configured feedback-analysis limit."
                )

            normalized_records: list[FeedbackRecordForInsights] = []
            skipped_count = 0
            for record in records:
                try:
                    normalized_record = self._record_for_insights(record)
                except Exception:
                    # A malformed historical row should not expose its text in
                    # diagnostics or prevent valid rows from being reported.
                    skipped_count += 1
                    continue
                if self._matches_in_memory_filters(normalized_record, filters):
                    normalized_records.append(normalized_record)

            _log(
                "dataverse",
                (
                    f"Read {len(normalized_records)} feedback record(s) for insights"
                    f"; skipped {skipped_count} malformed record(s)."
                ),
                verbose=self._verbose,
            )
            return normalized_records
        except Exception as error:
            _log_error(
                "dataverse",
                f"{stage}_failed",
                error,
                sensitive_values=(self._client_secret,),
            )
            if isinstance(error, DataverseInsightsReadError):
                raise
            raise DataverseInsightsReadError(
                "Feedback records could not be read from Dataverse."
            ) from error


_INSIGHT_SNAPSHOT_JSON_MAX_LENGTH = 1_000_000


@dataclass(frozen=True)
class DataverseInsightAnalysisColumnMap:
    """Physical columns for the separate, immutable insight-analysis table."""

    name: str = "agil_agilname"
    analysis_reference: str = "agil_analysisreference"
    generated_at: str = "agil_generatedat"
    source: str = "agil_source"
    period_start: str = "agil_periodstart"
    period_end: str = "agil_periodend"
    comparison_start: str = "agil_comparisonstart"
    comparison_end: str = "agil_comparisonend"
    software_id: str = "agil_softwareid"
    functionality_id: str = "agil_functionalityid"
    audience_profile: str = "agil_audienceprofile"
    total_feedbacks: str = "agil_totalfeedbacks"
    clustered_feedbacks: str = "agil_clusteredfeedbacks"
    cluster_count: str = "agil_clustercount"
    insights_json: str = "agil_insightsjson"
    audience_report_json: str = "agil_audiencereportsjson"
    schema_version: str = "agil_schemaversion"


class DataverseInsightAnalysisRepository:
    """Store and retrieve POC analysis snapshots without altering feedback rows."""

    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        table_logical_name: str,
        column_map: DataverseInsightAnalysisColumnMap | None = None,
        verbose: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._table_logical_name = table_logical_name
        self._client_secret = client_secret
        self._columns = column_map or DataverseInsightAnalysisColumnMap()
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
    ) -> "DataverseInsightAnalysisRepository":
        values = {
            "DATAVERSE_URL": DATAVERSE_URL,
            "DATAVERSE_TENANT_ID": DATAVERSE_TENANT_ID,
            "DATAVERSE_CLIENT_ID": DATAVERSE_CLIENT_ID,
            "DATAVERSE_CLIENT_SECRET": DATAVERSE_CLIENT_SECRET,
            "DATAVERSE_INSIGHT_ANALYSIS_TABLE": DATAVERSE_INSIGHT_ANALYSIS_TABLE,
        }
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError(
                f"Dataverse insight-analysis configuration missing: {', '.join(missing)}."
            )
        return cls(
            base_url=str(DATAVERSE_URL),
            tenant_id=str(DATAVERSE_TENANT_ID),
            client_id=str(DATAVERSE_CLIENT_ID),
            client_secret=str(DATAVERSE_CLIENT_SECRET),
            table_logical_name=str(DATAVERSE_INSIGHT_ANALYSIS_TABLE),
            verbose=verbose,
        )

    @staticmethod
    def _to_utc_iso8601(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Dataverse timestamps must include a timezone.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _record_value(record: Any, column: str) -> Any:
        getter = getattr(record, "get", None)
        if not callable(getter):
            raise TypeError("Dataverse returned a record without mapping access.")
        return getter(column)

    @staticmethod
    def _serialized_snapshot_values(
        snapshot: FeedbackInsightsSnapshot,
    ) -> tuple[str, str]:
        insights_json = snapshot.insights.model_dump_json()
        audience_report_json = snapshot.audience_report.model_dump_json()
        if len(insights_json) > _INSIGHT_SNAPSHOT_JSON_MAX_LENGTH:
            raise ValueError("The insights snapshot exceeds the Dataverse text limit.")
        if len(audience_report_json) > _INSIGHT_SNAPSHOT_JSON_MAX_LENGTH:
            raise ValueError("The audience report exceeds the Dataverse text limit.")
        return insights_json, audience_report_json

    def save_snapshot(self, *, snapshot: FeedbackInsightsSnapshot) -> str:
        """Create one immutable snapshot after a successful historical analysis."""

        try:
            snapshot = FeedbackInsightsSnapshot.model_validate(snapshot)
            columns = self._columns
            request = snapshot.insights.request
            insights_json, audience_report_json = self._serialized_snapshot_values(snapshot)
            generated_at = self._to_utc_iso8601(snapshot.generated_at)
            payload: dict[str, object] = {
                columns.name: f"Insights {generated_at}",
                columns.analysis_reference: f"insights-{uuid4()}",
                columns.generated_at: generated_at,
                columns.source: snapshot.source.value,
                columns.period_start: self._to_utc_iso8601(request.start_date),
                columns.period_end: self._to_utc_iso8601(request.end_date),
                columns.audience_profile: snapshot.audience_report.profile.value,
                columns.total_feedbacks: snapshot.insights.total_feedbacks,
                columns.clustered_feedbacks: snapshot.insights.clustered_feedbacks,
                columns.cluster_count: len(snapshot.insights.clusters),
                columns.insights_json: insights_json,
                columns.audience_report_json: audience_report_json,
                columns.schema_version: 1,
            }
            if request.comparison_start_date is not None:
                payload[columns.comparison_start] = self._to_utc_iso8601(
                    request.comparison_start_date
                )
            if request.comparison_end_date is not None:
                payload[columns.comparison_end] = self._to_utc_iso8601(
                    request.comparison_end_date
                )
            if request.software_id is not None:
                payload[columns.software_id] = request.software_id
            if request.functionality_id is not None:
                payload[columns.functionality_id] = request.functionality_id

            _log(
                "persistence",
                "Creating the insight-analysis snapshot in Dataverse.",
                verbose=self._verbose,
            )
            with DataverseClient(
                base_url=self._base_url,
                credential=self._credential,
            ) as client:
                record_id = client.records.create(self._table_logical_name, payload)
            _log(
                "persistence",
                f"Dataverse insight-analysis snapshot created: {record_id}.",
                verbose=self._verbose,
            )
            return str(record_id)
        except Exception as error:
            _log_error(
                "dataverse",
                "insights_snapshot_save_failed",
                error,
                sensitive_values=(self._client_secret,),
            )
            raise DataverseInsightsPersistenceError(
                "The insights analysis succeeded but could not be saved to Dataverse."
            ) from error

    def latest_snapshot(self) -> FeedbackInsightsSnapshot | None:
        """Return the most recent immutable snapshot, or None when none exists."""

        try:
            columns = self._columns
            with DataverseClient(
                base_url=self._base_url,
                credential=self._credential,
            ) as client:
                records = list(
                    client.records.list(
                        self._table_logical_name,
                        select=[
                            columns.generated_at,
                            columns.source,
                            columns.insights_json,
                            columns.audience_report_json,
                        ],
                        orderby=[f"{columns.generated_at} desc"],
                        top=1,
                    )
                )
            if not records:
                return None
            record = records[0]
            return FeedbackInsightsSnapshot(
                generated_at=self._record_value(record, columns.generated_at),
                source=self._record_value(record, columns.source),
                insights=json.loads(self._record_value(record, columns.insights_json)),
                audience_report=json.loads(
                    self._record_value(record, columns.audience_report_json)
                ),
            )
        except Exception as error:
            _log_error(
                "dataverse",
                "insights_snapshot_read_failed",
                error,
                sensitive_values=(self._client_secret,),
            )
            raise DataverseInsightsPersistenceError(
                "The latest insights snapshot could not be read from Dataverse."
            ) from error
