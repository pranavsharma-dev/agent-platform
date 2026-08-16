import hashlib
import json
import logging

import redis.asyncio as redis

from src.config import settings

logger = logging.getLogger(__name__)

_pool: redis.Redis | None = None

CACHE_TTL_SECONDS = 3600


async def init_redis() -> None:
    global _pool
    _pool = redis.from_url(settings.redis_url, decode_responses=True)


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None


def cache_key(step_type: str, input_data: dict) -> str:
    normalized = json.dumps(input_data, sort_keys=True, separators=(",", ":"))
    raw = f"{step_type}:{normalized}"
    return f"cache:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


async def cache_get(key: str) -> dict | None:
    if _pool is None:
        return None
    try:
        raw = await _pool.get(key)
        if raw is None:
            return None
        logger.info("cache hit: %s", key[:24])
        return json.loads(raw)
    except Exception:
        logger.warning("cache read failed for %s", key[:24], exc_info=True)
        return None


async def cache_set(key: str, value: dict, ttl: int = CACHE_TTL_SECONDS) -> None:
    if _pool is None:
        return
    try:
        raw = json.dumps(value, separators=(",", ":"))
        await _pool.set(key, raw, ex=ttl)
        logger.info("cache set: %s (ttl=%ds)", key[:24], ttl)
    except Exception:
        logger.warning("cache write failed for %s", key[:24], exc_info=True)
