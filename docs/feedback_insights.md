# Temporary feedback insights

## Purpose

`analyze_feedback_insights` is a read-only agent tool for historical reporting.
It reads enriched feedback from Dataverse, creates temporary semantic clusters,
and returns structured evidence to the conversational agent. It does not alter
feedback rows, save embeddings, or create an `issue_clusters` table.

The existing feedback summary is the preferred text representation. It must be
a direct, factual reformulation of the main issue or need because it is used to
compare feedback semantically. The raw comment is only an in-memory fallback
when a usable summary is missing. In that case only, a representative example
may contain a short, locally redacted excerpt (e-mail addresses, phone numbers,
URLs and IPv4 addresses are masked; the excerpt is capped at 320 characters)
and is explicitly marked `raw_fallback`. The complete raw comment is never
returned in a cluster result.

## Configuration

Add an embedding deployment to the existing Foundry project, then configure:

```env
EMBEDDING_MODEL_DEPLOYMENT_NAME=<your-Foundry-embedding-deployment-name>
EMBEDDING_BATCH_SIZE=64

CLUSTER_MAX_COSINE_DISTANCE=0.28
CLUSTER_MIN_SIZE=2
CLUSTER_MAX_EXAMPLES=3
CLUSTER_MAX_FEEDBACKS=1000

# Optional: use the normal chat-model deployment only to word titles after
# deterministic cluster membership has been calculated.
CLUSTER_LABELING_ENABLED=false
CLUSTER_LABEL_MODEL_DEPLOYMENT_NAME=gpt-4.1-mini
```

`CLUSTER_MAX_EXAMPLES` must be between `1` and `5`. It limits the number of
representative evidence items per cluster; it does not change clustering.

`EMBEDDING_MODEL_DEPLOYMENT_NAME` is mandatory the first time historical
reporting is invoked. The embedding deployment name is the Azure/Foundry
deployment identifier, not merely a public model family name.

## Dataverse data contract

The default logical column mapping is centralized in
`DataverseFeedbackColumnMap` in `app/dataverse.py`:

| Application field | Default Dataverse column |
| --- | --- |
| feedback ID | `agil_feedbackreference` |
| raw comment | `agil_rawcomment` |
| received timestamp | `agil_receivedat` |
| software | `agil_softwareid` |
| sentiment | `agil_sentiment` |
| feedback type | `agil_feedbacktype` |
| problem category | `agil_problemcategory` |
| functionality | `agil_primaryfunctionality` |
| direct summary | `agil_feedbacksummary` |

The Dataverse application user needs `Read` access to this table, in addition
to the existing write permissions used when saving feedback. It also needs the
metadata permissions already required by the Dataverse SDK to resolve Choice
labels. The reader uses formatted Choice labels and converts them back to the
application enums; it does not hard-code environment-specific Choice numbers.

If client or segment columns are added later, pass their logical names through
`DataverseFeedbackColumnMap`. Until then, `unique_client_count` is `null`, not
zero.

## How a report is calculated

1. The agent validates the requested ISO-8601 date range and optional filters.
2. The repository retrieves only the necessary Dataverse columns, bounded by
   `CLUSTER_MAX_FEEDBACKS`.
3. Feedbacks are partitioned by software, feedback type, and problem category.
   This prevents, for example, a payment feature request from joining a payment
   incident.
4. The service creates Foundry embeddings in memory and applies deterministic
   average-linkage hierarchical clustering with cosine distance.
5. Singletons and low-quality groups remain visible with `singleton` or
   `needs_review` status.
6. If a comparison period is provided, both periods are clustered together
   before period counts and trends are calculated.
7. Priority is transparent: `volume × severity × trend × segment_weight`.
   The current implementation uses a segment weight of `1.0` because segment
   data is not yet stored.
8. The service derives bounded current-period aggregates (feedback count,
   sentiment, feedback type, problem category and top functionality
   distributions). With a comparison, it derives the same aggregates for the
   comparison period separately. These facts support explicit KPIs and avoid
   treating a two-period total as a current-period count.

Cluster membership is never decided by the title-generation model. When
`CLUSTER_LABELING_ENABLED=true`, that model only receives representative
evidence excerpts and provides a clearer title and description. Each excerpt
includes its `source` (`summary` or `raw_fallback`) so a redacted fallback is
not presented as a generated summary. If it fails, the deterministic
summary-based label remains in use.

## Audience-specific reporting

`analyze_feedback_insights` now requires an `audience_profile`: `marketing`,
`it`, `support_sales`, or `management`. The agent resolves it from the
conversation only when the requested perspective is unambiguous; otherwise it
asks the user to choose. This keeps profile selection conversational rather than
binding it to a user account at this stage.

The tool returns a wrapper with two complementary sections:

```json
{
  "insights": { "...FeedbackInsightsResult..." },
  "audience_report": { "...AudienceReport..." },
  "visualization_guide": [
    {
      "id": "priority-signals",
      "kind": "bar",
      "title": "Signaux prioritaires",
      "report_section": "executive_summary"
    }
  ]
}
```

`insights` is the complete, evidence-bound clustering result: scope, counts,
clusters, bounded representative evidence, `metrics.current`, optional
`metrics.comparison`, priority scores, data quality, and limitations. A
representative item has `evidence_text` and its source: `summary` is an
enriched reformulation; `raw_fallback` is the redacted, bounded fallback
described above. `audience_report` does not recalculate or modify any of these
facts. It deterministically selects existing cluster IDs into:

- `priority_signal_ids`: the most relevant confirmed signals for the profile;
- `positive_signal_ids`: confirmed positive signals, shown separately;
- `watch_list_ids`: singleton or `needs_review` items that require validation;
- `suggested_follow_up_types`: proposed actions only, never completed actions.

The mapping is intentionally lightweight: IT prioritizes technical incident
categories, Marketing product opportunities and positive feedback, Support/Sales
relationship and guidance needs, and Management all confirmed signals in their
existing priority order. The model turns these references into readable prose,
but must obtain all factual cluster content from `insights` and must surface the
returned limitations.

`visualization_guide` is optional presentation metadata for the conversational
model. It contains only IDs, titles, captions, legends and fixed report-section
anchors, never free-form chart code or duplicate chart data. The backend builds
the full visualisation contract deterministically. The model may place an exact
marker such as `[[visual:priority-signals]]` after the paragraph it supports;
the frontend renders only a matching backend specification.

Visualisations vary by requested profile rather than using a fixed gallery:
Marketing receives sentiment, functionality and positive-signal views; IT gets
technical priorities, categories and comparison trends; Support/Sales gets
needs, priorities and trends; Management gets priority, sentiment and trend
views. Every specification has a title, caption and legend.

## Example tool result

```json
{
  "total_feedbacks": 3,
  "clustered_feedbacks": 3,
  "clusters": [
    {
      "temporary_id": "cluster_3d0a4f0a92c4b1be",
      "title": "Échecs de paiement après vérification 3D Secure",
      "status": "clustered",
      "member_count": 3,
      "sentiment_distribution": {"negative": 3},
      "period_metrics": {
        "current_count": 2,
        "previous_count": 1,
        "absolute_change": 1,
        "relative_change": 1.0,
        "trend": "up"
      },
      "priority": {
        "score": 8.0,
        "volume": 2.0,
        "severity": 2.0,
        "trend": 2.0,
        "segment_weight": 1.0
      }
    }
  ]
}
```

The priority score ranks observed feedback signals. It does not establish a
root cause, business causality, urgency, or churn risk.
