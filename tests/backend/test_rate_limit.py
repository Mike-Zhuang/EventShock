from pathlib import Path

import pytest

from backend.app.rate_limit import RateLimitExceeded, RateLimitRule, SlidingWindowRateLimiter


def test_sliding_window_rejects_then_recovers_with_retry_after() -> None:
    currentTime = [100.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: currentTime[0])
    rule = RateLimitRule(key="write:client", limit=2, windowSeconds=60)

    limiter.check([rule])
    limiter.check([rule])
    try:
        limiter.check([rule])
    except RateLimitExceeded as error:
        assert error.retryAfterSeconds == 60
    else:
        raise AssertionError("the third request must be rate limited")

    currentTime[0] = 160.1
    limiter.check([rule])


def test_protected_rate_limit_survives_process_restart(tmp_path: Path) -> None:
    currentTime = [1_000.0]
    databasePath = tmp_path / "rate-limit.db"
    rule = RateLimitRule(
        key="auth-login:ip:203.0.113.10",
        limit=2,
        windowSeconds=60,
        protected=True,
    )

    firstProcess = SlidingWindowRateLimiter(
        persistencePath=databasePath,
        persistentClock=lambda: currentTime[0],
    )
    firstProcess.check([rule])
    firstProcess.check([rule])

    restartedProcess = SlidingWindowRateLimiter(
        persistencePath=databasePath,
        persistentClock=lambda: currentTime[0],
    )
    with pytest.raises(RateLimitExceeded) as error:
        restartedProcess.check([rule])
    assert error.value.retryAfterSeconds == 60

    currentTime[0] = 1_060.1
    restartedProcess.check([rule])
