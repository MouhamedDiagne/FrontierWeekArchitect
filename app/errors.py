class FeedbackAnalysisAgentError(Exception):
    """Base error for the sentiment agent."""


class ConfigurationError(FeedbackAnalysisAgentError):
    pass


class ProviderRequestError(FeedbackAnalysisAgentError):
    pass


class InvalidModelResponseError(FeedbackAnalysisAgentError):
    pass