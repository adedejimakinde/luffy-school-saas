"""What the website's services refuse with. Each says which rule refused, in words for a person."""


class SiteError(Exception):
    """A change to a school's website could not be made as asked. Nothing was written."""


class SiteRefused(SiteError):
    """Well formed, and the site's own rules say no: data it will not keep, a step out of order."""


class NotAllowed(SiteError):
    """This login may not do this at this school."""


class NotAllowedToEdit(NotAllowed):
    """Not the principal, nor an administrator the principal has let edit."""


class NotAllowedToPublish(NotAllowed):
    """Publishing, rolling back, the theme and the delegation are the principal's."""


class NotAllowedToReadLog(NotAllowed):
    """The publish log is the principal's and the administrator's."""


class StaleDraft(SiteError):
    """Somebody changed this part of the draft since the caller read it."""


__all__ = [
    "NotAllowed",
    "NotAllowedToEdit",
    "NotAllowedToPublish",
    "NotAllowedToReadLog",
    "SiteError",
    "SiteRefused",
    "StaleDraft",
]
