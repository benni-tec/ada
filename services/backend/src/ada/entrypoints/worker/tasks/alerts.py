import logging
from uuid import UUID

from dishka.integrations.taskiq import FromDishka

from ada.core.ports.tasks import TaskDispatcher
from ada.core.services.ports.alerts import AlertService
from ada.entrypoints.worker.registry import task

logger = logging.getLogger(__name__)


@task()
async def check_alert_rule(rule_id: str, *, service: FromDishka[AlertService]) -> None:
    """Queued for each rule that is due. Checks the rule on a new run of its measure,
    which opens, keeps and resolves its alerts and announces the changes."""
    try:
        rule = await service.get_rule(UUID(rule_id))
        if not rule.enabled:
            # Disabled after it was queued.
            return
        await service.check(rule.id)
    except Exception:
        # A check writes alerts only after everything that can fail has run, so a failed
        # one leaves the alerts as they were; its run, if it started, published
        # run.failed. The rule stays due and the next tick queues it again. Ending
        # normally keeps the worker's log to one entry and commits what was recorded,
        # e.g. a failed source refresh.
        logger.exception("Checking alert rule %s failed", rule_id)


@task(schedule=[{"cron": "* * * * *"}])
async def check_due_alert_rules(
    service: FromDishka[AlertService], dispatcher: FromDishka[TaskDispatcher]
) -> None:
    """Runs every minute and queues a check for each rule that is due: its interval has
    passed, or, for a rule without one, its measure's data changed. Queued rather than run
    here, so one slow check holds up neither the others nor the next tick."""
    for rule in await service.due():
        try:
            await dispatcher.check_alert_rule(rule.id)
        except Exception:
            # The rule is still due on the next tick, which queues it again.
            logger.exception("Queueing a check of alert rule %s failed", rule.id)
