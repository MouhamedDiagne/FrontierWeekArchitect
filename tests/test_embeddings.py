import unittest
from types import SimpleNamespace

from app.embeddings import EmbeddingProviderError, FoundryEmbeddingProvider


class FakeEmbeddingsAPI:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


class FoundryEmbeddingProviderTests(unittest.TestCase):
    def test_embeds_in_batches_and_restores_response_index_order(self):
        api = FakeEmbeddingsAPI(
            [
                SimpleNamespace(
                    data=[
                        SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                        SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                    ]
                ),
                SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.5, 0.5])]),
            ]
        )
        client = SimpleNamespace(embeddings=api)
        provider = FoundryEmbeddingProvider(
            client,
            "feedback-embeddings",
            batch_size=2,
            verbose=False,
        )

        vectors = provider.embed(["first", "second", "third"])

        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]])
        self.assertEqual([call["input"] for call in api.calls], [["first", "second"], ["third"]])
        self.assertTrue(all(call["model"] == "feedback-embeddings" for call in api.calls))

    def test_rejects_inconsistent_vector_dimensions(self):
        api = FakeEmbeddingsAPI(
            [
                SimpleNamespace(
                    data=[
                        SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                        SimpleNamespace(index=1, embedding=[0.0, 1.0, 0.0]),
                    ]
                )
            ]
        )
        provider = FoundryEmbeddingProvider(
            SimpleNamespace(embeddings=api),
            "feedback-embeddings",
            verbose=False,
        )

        with self.assertRaises(EmbeddingProviderError):
            provider.embed(["first", "second"])

    def test_requires_a_deployment_name_before_provider_calls(self):
        with self.assertRaisesRegex(ValueError, "EMBEDDING_MODEL_DEPLOYMENT_NAME"):
            FoundryEmbeddingProvider(
                SimpleNamespace(embeddings=FakeEmbeddingsAPI([])),
                "   ",
                verbose=False,
            )


if __name__ == "__main__":
    unittest.main()
