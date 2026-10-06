"""Provider-independent embedding access for temporary feedback clustering."""

from __future__ import annotations

from math import isfinite
from typing import Any, Protocol, Sequence

from .errors import _log_error
from .utils import _log


class EmbeddingProvider(Protocol):
    """Small interface that makes clustering independent of an embedding vendor."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one numeric vector for each input text, preserving input order."""


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot return a valid vector set."""


class FoundryEmbeddingProvider:
    """Azure Foundry/OpenAI embeddings implementation used by the live service."""

    def __init__(
        self,
        embedding_client: Any,
        deployment_name: str,
        *,
        batch_size: int = 64,
        verbose: bool = True,
    ) -> None:
        if embedding_client is None:
            raise ValueError("An OpenAI client is required for embeddings.")
        if not deployment_name or not deployment_name.strip():
            raise ValueError("EMBEDDING_MODEL_DEPLOYMENT_NAME must be configured.")
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero.")

        self._embedding_client = embedding_client
        self._deployment_name = deployment_name.strip()
        self._batch_size = batch_size
        self._verbose = verbose

    @staticmethod
    def _chunks(values: Sequence[str], size: int) -> list[Sequence[str]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    @staticmethod
    def _validate_vector(
        vector: object,
        *,
        expected_dimension: int | None,
    ) -> tuple[list[float], int]:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise EmbeddingProviderError("The embedding provider returned an empty vector.")

        try:
            normalized = [float(component) for component in vector]
        except (TypeError, ValueError) as error:
            raise EmbeddingProviderError(
                "The embedding provider returned a non-numeric vector."
            ) from error

        if not all(isfinite(component) for component in normalized):
            raise EmbeddingProviderError(
                "The embedding provider returned a non-finite vector component."
            )
        if expected_dimension is not None and len(normalized) != expected_dimension:
            raise EmbeddingProviderError(
                "The embedding provider returned vectors with inconsistent dimensions."
            )
        return normalized, len(normalized)

    @staticmethod
    def _response_item_value(item: object, name: str, default: object = None) -> Any:
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    @staticmethod
    def _response_item_index(item: object, *, fallback: int) -> int:
        value = FoundryEmbeddingProvider._response_item_value(item, "index", fallback)
        if isinstance(value, bool):
            value = int(value)
        elif isinstance(value, (int, float)):
            value = int(value)
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                return fallback
        return value

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in bounded batches without logging their contents."""

        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Embedding inputs must be non-empty strings.")

        vectors: list[list[float]] = []
        expected_dimension: int | None = None
        stage = "batch-chunking"
        try:
            batches = self._chunks(texts, self._batch_size)
            for batch_number, batch in enumerate(batches, start=1):
                _log(
                    "embeddings",
                    (
                        f"Requesting embeddings batch {batch_number}/{len(batches)} "
                        f"({len(batch)} representation(s))."
                    ),
                    verbose=self._verbose,
                )
                stage = "embedding-creation-request"
    
                response = self._embedding_client.embeddings.create(
                    model=self._deployment_name,
                    input=list(batch),
                )
                stage = "embedding-data-verification"
                response_data = getattr(response, "data", None)
                if not isinstance(response_data, (list, tuple)):
                    raise EmbeddingProviderError(
                        "The embedding provider returned no embedding data."
                    )
                if len(response_data) != len(batch):
                    raise EmbeddingProviderError(
                        "The embedding provider returned an unexpected number of vectors."
                    )

                # OpenAI-compatible APIs normally preserve order. Sorting by index
                # also handles providers that expose an explicit response index.
                stage = "embedding-ordering"
                ordered_data = sorted(
                    response_data,
                    key=lambda item: FoundryEmbeddingProvider._response_item_value(
                        item,
                        "index",
                        len(response_data),
                    ),
                )
                stage = "embedding-vectors-collection"
                for item in ordered_data:
                    vector, expected_dimension = self._validate_vector(
                        self._response_item_value(item, "embedding"),
                        expected_dimension=expected_dimension,
                    )
                    vectors.append(vector)

            if len(vectors) != len(texts):
                raise EmbeddingProviderError(
                    "The embedding provider did not preserve the input cardinality."
                )
            _log(
                "embeddings",
                f"Generated {len(vectors)} temporary feedback embedding(s).",
                verbose=self._verbose,
            )
            return vectors
        except Exception as error:
            _log_error(
                "embeddings",
                f"{stage}_failed",
                error,
                sensitive_values=tuple(texts),
            )
            if isinstance(error, EmbeddingProviderError):
                raise
            raise EmbeddingProviderError("The embedding request could not be completed.") from error
