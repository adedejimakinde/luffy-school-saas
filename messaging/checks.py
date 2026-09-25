"""The two ways a deploy can be wrong about messaging. `docs/messaging.md` D2.

`E001` is not `deploy=True`, unlike `accounts.E001`: the fake in production is
not a question of hostnames that only shows on the second host, it is codes
stored in the clear from the first request. So it runs wherever checks run.

`W001` is `deploy=True`, because a development machine with no provider is
normal. It is silenced in `settings.py` until a real provider exists (M6), with
the reason written there.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

FAKE = "messaging.fake.FakeProvider"


@register(Tags.security)
def the_fake_is_for_development_only(app_configs, **kwargs):
    providers = getattr(settings, "MESSAGING_PROVIDERS", None) or {}
    faked = sorted(kind for kind, path in providers.items() if path == FAKE)
    if not faked or settings.DEBUG:
        return []
    return [
        Error(
            f"The fake message provider is configured for {', '.join(faked)} with "
            f"DEBUG off. It sends nothing, and it stores every sign-in code it is "
            f"given in the clear.",
            hint=(
                "Name a real provider in MESSAGING_EMAIL_PROVIDER and "
                "MESSAGING_PHONE_PROVIDER, or leave them empty so that sends are "
                "refused rather than faked."
            ),
            id="messaging.E001",
        )
    ]


@register(Tags.security, deploy=True)
def guardians_need_a_phone_provider(app_configs, **kwargs):
    providers = getattr(settings, "MESSAGING_PROVIDERS", None) or {}
    if providers.get("phone"):
        return []
    return [
        Warning(
            "No phone message provider is configured, so no code can be sent to a "
            "phone: a guardian reached by phone can neither prove their number "
            "nor sign in.",
            hint="Set MESSAGING_PHONE_PROVIDER.",
            id="messaging.W001",
        )
    ]
