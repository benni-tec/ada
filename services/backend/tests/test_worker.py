from ada.config import Settings
from ada.entrypoints.worker import create_broker
from ada.entrypoints.worker.factory import create_scheduler


def test_heartbeat_task_is_registered_and_scheduled(unreachable_settings: Settings) -> None:
    broker = create_broker(unreachable_settings, in_memory=True)
    name = "ada.entrypoints.worker.tasks:record_heartbeat"
    task = broker.find_task(name)
    assert task is not None
    assert task.labels["schedule"] == [{"cron": "* * * * *"}]
    assert create_scheduler(broker).sources
