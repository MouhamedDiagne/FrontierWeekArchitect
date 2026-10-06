"""Deterministic profile-specific presentation of temporary feedback insights."""

from __future__ import annotations

from collections.abc import Callable

from .models import (
    AudienceReport,
    AudienceReportScope,
    FeedbackInsightsResult,
    FeedbackType,
    ProblemCategory,
    TemporaryFeedbackCluster,
    UserProfile,
)


_TECHNICAL_CATEGORIES = frozenset(
    {
        ProblemCategory.BUG_ERROR,
        ProblemCategory.PERFORMANCE_SLOWDOWN,
        ProblemCategory.AVAILABILITY_RELIABILITY,
        ProblemCategory.ACCESS_AUTHENTICATION,
        ProblemCategory.DATA_QUALITY_REPORTING,
        ProblemCategory.INTEGRATION,
        ProblemCategory.SECURITY_PRIVACY,
    }
)
_MARKETING_TYPES = frozenset(
    {
        FeedbackType.POSITIVE_FEEDBACK,
        FeedbackType.FEATURE_REQUEST,
        FeedbackType.IMPROVEMENT_SUGGESTION,
    }
)
_SUPPORT_SALES_TYPES = frozenset(
    {
        FeedbackType.INFORMATION_REQUEST,
        FeedbackType.ISSUE_REPORT,
        FeedbackType.FEATURE_REQUEST,
        FeedbackType.IMPROVEMENT_SUGGESTION,
    }
)
_SUPPORT_SALES_CATEGORIES = frozenset(
    {
        ProblemCategory.USABILITY_UX,
        ProblemCategory.DOCUMENTATION_INFORMATION,
        ProblemCategory.SUPPORT_EXPERIENCE,
        ProblemCategory.ACCESS_AUTHENTICATION,
    }
)


def _cluster_sort_key(cluster: TemporaryFeedbackCluster) -> tuple[float, str]:
    return (-cluster.priority.score, cluster.temporary_id)


def _is_clustered(cluster: TemporaryFeedbackCluster) -> bool:
    return cluster.status == "clustered"


def _it_candidate(cluster: TemporaryFeedbackCluster) -> bool:
    return (
        cluster.feedback_type is FeedbackType.ISSUE_REPORT
        and cluster.dominant_problem_category in _TECHNICAL_CATEGORIES
    )


def _marketing_candidate(cluster: TemporaryFeedbackCluster) -> bool:
    return cluster.feedback_type in _MARKETING_TYPES


def _support_sales_candidate(cluster: TemporaryFeedbackCluster) -> bool:
    return (
        cluster.feedback_type in _SUPPORT_SALES_TYPES
        or cluster.dominant_problem_category in _SUPPORT_SALES_CATEGORIES
    )


_PROFILE_RULES: dict[
    UserProfile,
    tuple[str, Callable[[TemporaryFeedbackCluster], bool], tuple[str, ...]],
] = {
    UserProfile.MARKETING: (
        "Expérience perçue, opportunités produit et signaux de valorisation client.",
        _marketing_candidate,
        ("review_customer_message", "validate_product_opportunity"),
    ),
    UserProfile.IT: (
        "Priorités techniques et signaux à investiguer.",
        _it_candidate,
        ("investigate", "reproduce", "check_logs"),
    ),
    UserProfile.SUPPORT_SALES: (
        "Besoins récurrents à traiter dans la relation et l'accompagnement client.",
        _support_sales_candidate,
        ("prepare_support_guidance", "review_documentation", "qualify_product_request"),
    ),
    UserProfile.MANAGEMENT: (
        "Priorités transverses, évolution des signaux et arbitrages de suivi.",
        lambda cluster: True,
        ("prioritize", "assign_owner", "review_next_cycle"),
    ),
}


class ProfiledInsightsReportBuilder:
    """Select report evidence for one audience without altering clustering facts."""

    max_priority_signals = 5
    max_positive_signals = 3
    max_watch_list_signals = 5

    @classmethod
    def build(
        cls,
        insights: FeedbackInsightsResult,
        profile: UserProfile,
    ) -> AudienceReport:
        """Create deterministic reporting guidance from an existing analysis."""

        focus, candidate_predicate, default_actions = _PROFILE_RULES[profile]
        clustered = sorted(
            (cluster for cluster in insights.clusters if _is_clustered(cluster)),
            key=_cluster_sort_key,
        )
        priority_clusters = [
            cluster for cluster in clustered if candidate_predicate(cluster)
        ][: cls.max_priority_signals]
        priority_ids = {cluster.temporary_id for cluster in priority_clusters}

        positive_clusters = [
            cluster
            for cluster in clustered
            if cluster.feedback_type is FeedbackType.POSITIVE_FEEDBACK
            and cluster.temporary_id not in priority_ids
        ][: cls.max_positive_signals]
        watch_list = sorted(
            (cluster for cluster in insights.clusters if not _is_clustered(cluster)),
            key=_cluster_sort_key,
        )[: cls.max_watch_list_signals]

        limitations = list(dict.fromkeys(insights.limitations))
        if not priority_clusters and insights.total_feedbacks:
            limitations.append(
                "Aucun cluster confirmé ne correspond directement au profil demandé."
            )

        return AudienceReport(
            profile=profile,
            scope=cls._scope(insights),
            executive_focus=focus,
            priority_signal_ids=[cluster.temporary_id for cluster in priority_clusters],
            positive_signal_ids=[cluster.temporary_id for cluster in positive_clusters],
            watch_list_ids=[cluster.temporary_id for cluster in watch_list],
            suggested_follow_up_types=list(default_actions) if priority_clusters else [],
            limitations=limitations,
        )

    @staticmethod
    def _scope(insights: FeedbackInsightsResult) -> AudienceReportScope:
        request = insights.request
        current_period = (
            f"{request.start_date.date().isoformat()} to {request.end_date.date().isoformat()}"
        )
        comparison_period = None
        if request.comparison_start_date is not None and request.comparison_end_date is not None:
            comparison_period = (
                f"{request.comparison_start_date.date().isoformat()} to "
                f"{request.comparison_end_date.date().isoformat()}"
            )
        return AudienceReportScope(
            period=current_period,
            software_id=request.software_id,
            functionality_id=request.functionality_id,
            comparison_period=comparison_period,
        )
