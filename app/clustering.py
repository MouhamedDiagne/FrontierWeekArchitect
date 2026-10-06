"""Temporary, deterministic clustering of enriched customer feedback.

This module deliberately has no persistence concerns.  It receives records that
have already been read from Dataverse, creates embeddings only in memory, and
returns clusters that are valid for the current request only.

The clustering implementation uses average-linkage hierarchical clustering with
cosine distance.  It is implemented with the standard library so that the core
domain behaviour does not depend on a data-science package at runtime.  The
embedding provider remains injected, which keeps the module testable and avoids
coupling it to a specific Foundry deployment.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite, sqrt
from typing import TYPE_CHECKING, Iterable, Sequence

from .models import (
    ClusterExample,
    ClusterPriority,
    FeedbackRecordForInsights,
    FeedbackType,
    ProblemCategory,
    TemporaryFeedbackCluster,
)

if TYPE_CHECKING:
    from .embeddings import EmbeddingProvider


class ClusteringConfigurationError(ValueError):
    """Raised when a clustering setting cannot produce a safe result."""


class EmbeddingResultError(RuntimeError):
    """Raised when an embedding provider returns unusable vectors."""


@dataclass(frozen=True)
class ClusteringConfig:
    """Settings governing an on-demand clustering run.

    ``max_cosine_distance`` is the largest average cosine distance accepted
    when two provisional clusters are merged.  Lower values create stricter,
    smaller groups.  It is deliberately configuration rather than a hard-coded
    business rule because it must be calibrated with real feedback samples.
    """

    max_cosine_distance: float = 0.28
    min_cluster_size: int = 2
    max_examples: int = 3
    max_feedbacks: int = 1_000
    minimum_representation_length: int = 8
    review_confidence_threshold: float = 0.60

    def __post_init__(self) -> None:
        if not 0.0 <= self.max_cosine_distance <= 2.0:
            raise ClusteringConfigurationError(
                "max_cosine_distance must be between 0.0 and 2.0."
            )
        if self.min_cluster_size < 2:
            raise ClusteringConfigurationError("min_cluster_size must be at least 2.")
        if self.max_examples < 1:
            raise ClusteringConfigurationError("max_examples must be at least 1.")
        if self.max_feedbacks < 1:
            raise ClusteringConfigurationError("max_feedbacks must be at least 1.")
        if self.minimum_representation_length < 1:
            raise ClusteringConfigurationError(
                "minimum_representation_length must be at least 1."
            )
        if not 0.0 <= self.review_confidence_threshold <= 1.0:
            raise ClusteringConfigurationError(
                "review_confidence_threshold must be between 0.0 and 1.0."
            )


@dataclass(frozen=True)
class _PreparedFeedback:
    """Internal feedback state used during one clustering request only."""

    record: FeedbackRecordForInsights
    representation: str | None
    safe_summary: str | None


_UNCLASSIFIED = "unclassified"
_GENERIC_SUMMARIES = frozenset(
    {
        "n/a",
        "na",
        "none",
        "no summary",
        "sans objet",
        "aucun",
        "feedback",
        "probleme",
        "problème",
    }
)


def build_feedback_representation(
    record: FeedbackRecordForInsights,
    *,
    config: ClusteringConfig | None = None,
) -> str | None:
    """Build the text sent to the embedding provider for one feedback.

    A clear enriched summary is always preferred.  The raw comment is used only
    when that summary is missing or too vague, and remains in memory: raw text
    is never returned in a ``TemporaryFeedbackCluster``.
    """

    effective_config = config or ClusteringConfig()
    summary = _usable_text(
        record.feedback_summary,
        minimum_length=effective_config.minimum_representation_length,
    )
    source_text = summary or _usable_text(
        record.raw_comment,
        minimum_length=effective_config.minimum_representation_length,
    )
    if source_text is None:
        return None

    parts: list[str] = []
    functionality = (
        record.primary_functionality_name or record.primary_functionality
    )
    if functionality:
        parts.append(f"Functionality: {functionality.strip()}")
    if record.feedback_type is not None:
        parts.append(f"Feedback type: {record.feedback_type.value}")
    if record.problem_category is not None:
        parts.append(f"Problem category: {record.problem_category.value}")
    parts.append(f"Summary: {source_text}")
    return "\n".join(parts)


def feedback_representation_source(
    record: FeedbackRecordForInsights,
    *,
    config: ClusteringConfig | None = None,
) -> str:
    """Return the non-sensitive source selected for one representation.

    The return value lets the orchestration layer report data quality without
    exposing a raw fallback comment in an insight result.
    """

    effective_config = config or ClusteringConfig()
    if _usable_text(
        record.feedback_summary,
        minimum_length=effective_config.minimum_representation_length,
    ) is not None:
        return "summary"
    if _usable_text(
        record.raw_comment,
        minimum_length=effective_config.minimum_representation_length,
    ) is not None:
        return "raw_fallback"
    return "unusable"


def cluster_feedback_records(
    records: Sequence[FeedbackRecordForInsights],
    *,
    embedding_provider: "EmbeddingProvider",
    config: ClusteringConfig | None = None,
) -> list[TemporaryFeedbackCluster]:
    """Create temporary clusters from already enriched feedback records.

    Feedback is first partitioned by product, feedback type and problem category
    before semantic comparison.  This is a deliberately conservative rule: a
    feature request about payment therefore cannot be merged with a payment
    incident merely because their wording is similar.

    The result is deterministic for a deterministic embedding provider.  It is
    sorted by its temporary identifier so downstream reporting has stable output.
    """

    effective_config = config or ClusteringConfig()
    ordered_records = sorted(records, key=lambda item: item.feedback_id)
    _validate_records(ordered_records, effective_config)

    prepared = [
        _PreparedFeedback(
            record=record,
            representation=build_feedback_representation(record, config=effective_config),
            safe_summary=_usable_text(
                record.feedback_summary,
                minimum_length=effective_config.minimum_representation_length,
            ),
        )
        for record in ordered_records
    ]

    usable_positions = [
        position
        for position, item in enumerate(prepared)
        if item.representation is not None
    ]
    vectors_by_position: dict[int, tuple[float, ...]] = {}
    if usable_positions:
        vectors = embedding_provider.embed(
            [prepared[position].representation for position in usable_positions]
        )
        validated_vectors = _validate_embedding_vectors(vectors, len(usable_positions))
        vectors_by_position = dict(zip(usable_positions, validated_vectors))

    clusters: list[TemporaryFeedbackCluster] = []

    # Records with neither a usable summary nor a usable raw fallback must not be
    # forced into an invented semantic group.
    for position, item in enumerate(prepared):
        if item.representation is None:
            clusters.append(
                _make_cluster(
                    (position,),
                    prepared=prepared,
                    similarities={},
                    config=effective_config,
                    force_review=True,
                )
            )

    partitions: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for position in usable_positions:
        record = prepared[position].record
        partitions[_partition_key(record)].append(position)

    for positions in partitions.values():
        similarities = _build_similarity_map(positions, vectors_by_position)
        for member_positions in _average_linkage_clusters(
            positions,
            similarities=similarities,
            max_cosine_distance=effective_config.max_cosine_distance,
        ):
            if len(member_positions) < effective_config.min_cluster_size:
                for position in member_positions:
                    clusters.append(
                        _make_cluster(
                            (position,),
                            prepared=prepared,
                            similarities=similarities,
                            config=effective_config,
                        )
                    )
                continue

            clusters.append(
                _make_cluster(
                    member_positions,
                    prepared=prepared,
                    similarities=similarities,
                    config=effective_config,
                )
            )

    return sorted(clusters, key=lambda cluster: cluster.temporary_id)


# A concise alias makes the public operation easy to discover while preserving a
# name that makes its expected record type explicit for service-layer callers.
cluster_feedbacks = cluster_feedback_records


def _validate_records(
    records: Sequence[FeedbackRecordForInsights],
    config: ClusteringConfig,
) -> None:
    if len(records) > config.max_feedbacks:
        raise ClusteringConfigurationError(
            f"A clustering request can contain at most {config.max_feedbacks} feedbacks."
        )

    feedback_ids = [record.feedback_id for record in records]
    if len(feedback_ids) != len(set(feedback_ids)):
        raise ClusteringConfigurationError(
            "Feedback identifiers must be unique within one clustering request."
        )


def _partition_key(record: FeedbackRecordForInsights) -> tuple[str, str, str]:
    """Return the conservative compatibility boundary for semantic grouping."""

    category = (
        record.problem_category.value
        if record.problem_category is not None
        else _UNCLASSIFIED
    )
    feedback_type = (
        record.feedback_type.value
        if record.feedback_type is not None
        else _UNCLASSIFIED
    )
    return (record.software_id, feedback_type, category)


def _usable_text(value: str | None, *, minimum_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if len(normalized) < minimum_length:
        return None
    if normalized.casefold() in _GENERIC_SUMMARIES:
        return None
    return normalized


def _validate_embedding_vectors(
    vectors: Sequence[Sequence[float]],
    expected_count: int,
) -> list[tuple[float, ...]]:
    if len(vectors) != expected_count:
        raise EmbeddingResultError(
            "The embedding provider returned a different number of vectors than texts."
        )

    validated: list[tuple[float, ...]] = []
    expected_dimension: int | None = None
    for vector in vectors:
        if isinstance(vector, (str, bytes)):
            raise EmbeddingResultError(
                "The embedding provider returned a non-numeric vector."
            )
        try:
            normalized = tuple(float(value) for value in vector)
        except (TypeError, ValueError) as error:
            raise EmbeddingResultError("The embedding provider returned a non-numeric vector.") from error

        if not normalized or not all(isfinite(value) for value in normalized):
            raise EmbeddingResultError(
                "The embedding provider returned an empty or non-finite vector."
            )
        if _norm(normalized) == 0:
            raise EmbeddingResultError("The embedding provider returned a zero vector.")
        if expected_dimension is None:
            expected_dimension = len(normalized)
        elif len(normalized) != expected_dimension:
            raise EmbeddingResultError(
                "The embedding provider returned vectors with inconsistent dimensions."
            )
        validated.append(normalized)
    return validated


def _build_similarity_map(
    positions: Iterable[int],
    vectors_by_position: dict[int, tuple[float, ...]],
) -> dict[tuple[int, int], float]:
    similarities: dict[tuple[int, int], float] = {}
    for left, right in _pairs(sorted(positions)):
        similarities[(left, right)] = _cosine_similarity(
            vectors_by_position[left],
            vectors_by_position[right],
        )
    return similarities


def _average_linkage_clusters(
    positions: Sequence[int],
    *,
    similarities: dict[tuple[int, int], float],
    max_cosine_distance: float,
) -> list[tuple[int, ...]]:
    """Merge the nearest groups until their average distance exceeds the limit."""

    groups = [tuple([position]) for position in sorted(positions)]
    while len(groups) > 1:
        best: tuple[float, tuple[int, ...], tuple[int, ...]] | None = None
        for left_index, right_index in _pairs(range(len(groups))):
            left = groups[left_index]
            right = groups[right_index]
            distance = _average_distance(left, right, similarities)
            candidate = (distance, left, right)
            if best is None or candidate < best:
                best = candidate

        if best is None or best[0] > max_cosine_distance:
            break

        _, left, right = best
        groups.remove(left)
        groups.remove(right)
        groups.append(tuple(sorted((*left, *right))))
        groups.sort()

    return groups


def _average_distance(
    left: Sequence[int],
    right: Sequence[int],
    similarities: dict[tuple[int, int], float],
) -> float:
    distances = [1.0 - _similarity(first, second, similarities) for first in left for second in right]
    return sum(distances) / len(distances)


def _make_cluster(
    positions: Sequence[int],
    *,
    prepared: Sequence[_PreparedFeedback],
    similarities: dict[tuple[int, int], float],
    config: ClusteringConfig,
    force_review: bool = False,
) -> TemporaryFeedbackCluster:
    ordered_positions = tuple(sorted(positions))
    members = [prepared[position] for position in ordered_positions]
    average_similarity = _average_pairwise_similarity(ordered_positions, similarities)
    medoid_position = _medoid_position(ordered_positions, prepared, similarities)
    safe_summary_coverage = sum(member.safe_summary is not None for member in members) / len(members)
    has_feedback_type_for_every_member = all(
        member.record.feedback_type is not None for member in members
    )
    confidence = _confidence(
        average_similarity=average_similarity,
        safe_summary_coverage=safe_summary_coverage,
        member_count=len(members),
    )

    if (
        force_review
        or safe_summary_coverage < 1.0
        or not has_feedback_type_for_every_member
    ):
        status = "needs_review"
    elif len(members) == 1:
        status = "singleton"
    elif confidence < config.review_confidence_threshold:
        status = "needs_review"
    else:
        status = "clustered"

    feedback_ids = sorted(member.record.feedback_id for member in members)
    medoid_summary = prepared[medoid_position].safe_summary
    title = medoid_summary or _first_safe_summary(members) or "Feedback à examiner"
    description = _cluster_description(member_count=len(members), status=status)

    return TemporaryFeedbackCluster(
        temporary_id=_temporary_id(feedback_ids),
        title=title,
        description=description,
        status=status,
        software_id=members[0].record.software_id,
        feedback_type=_dominant_feedback_type(members),
        dominant_problem_category=_dominant_problem_category(members),
        feedback_ids=feedback_ids,
        member_count=len(members),
        unique_client_count=_unique_client_count(members),
        functionality_breakdown=_breakdown(
            (
                member.record.primary_functionality_name
                or member.record.primary_functionality
            )
            for member in members
        ),
        problem_category_breakdown=_breakdown(
            member.record.problem_category.value
            if member.record.problem_category is not None
            else None
            for member in members
        ),
        sentiment_distribution=_breakdown(
            member.record.sentiment.value
            if member.record.sentiment is not None
            else None
            for member in members
        ),
        first_occurrence=min(member.record.received_at for member in members),
        last_occurrence=max(member.record.received_at for member in members),
        representative_examples=_representative_examples(
            ordered_positions,
            prepared=prepared,
            medoid_position=medoid_position,
            similarities=similarities,
            max_examples=config.max_examples,
        ),
        average_similarity=average_similarity,
        confidence=confidence,
        priority=_priority(members),
    )


def _average_pairwise_similarity(
    positions: Sequence[int],
    similarities: dict[tuple[int, int], float],
) -> float | None:
    pairs = list(_pairs(positions))
    if not pairs:
        return None
    return sum(_similarity(left, right, similarities) for left, right in pairs) / len(pairs)


def _medoid_position(
    positions: Sequence[int],
    prepared: Sequence[_PreparedFeedback],
    similarities: dict[tuple[int, int], float],
) -> int:
    if len(positions) == 1:
        return positions[0]

    def sort_key(position: int) -> tuple[float, str]:
        others = [other for other in positions if other != position]
        mean_similarity = sum(
            _similarity(position, other, similarities) for other in others
        ) / len(others)
        # Negation keeps the deterministic feedback identifier as the tie-breaker.
        return (-mean_similarity, prepared[position].record.feedback_id)

    return min(positions, key=sort_key)


def _representative_examples(
    positions: Sequence[int],
    *,
    prepared: Sequence[_PreparedFeedback],
    medoid_position: int,
    similarities: dict[tuple[int, int], float],
    max_examples: int,
) -> list[ClusterExample]:
    sortable: list[tuple[float, str, int]] = []
    for position in positions:
        summary = prepared[position].safe_summary
        if summary is None:
            continue
        similarity = (
            None
            if position == medoid_position and len(positions) == 1
            else _similarity(position, medoid_position, similarities)
        )
        sortable.append(
            (
                -(similarity if similarity is not None else 1.0),
                prepared[position].record.feedback_id,
                position,
            )
        )

    examples: list[ClusterExample] = []
    for _, _, position in sorted(sortable)[:max_examples]:
        record = prepared[position].record
        examples.append(
            ClusterExample(
                feedback_id=record.feedback_id,
                feedback_summary=prepared[position].safe_summary or "",
                received_at=record.received_at,
                similarity_to_representative=(
                    None
                    if position == medoid_position and len(positions) == 1
                    else _similarity(position, medoid_position, similarities)
                ),
            )
        )
    return examples


def _confidence(
    *,
    average_similarity: float | None,
    safe_summary_coverage: float,
    member_count: int,
) -> float:
    if member_count == 1:
        # A single feedback cannot corroborate a common issue, even when its
        # enrichment is complete.
        return round(0.5 * safe_summary_coverage, 4)
    cohesion = ((average_similarity or -1.0) + 1.0) / 2.0
    return round(max(0.0, min(1.0, cohesion * safe_summary_coverage)), 4)


def _priority(members: Sequence[_PreparedFeedback]) -> ClusterPriority:
    total = len(members)
    sentiments = Counter(
        member.record.sentiment.value
        for member in members
        if member.record.sentiment is not None
    )
    negative_ratio = sentiments.get("negative", 0) / total
    mixed_ratio = sentiments.get("mixed", 0) / total
    severity = 1.0 + negative_ratio + (0.5 * mixed_ratio)
    volume = float(total)
    trend = 1.0
    segment_weight = 1.0
    return ClusterPriority(
        score=round(volume * severity * trend * segment_weight, 4),
        volume=volume,
        severity=round(severity, 4),
        trend=trend,
        segment_weight=segment_weight,
    )


def _breakdown(values: Iterable[str | None]) -> dict[str, int]:
    counter = Counter(value.strip() if value and value.strip() else _UNCLASSIFIED for value in values)
    return dict(sorted(counter.items()))


def _dominant_feedback_type(
    members: Sequence[_PreparedFeedback],
) -> FeedbackType | None:
    values = [
        member.record.feedback_type
        for member in members
        if member.record.feedback_type is not None
    ]
    if not values:
        return None
    counts = Counter(values)
    return min(counts, key=lambda value: (-counts[value], value.value))


def _dominant_problem_category(
    members: Sequence[_PreparedFeedback],
) -> ProblemCategory | None:
    values = [
        member.record.problem_category
        for member in members
        if member.record.problem_category is not None
    ]
    if not values:
        return None
    counts = Counter(values)
    return min(counts, key=lambda value: (-counts[value], value.value))


def _unique_client_count(members: Sequence[_PreparedFeedback]) -> int | None:
    client_ids = {
        member.record.client_id.strip()
        for member in members
        if member.record.client_id and member.record.client_id.strip()
    }
    return len(client_ids) if client_ids else None


def _first_safe_summary(members: Sequence[_PreparedFeedback]) -> str | None:
    for member in members:
        if member.safe_summary is not None:
            return member.safe_summary
    return None


def _cluster_description(*, member_count: int, status: str) -> str:
    if status == "singleton":
        return "Un feedback isolé, sans signal similaire confirmé."
    if status == "needs_review":
        return f"Groupe provisoire de {member_count} feedbacks à vérifier."
    return f"Groupe temporaire de {member_count} feedbacks sémantiquement similaires."


def _temporary_id(feedback_ids: Sequence[str]) -> str:
    payload = "\x1f".join(sorted(feedback_ids)).encode("utf-8")
    return f"cluster_{sha256(payload).hexdigest()[:16]}"


def _similarity(
    left: int,
    right: int,
    similarities: dict[tuple[int, int], float],
) -> float:
    if left == right:
        return 1.0
    key = (left, right) if left < right else (right, left)
    return similarities[key]


def _pairs(values: Iterable[int]) -> Iterable[tuple[int, int]]:
    ordered = list(values)
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            yield left, right


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(first * second for first, second in zip(left, right))
    denominator = _norm(left) * _norm(right)
    similarity = numerator / denominator
    # Floating point arithmetic can exceed the mathematical bounds by a tiny
    # amount; clamp it before distance and confidence calculations.
    return max(-1.0, min(1.0, similarity))


def _norm(vector: Sequence[float]) -> float:
    return sqrt(sum(value * value for value in vector))
