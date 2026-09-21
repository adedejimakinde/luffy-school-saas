from django.db import connection
from django_tenants.utils import get_public_schema_name

from .guardian_signin import OPENED_BY_CODE
from .refusals import CodeSessionCannotEscalate, NoMembershipHere


class SchoolAccessMiddleware:
    """Keeps a signed-in person to the schools they may actually act at.

    On a school's own host, an authenticated user needs an **active** Membership
    there. Invited and suspended people are refused: their relationship exists,
    but it does not grant access. That rule is not spelled out below — it lives
    one step away in `User.roles_at()`, which is scoped to ACCESS_STATUSES.
    Deliberately not `.live()`, which is the wider set including invited and
    suspended.

    On the public portal host none of this applies: that is where a parent sees
    children from several schools at once, and where a login with no membership
    anywhere still has to be able to sign in.

    Sets `request.school` (None on the portal) and `request.school_roles`.

    ## A session opened by a code reaches PARENT and nothing else

    `settings.GUARDIAN_SESSION_AGE` is thirty days, and the argument written at
    that constant for why thirty is tolerable is that a lost handset exposes "a
    parent-scoped read of their own children". Nothing made that true until this
    clause: a guardian who is also a bursar is an ordinary person rather than a
    corner case — `results.tests.test_withholding.TheClaimIsNotABool` is about
    exactly her — and without it a session opened with six digits off an SMS
    carries her bursar role.

    **What that costs is specific, and worth naming rather than gesturing at.**
    BURSAR is in `card_api.CARD_VIEWING_ROLES`, so `_may_read()` answers `STAFF`
    for her and the fee gate serves her a card that is withheld from her own
    family — `TheClaimIsNotABool` asserts exactly that, as a consequence of
    "staff always see a withheld card" rather than an exception to it. BURSAR is
    also in `withholding.WITHHOLDING_ROLES`, so she can hold a card back and lift
    it again, with the append-only log naming her. Not the gradebook: a bursar is
    deliberately absent from `gradebook.MARK_ENTERING_ROLES`, which says in so
    many words that a bursar keeps the books and does not mark.

    So a session carrying `guardian_signin.OPENED_BY_CODE` gets
    `parent_scoped_credential` set on `request.user` here, at the one place
    every request to a school host passes through. **Not at the view**, which
    would make it a rule each new surface has to remember — the whole finding
    behind `results.card_api._require_servable()` is what that costs.

    **And not on `request.school_roles`, which was the first shape of this and
    would have enforced nothing.** Nothing else on the platform reads that
    attribute: `card_api._may_read()`, `gradebook.services.can_enter_marks()`
    and every other guard call `user.roles_at()` themselves. Narrowing the
    middleware's private copy would have been a restriction that looked enforced
    and was not, which is the defect class this phase keeps finding — so the
    filter lives in `User.roles_at()` and this sets the flag it reads.

    It narrows rather than refuses outright, because a guardian who is also
    staff still has a child at that school and a right to read their card. What
    she does not have is her staff powers on this credential; she gets them by
    signing in with her password, which is the point.

    **The platform-staff bypass does not apply to one of these.** That bypass
    exists so somebody operating the platform is not locked out of a school they
    hold no membership at; a six-digit code is not how they prove they are that
    person.

    This is a second reason this middleware answers 403, and it is why every
    assertion about a *feature's* 403 has to read the body rather than the
    status — see `results/tests/test_withholding.py`.

    **Both sentences below now reach the person refused — issue #122, closed.**
    They used to reach nobody: there was no `403.html`, so Django's default
    handler rendered `ERROR_PAGE_TEMPLATE` with empty `details` and discarded
    the message, and a reader saw "403 Forbidden" and nothing else.

    What the fix turns on is that these two refusals have **different
    remedies** — one is a password away from what she is asking for and the
    other is not — so the identity has to travel with the exception rather than
    be recovered from its prose. `accounts.refusals` is the two classes, and
    `accounts.views.refused()` is the handler that reads them. A template
    branching on these strings would have offered the wrong remedy the day
    somebody reworded one.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(connection, "tenant", None)
        on_portal = tenant is None or tenant.schema_name == get_public_schema_name()

        request.school = None if on_portal else tenant
        request.school_roles = frozenset()

        user = getattr(request, "user", None)
        if not on_portal and user is not None and user.is_authenticated:
            # The flag goes on **before** the roles are read, and on the user
            # object rather than beside it. `User.roles_at()` is what every
            # guard on the platform calls, so this is the one place a narrowing
            # reaches all of them; `request.school_roles` below is then the
            # narrowed set too, for free and without a second rule to keep in
            # step with the first.
            #
            # `getattr` on the session, matching the line above it:
            # SessionMiddleware runs before this one in `settings.MIDDLEWARE`
            # today, and a stack somebody has reordered should not quietly stop
            # narrowing. Absent session reads as "not a code session", which is
            # safe only because the refusal below still catches a caller left
            # with no roles at all.
            session = getattr(request, "session", None)
            user.parent_scoped_credential = (
                session is not None and session.get(OPENED_BY_CODE) is not None
            )

            request.school_roles = frozenset(user.roles_at(tenant))
            if not request.school_roles:
                if user.parent_scoped_credential:
                    # Refused whatever else this login is, including platform
                    # staff. That bypass exists so somebody operating the
                    # platform is not locked out of a school they hold no
                    # membership at; six digits off an SMS is not how they prove
                    # they are that person.
                    raise CodeSessionCannotEscalate(
                        "This session was opened with a sign-in code, which "
                        "reaches a guardian's own children and nothing else."
                    )
                if not user.is_platform_staff:
                    raise NoMembershipHere(
                        "You do not have access to this school."
                    )

        return self.get_response(request)
