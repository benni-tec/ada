from ada.core.models.actors import Actor, ActorKind

# There are no users yet. Everything the frontend does is attributed to this label.
WEB = Actor(kind=ActorKind.USER, name="web")
