from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ada.core.ports.system import TaskQueue

HEARTBEAT_KEY = "ada:worker:heartbeat"
# The scheduler beats every minute, so a missing key means the worker or scheduler is down.
HEARTBEAT_TTL = timedelta(minutes=3)


class ValkeyTaskQueue(TaskQueue):
    def __init__(self, valkey: Redis) -> None:
        self.valkey = valkey

    async def is_reachable(self) -> bool:
        try:
            await self.valkey.ping()
        except RedisError, OSError:
            return False
        return True

    async def record_heartbeat(self) -> None:
        await self.valkey.set(HEARTBEAT_KEY, datetime.now(UTC).isoformat(), ex=HEARTBEAT_TTL)

    async def worker_is_alive(self) -> bool:
        try:
            return await self.valkey.exists(HEARTBEAT_KEY) > 0
        except RedisError, OSError:
            return False
