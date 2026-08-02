"""Decorator de retry com backoff exponencial.

Parâmetros vêm de config.py (MAX_RETRIES, BACKOFF_BASE_SECONDS,
BACKOFF_MAX_SECONDS) para manter um único lugar de verdade. Usado por
qualquer chamada de rede do projeto — Telegram, e futuramente o cliente
da AliExpress — já que o bot roda 24/7 sem garantia de rede estável.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from typing import Callable, TypeVar

import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


def with_retry(
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    attempt += 1
                    if attempt > config.MAX_RETRIES:
                        logger.error(
                            "%s falhou após %d tentativa(s): %s", func.__name__, attempt, exc
                        )
                        raise
                    delay = min(
                        config.BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                        config.BACKOFF_MAX_SECONDS,
                    )
                    delay *= 1 + random.uniform(0, 0.1)  # jitter de até 10%
                    logger.warning(
                        "%s falhou (tentativa %d/%d): %s — tentando de novo em %.1fs",
                        func.__name__,
                        attempt,
                        config.MAX_RETRIES,
                        exc,
                        delay,
                    )
                    time.sleep(delay)

        return wrapper

    return decorator
