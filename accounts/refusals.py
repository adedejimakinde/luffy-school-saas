"""The two refusals `SchoolAccessMiddleware` raises, told apart by what they are.

Both are `PermissionDenied`, both reach the same handler, and both used to be
indistinguishable once they got there. That was issue #122: the middleware
raised `PermissionDenied("This session was opened with a sign-in code…")` and
`PermissionDenied("You do not have access to this school.")`, Django's default
handler rendered `ERROR_PAGE_TEMPLATE` with empty `details`, and **both
sentences reached nobody**. The reader saw "403 Forbidden" and was told neither
what had happened nor whether anything would fix it.

## Why two classes rather than one message the template reads

The obvious repair is a `403.html` that prints `str(exception)`, and it is the
wrong one, because these two refusals have **different remedies**:

- a guardian on a code session at a school where she also teaches is one
  password away from everything she is asking for; and
- somebody with no membership at this school is not, and never will be.

A page that offered the staff door to the second person would be a false
remedy — a link that cannot work, on the screen whose whole job is saying what
to do next, which is the failure `schools.hosts.portal_host()` already refuses
to ship on the family pages.

So the remedy has to be a **property of the refusal**, and the only honest place
to hang it is the exception's type. Branching a template on the message string
would key page behaviour on prose somebody will reword — the near-enough thing
this codebase keeps finding in other clothes — and it would silently start
offering the wrong remedy the day a sentence was edited.

`a_password_fixes_it` is deliberately not "is this a code session". What the
page does with it is offer the password door, so it is named for the thing the
page is deciding, and a third refusal that a password also fixes gets it right
by setting one attribute.

## Anything else that raises `PermissionDenied` still renders

`accounts.views.refused()` treats a plain `PermissionDenied` as "refused, no
remedy, no sentence", and it prints the sentence **only** for the types below.
An arbitrary exception's `str()` is written for whoever debugs it, and error
pages are not where a codebase should start trusting that.
"""

from django.core.exceptions import PermissionDenied


class SchoolAccessRefused(PermissionDenied):
    """A refusal by `SchoolAccessMiddleware`, carrying its own remedy.

    The base exists so `accounts.views.refused()` has one type to ask about
    before it prints anybody's sentence to a reader, rather than a tuple of
    concrete classes that a third refusal could be added without joining.
    """

    #: Whether signing in with a password is what fixes this. Read by
    #: `accounts.views.refused()` to decide whether the page offers the staff
    #: door — so it is False by default, and a refusal that does not know
    #: cannot accidentally promise a remedy.
    a_password_fixes_it = False


class NoMembershipHere(SchoolAccessRefused):
    """Signed in, on a school's host, holding no active role at that school.

    **A password fixes nothing here**, which is the whole reason this is a
    separate class. The person is already signed in with one; what they do not
    have is a membership, and only the school can give them that. Offering the
    staff door would be sending somebody to type a password they have already
    typed.
    """

    a_password_fixes_it = False


class CodeSessionCannotEscalate(SchoolAccessRefused):
    """A guardian's code session, reaching for something only staff may have.

    `settings.GUARDIAN_SESSION_AGE` is thirty days on the argument that a lost
    handset exposes "a parent-scoped read of their own children", and
    `User.roles_at()` is what makes that true: on a session opened with six
    digits off an SMS it narrows to PARENT. At a school where this person only
    teaches, that leaves nothing, and she is refused here.

    **A password fixes it exactly**, and the constant says so in so many words
    — "She gets her staff powers again by signing in with her password." Until
    `/staff-sign-in/` landed there was nowhere to do that; until this class
    there was no way for the refusal to say so.
    """

    a_password_fixes_it = True


__all__ = [
    "SchoolAccessRefused",
    "NoMembershipHere",
    "CodeSessionCannotEscalate",
]
