def _log(step: str, message: str, *, verbose: bool) -> None:
    """Print progress without exposing feedback text, secrets, or full payloads."""
    if verbose:
        print(f"[feedback-agent][{step}] {message}", flush=True)
