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
