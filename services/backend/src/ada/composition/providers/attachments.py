from dishka import Provider, Scope, provide

from ada.core.services.attachments.service import Attachments
from ada.core.services.ports.attachments import AttachmentService


class AttachmentProvider(Provider):
    """What sessions show beside their conversation."""

    scope = Scope.REQUEST

    attachments = provide(Attachments, provides=AttachmentService)


provider = AttachmentProvider()
