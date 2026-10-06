"""Read-only feedback insights orchestration and optional cluster labelling."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .clustering import (
    ClusteringConfig,
    cluster_feedback_records,
    feedback_representation_source,
)
from .dataverse import FeedbackReader
from .embeddings import EmbeddingProvider
from .errors import _error_was_logged, _log_error, _safe_error_detail
from .models import (
    ClusterPeriodMetrics,
    ClusterPriority,
    FeedbackInsightsDataQuality,
    FeedbackInsightsRequest,
    FeedbackInsightsResult,
    FeedbackRecordForInsights,
    TemporaryFeedbackCluster,
)
from .utils import _log


class FeedbackInsightsError(RuntimeError):
    """Raised when a requested historical feedback analysis cannot be produced."""


class ClusterLabel(BaseModel):
    """Optional wording only; it never controls cluster membership."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=400)

    @field_validator("title", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("cluster labels must not be blank")
        return normalized


class ClusterLabelProvider(Protocol):
    """Optional abstraction for naming already-calculated clusters."""

    def label_cluster(self, cluster: TemporaryFeedbackCluster) -> ClusterLabel:
        """Return a safe title and description for an existing cluster."""


class OpenAIClusterLabelProvider:
    """Use the existing Foundry model only to word labels after clustering."""

    def __init__(
        self,
        openai_client: Any,
        model_deployment_name: str,
        *,
        verbose: bool = True,
    ) -> None:
        if openai_client is None:
            raise ValueError("An OpenAI client is required for cluster labelling.")
        if not model_deployment_name or not model_deployment_name.strip():
            raise ValueError("A model deployment is required for cluster labelling.")
        self._openai_client = openai_client
        self._model_deployment_name = model_deployment_name.strip()
        self._verbose = verbose

    @staticmethod
    def _instructions() -> str:
        return """
You name an already-calculated cluster of customer feedback. Membership,
counts, sentiment, and category are authoritative and must not be changed.
Use only the supplied representative summaries; do not infer a root cause,
solution, urgency, or business impact. Do not include personal data, customer
names, raw comments, or unsupported facts.

Return French- or source-language wording that directly states the shared
feedback issue or need. Keep the title concise and the description factual.
""".strip()

    @staticmethod
    def _response_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title", "description"],
            "additionalProperties": False,
        }

    def label_cluster(self, cluster: TemporaryFeedbackCluster) -> ClusterLabel:
        if not cluster.representative_examples:
            raise ValueError("A cluster needs a safe representative summary to be labelled.")

        context = {
            "software_id": cluster.software_id,
            "feedback_type": (
                cluster.feedback_type.value if cluster.feedback_type is not None else None
            ),
            "dominant_problem_category": (
                cluster.dominant_problem_category.value
                if cluster.dominant_problem_category is not None
                else None
            ),
            "member_count": cluster.member_count,
            "representative_summaries": [
                example.feedback_summary
                for example in cluster.representative_examples
            ],
        }
        sensitive_values = tuple(context["representative_summaries"])
        try:
            _log(
                "insights",
                f"Labelling temporary cluster {cluster.temporary_id}.",
                verbose=self._verbose,
            )
            response = self._openai_client.responses.create(
                model=self._model_deployment_name,
                instructions=self._instructions(),
                input=json.dumps(context, ensure_ascii=False),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "feedback_cluster_label",
                        "strict": True,
                        "schema": self._response_schema(),
                    }
                },
                temperature=0,
                max_output_tokens=180,
            )
            response_error = getattr(response, "error", None)
            if response_error:
                raise RuntimeError(
                    "Cluster label model request failed: "
                    f"{getattr(response_error, 'message', response_error)}"
                )
            output_text = getattr(response, "output_text", None)
            if not output_text:
                raise RuntimeError("Cluster label model returned no structured result.")
            try:
                return ClusterLabel.model_validate_json(output_text)
            except ValidationError as error:
                raise RuntimeError(
                    "Cluster label model returned invalid structured output: "
                    f"{_safe_error_detail(error, sensitive_values=sensitive_values)}"
                ) from error
        except Exception as error:
            _log_error(
                "insights",
                "cluster_labelling_failed",
                error,
                sensitive_values=sensitive_values,
            )
            raise


class FeedbackInsightsService:
    """Coordinate Dataverse reading, temporary clustering, and safe labelling."""

    def __init__(
        self,
        *,
        feedback_reader: FeedbackReader,
        embedding_provider: EmbeddingProvider,
        clustering_config: ClusteringConfig,
        cluster_label_provider: ClusterLabelProvider | None = None,
        verbose: bool = True,
    ) -> None:
        self._feedback_reader = feedback_reader
        self._embedding_provider = embedding_provider
        self._clustering_config = clustering_config
        self._cluster_label_provider = cluster_label_provider
        self._verbose = verbose

    def _log(self, message: str) -> None:
        _log("insights", message, verbose=self._verbose)

    def analyze(self, request: FeedbackInsightsRequest) -> FeedbackInsightsResult:
        """Produce a temporary, evidence-bound historical analysis.

        If a comparison period is supplied, both periods are clustered together
        before counts are calculated. This gives each cluster a stable meaning
        across the comparison instead of comparing unrelated cluster runs.
        """

        stage = "request_validation"
        try:
            request = FeedbackInsightsRequest.model_validate(request)
            stage = "current_period_read"
            self._log("Reading feedback for the current reporting period.")
            current_records = self._feedback_reader.list_for_insights(
                request.current_filters()
            )

            stage = "comparison_period_read"
            previous_filters = request.comparison_filters()
            previous_records: list[FeedbackRecordForInsights] = []
            if previous_filters is not None:
                self._log("Reading feedback for the comparison reporting period.")
                previous_records = self._feedback_reader.list_for_insights(
                    previous_filters
                )

            stage = "record_validation"
            period_by_feedback_id = {
                record.feedback_id: "current" for record in current_records
            }
            for record in previous_records:
                if record.feedback_id in period_by_feedback_id:
                    raise FeedbackInsightsError(
                        "The current and comparison periods contain duplicate feedback identifiers."
                    )
                period_by_feedback_id[record.feedback_id] = "previous"

            all_records = [*current_records, *previous_records]
            if len(all_records) > self._clustering_config.max_feedbacks:
                raise FeedbackInsightsError(
                    "The requested periods exceed the configured feedback-analysis limit."
                )

            stage = "temporary_clustering"
            self._log(
                f"Creating temporary clusters from {len(all_records)} feedback record(s)."
            )
            clusters = cluster_feedback_records(
                all_records,
                embedding_provider=self._embedding_provider,
                config=self._clustering_config,
            )

            records_by_id = {record.feedback_id: record for record in all_records}
            clusters = [
                self._with_period_metrics_and_priority(
                    cluster,
                    records_by_id=records_by_id,
                    period_by_feedback_id=period_by_feedback_id,
                    has_comparison=previous_filters is not None,
                )
                for cluster in clusters
            ]

            stage = "cluster_labelling"
            clusters = self._label_clusters(clusters)
            clusters.sort(key=lambda cluster: (-cluster.priority.score, cluster.temporary_id))

            quality = self._data_quality(all_records)
            limitations = self._limitations(
                current_count=len(current_records),
                previous_count=len(previous_records),
                has_comparison=previous_filters is not None,
                quality=quality,
                clusters=clusters,
            )
            result = FeedbackInsightsResult(
                request=request,
                total_feedbacks=len(all_records),
                clustered_feedbacks=sum(
                    cluster.member_count
                    for cluster in clusters
                    if cluster.status == "clustered"
                ),
                clusters=clusters,
                data_quality=quality,
                limitations=limitations,
            )
            self._log(
                f"Temporary feedback analysis completed with {len(clusters)} cluster(s)."
            )
            return result
        except Exception as error:
            if not _error_was_logged(error):
                _log_error("insights", f"{stage}_failed", error)
            if isinstance(error, FeedbackInsightsError):
                raise
            raise FeedbackInsightsError(
                "Historical feedback analysis could not be completed."
            ) from error

    def _data_quality(
        self,
        records: list[FeedbackRecordForInsights],
    ) -> FeedbackInsightsDataQuality:
        sources = Counter(
            feedback_representation_source(record, config=self._clustering_config)
            for record in records
        )
        return FeedbackInsightsDataQuality(
            records_with_summary=sources["summary"],
            records_using_raw_fallback=sources["raw_fallback"],
            records_without_usable_representation=sources["unusable"],
        )

    def _with_period_metrics_and_priority(
        self,
        cluster: TemporaryFeedbackCluster,
        *,
        records_by_id: dict[str, FeedbackRecordForInsights],
        period_by_feedback_id: dict[str, str],
        has_comparison: bool,
    ) -> TemporaryFeedbackCluster:
        members = [records_by_id[feedback_id] for feedback_id in cluster.feedback_ids]
        current_members = [
            member
            for member in members
            if period_by_feedback_id[member.feedback_id] == "current"
        ]
        previous_members = [
            member
            for member in members
            if period_by_feedback_id[member.feedback_id] == "previous"
        ]
        period_metrics = (
            self._period_metrics(
                current_count=len(current_members),
                previous_count=len(previous_members),
            )
            if has_comparison
            else None
        )
        priority_members = current_members if has_comparison else members
        priority = self._priority(
            priority_members=priority_members,
            current_count=len(current_members),
            previous_count=len(previous_members),
            has_comparison=has_comparison,
        )
        return cluster.model_copy(
            update={"period_metrics": period_metrics, "priority": priority}
        )

    @staticmethod
    def _period_metrics(
        *,
        current_count: int,
        previous_count: int,
    ) -> ClusterPeriodMetrics:
        change = current_count - previous_count
        if previous_count == 0:
            relative_change = None
            trend = "new" if current_count > 0 else "stable"
        else:
            relative_change = round(change / previous_count, 4)
            if change > 0:
                trend = "up"
            elif change < 0:
                trend = "down"
            else:
                trend = "stable"
        return ClusterPeriodMetrics(
            current_count=current_count,
            previous_count=previous_count,
            absolute_change=change,
            relative_change=relative_change,
            trend=trend,
        )

    @staticmethod
    def _priority(
        *,
        priority_members: list[FeedbackRecordForInsights],
        current_count: int,
        previous_count: int,
        has_comparison: bool,
    ) -> ClusterPriority:
        denominator = len(priority_members)
        negative_count = sum(
            member.sentiment is not None and member.sentiment.value == "negative"
            for member in priority_members
        )
        mixed_count = sum(
            member.sentiment is not None and member.sentiment.value == "mixed"
            for member in priority_members
        )
        severity = (
            1.0 + (negative_count / denominator) + (0.5 * mixed_count / denominator)
            if denominator
            else 1.0
        )
        if has_comparison and current_count > previous_count:
            growth = (current_count - previous_count) / max(previous_count, 1)
            trend = round(1.0 + min(growth, 2.0), 4)
        else:
            trend = 1.0
        volume = float(current_count if has_comparison else denominator)
        segment_weight = 1.0
        return ClusterPriority(
            score=round(volume * severity * trend * segment_weight, 4),
            volume=volume,
            severity=round(severity, 4),
            trend=trend,
            segment_weight=segment_weight,
        )

    def _label_clusters(
        self,
        clusters: list[TemporaryFeedbackCluster],
    ) -> list[TemporaryFeedbackCluster]:
        if self._cluster_label_provider is None:
            return clusters

        labelled: list[TemporaryFeedbackCluster] = []
        for cluster in clusters:
            if cluster.status != "clustered" or not cluster.representative_examples:
                labelled.append(cluster)
                continue
            try:
                label = self._cluster_label_provider.label_cluster(cluster)
            except Exception:
                # The deterministic medoid-based title from clustering remains a
                # truthful fallback; labels must never make reporting unavailable.
                labelled.append(cluster)
                continue
            labelled.append(
                cluster.model_copy(
                    update={"title": label.title, "description": label.description}
                )
            )
        return labelled

    @staticmethod
    def _limitations(
        *,
        current_count: int,
        previous_count: int,
        has_comparison: bool,
        quality: FeedbackInsightsDataQuality,
        clusters: list[TemporaryFeedbackCluster],
    ) -> list[str]:
        limitations: list[str] = []
        if current_count == 0:
            limitations.append("Aucun feedback ne correspond à la période courante demandée.")
        if has_comparison and previous_count == 0:
            limitations.append(
                "Aucun feedback ne correspond à la période de comparaison demandée."
            )
        if quality.records_using_raw_fallback:
            limitations.append(
                "Certains clusters reposent sur un texte brut faute de résumé exploitable et doivent être vérifiés."
            )
        if quality.records_without_usable_representation:
            limitations.append(
                "Certains feedbacks sans résumé ni texte exploitable restent à examiner individuellement."
            )
        review_count = sum(cluster.status == "needs_review" for cluster in clusters)
        if review_count:
            limitations.append(
                f"{review_count} cluster(s) sont marqués à vérifier avant toute décision opérationnelle."
            )
        if any(cluster.unique_client_count is None for cluster in clusters):
            limitations.append(
                "Le nombre de clients uniques n'est pas disponible car la table ne contient pas encore cet identifiant."
            )
        return limitations
