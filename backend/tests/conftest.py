import ai
import pytest


@pytest.fixture(autouse=True)
def _reset_ai_rate_limit_state():
    """_rate_limit_requests is module-level, process-lifetime state in
    ai.py by design (production relies on the sliding window naturally
    expiring, not on a reset). Tests need an explicit reset instead --
    without it, many tests reusing the same repository_id (e.g. every
    test_api.py test that imports "octocat/test-repo") would share one AI
    rate-limit bucket and spuriously 429 each other."""
    ai._rate_limit_requests.clear()
    yield
    ai._rate_limit_requests.clear()
