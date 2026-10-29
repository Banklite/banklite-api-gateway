"""Rate limiting de ventana deslizante, en memoria (suficiente para una sola instancia)."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0) -> tuple[bool, int]:
        """Devuelve (permitido, segundos_para_reintentar)."""
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] >= window:
            q.popleft()
        if len(q) >= limit:
            return False, max(1, int(window - (now - q[0])) + 1)
        q.append(now)
        return True, 0

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()
