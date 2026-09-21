"""Write operations on memberships.

The model enforces what Postgres can enforce. The rules that span tables live
here, so callers never have to remember them:

  * linking a child to a parent gives that parent a PARENT membership at the
    child's school, creating it if this is their first child there;
  * unlinking their last child at a school ends that membership;
  * transferring a student carries the guardians across.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    LIVE_STATUSES,
    MEMBERSHIP_GRANTING_ROLES,
    GuardianAccount,
    Guardianship,
    Membership,
    MembershipStatus,
    Relationship,
    Role,
    TransferRequest,
    TransferRequestStatus,
    TransferRoute,
    User,
)


class MembershipError(Exception):
    """A membership rule was violated."""


class AlreadyEnrolled(MembershipError):
    pass


class NotEnrolled(MembershipError):
    """There is no live enrolment to release.

    Its own type because the answer differs from `NotAStudent`: that one says
    "this is the wrong kind of membership", while this says "it is the right
    kind and it is already closed". A releasing school that sees this has
    nothing left to do; a second release would only move `ended_on`.
    """


class NotAStudent(MembershipError):
    pass


class SelfGuardianship(MembershipError):
    """A login was offered as the guardian of its own enrolment.

    Its own type rather than a bare `MembershipError`, for the reason issue #89
    gives about `assertRaises(IntegrityError)`: `MembershipError` is the *base*
    of this hierarchy, so a test that asserts it cannot tell this refusal from
    `AlreadyEnrolled`, `NotEnrolled`, `NotAStudent` or `NotPermitted`. A refusal
    worth having a rule for is worth being nameable on its own.

    Subclasses `MembershipError`, so any caller that was catching the base
    keeps catching this.
    """


class NotPermitted(MembershipError):
    """The actor has no authority to grant memberships at that school."""


#: Maps the codes `Guardianship.clean()` raises onto this module's hierarchy.
#: Keyed on the code and not the message: the message is prose that may be
#: reworded, while the code is the rule's name.
_GUARDIANSHIP_REFUSALS = {
    "not_a_student": NotAStudent,
    "self_guardian": SelfGuardianship,
}


def _raise_as_membership_error(exc):
    """Re-raise a `Guardianship` `ValidationError` in this module's own types.

    Translation at the service boundary rather than letting `ValidationError`
    out. The rule itself stays in `Guardianship.clean()` — this only restates
    *which* refusal it was in the vocabulary the rest of `services` speaks, so
    that `link_guardian()` refuses a non-student with the same `NotAStudent`
    that `release_student()` and `transfer_student()` already raise for theirs.

    Anything that is not one of the two rules — a bad `relationship` choice, an
    over-long field — is re-raised untouched. Those are not membership rules and
    dressing them as one would be the drift this function exists to prevent.
    """
    for errors in getattr(exc, "error_dict", {}).values():
        for error in errors:
            refusal = _GUARDIANSHIP_REFUSALS.get(error.code)
            if refusal is not None:
                raise refusal(error.messages[0]) from exc
    raise


def can_grant_memberships(actor, school) -> bool:
    """May `actor` hand out memberships at `school`?

    A school administrator's authority stops at their own school — an admin at
    St Mary's cannot enrol anyone at Grace Academy. Only platform staff act
    across schools.

    Access-scoped: an admin who is merely invited, or who has been suspended,
    grants nothing.
    """
    if getattr(actor, "is_platform_staff", False):
        return True
    return actor.memberships.with_access().filter(
        school=school, role__in=MEMBERSHIP_GRANTING_ROLES
    ).exists()


def _require_grant_authority(actor, school):
    if not can_grant_memberships(actor, school):
        raise NotPermitted(f"{actor} cannot grant memberships at {school}.")


@transaction.atomic
def grant_membership(user, school, role, *, status=MembershipStatus.ACTIVE, **fields):
    """Give `user` a `role` at `school`, reviving an ended membership if there is one.

    Idempotent: calling it twice returns the same row.
    """
    # `.order_by()` because `Membership.Meta.ordering` joins `schools_school`
    # and `accounts_user`, and Postgres locks a row in every joined table when
    # `FOR UPDATE` is used with a join. Without it this held an exclusive lock on
    # the School row — a row this function never writes — for the length of every
    # caller's transaction, serialising unrelated grants at the same school.
    # `(user, school, role)` is uniquely constrained, so there is at most one row
    # and no ordering to apply.
    membership = (
        Membership.objects.select_for_update()
        .order_by()
        .filter(user=user, school=school, role=role)
        .first()
    )
    if membership is None:
        return Membership.objects.create(
            user=user, school=school, role=role, status=status, **fields
        )
    if not membership.is_live:
        membership.status = status
        membership.ended_on = None
        for key, value in fields.items():
            setattr(membership, key, value)
        membership.save()
    return membership


@transaction.atomic
def enroll_student(user, school, *, reference="", **fields):
    """Enrol `user` as a student at `school`.

    A student has exactly one school, so this refuses if they are already
    enrolled somewhere else — and refuses by *naming* that school, which is what
    tells a receiving admin the child has not been released yet rather than
    leaving them to guess.

    Also the receiving half of a transfer: once the previous school has called
    `release_student()`, the old row is ended, the one-school slot is free, and
    this is an ordinary admission. Guardians are re-linked here with
    `link_guardian()`; `release_student()` leaves the old guardianship rows in
    place precisely so there is something to read them off. `transfer_student()`
    remains the both-ends-at-once version for a caller with authority at both.
    """
    existing = (
        Membership.objects.select_for_update()
        .filter(user=user, role=Role.STUDENT, status__in=LIVE_STATUSES)
        .first()
    )
    if existing is not None and existing.school_id != school.pk:
        raise AlreadyEnrolled(
            f"{user} is already enrolled at {existing.school}. Transfer them instead."
        )
    return grant_membership(user, school, Role.STUDENT, reference=reference, **fields)


@transaction.atomic
def link_guardian(
    guardian,
    student,
    *,
    relationship=Relationship.GUARDIAN,
    is_primary_contact=False,
    receives_invoices=True,
    can_collect=True,
):
    """Link a parent's login to one child.

    Also ensures the parent holds a PARENT membership at that child's school —
    this is how one login comes to span several schools: each linked child adds
    the school it belongs to.

    The two rules this used to re-state by hand now come from the one copy in
    `Guardianship.clean()`. Asked here, ahead of `grant_membership()` below, so
    that a refused link never grants the PARENT membership in the first place
    rather than granting one and relying on the rollback to take it back.

    **The membership is granted INVITED unless the guardian holds a verified
    contact channel**, which is D9's "the guardian link does not go live until
    it comes back" as a thing the code does rather than a sentence in a design
    doc. `GuardianAccount.has_verified_channel()` has existed since PR B with
    nothing reading it; this is the reader.

    INVITED rather than refusing outright, because D10's order is "create
    guardian, attach to child, enter contact channel" — the link comes *before*
    the channel, and a refusal here would make the documented flow impossible.
    INVITED is exactly the state the model already has for this: `LIVE_STATUSES`
    holds the relationship, so the child still appears on the parent's
    dashboard and still occupies whatever the relationship occupies, while
    `ACCESS_STATUSES` withholds the access. Those two predicates were kept apart
    for this class of case and this is the case.

    `grant_membership()` does not downgrade a live membership, so a guardian
    already ACTIVE at a school stays ACTIVE when a second child is linked
    there — the gate gives access, it does not take it away.

    **What this deliberately does not do is take access back.** A channel
    revoked under D11 leaves an ACTIVE membership standing, because D11's change
    flow is not built yet and half a mechanism is worse than a named gap. The
    demotion belongs with the revocation that causes it; see the note on
    `guardian_contacts.activate_guardian_links()`.
    """
    try:
        Guardianship(
            guardian=guardian,
            student=student,
            relationship=relationship,
            is_primary_contact=is_primary_contact,
            receives_invoices=receives_invoices,
            can_collect=can_collect,
        ).full_clean(exclude=None, validate_constraints=False)
    except ValidationError as exc:
        _raise_as_membership_error(exc)

    account = GuardianAccount.objects.filter(user=guardian).first()
    grant_membership(
        guardian,
        student.school,
        Role.PARENT,
        status=(
            MembershipStatus.ACTIVE
            if account is not None and account.has_verified_channel()
            else MembershipStatus.INVITED
        ),
    )

    if is_primary_contact:
        Guardianship.objects.filter(student=student, is_primary_contact=True).update(
            is_primary_contact=False
        )

    link, created = Guardianship.objects.get_or_create(
        guardian=guardian,
        student=student,
        defaults={
            "relationship": relationship,
            "is_primary_contact": is_primary_contact,
            "receives_invoices": receives_invoices,
            "can_collect": can_collect,
        },
    )
    if not created and is_primary_contact and not link.is_primary_contact:
        link.is_primary_contact = True
        link.save(update_fields=["is_primary_contact"])
    return link


def activate_guardian_links(guardian):
    """Turn every waiting PARENT membership of `guardian` live. Returns how many.

    The other half of `link_guardian()`'s gate: that one withholds access until
    a channel is verified, and this is what verifying does about it. Called from
    `guardian_contacts.confirm_verification()`, which is the one place a channel
    ever becomes verified.

    **Every school at once, because a guardian has one channel and many
    schools.** D5 gives a parent of three children at two schools one login and
    one guardian record; scoping this to a school would mean the channel proved
    at St Mary's left the same person waiting at Grace with nothing further to
    prove.

    **INVITED only, never SUSPENDED.** A suspension is somebody's decision about
    this person, and a verified channel is not an answer to it — promoting a
    suspended parent would let anyone reverse a school's decision by asking for
    a code. INVITED is the absence of a decision, which is the only thing this
    is entitled to fill in.

    **Role-scoped, because a guardian can be other things.** A teacher whose
    membership is still INVITED is waiting on an invitation, not on a phone
    number, and verifying a contact channel has nothing to say about it.
    """
    return Membership.objects.filter(
        user=guardian, role=Role.PARENT, status=MembershipStatus.INVITED
    ).update(status=MembershipStatus.ACTIVE)


def _drop_parent_access_without_children(guardian, school):
    """End `guardian`'s PARENT membership at `school` if no live child keeps it.

    A login should not retain access to a school it has no reason to reach.
    Memberships in other roles at that school are left alone — a teacher whose
    own child leaves is still a teacher.

    Read the query carefully: it asks whether any *live* guardianship remains,
    so it must run **after** whatever ended the child's membership, not before.
    Shared by `unlink_guardian()`, which removes one link, and
    `release_student()`, which ends the enrolment underneath every link at once.
    """
    still_has_children = Guardianship.objects.filter(
        guardian=guardian,
        student__school=school,
        student__status__in=LIVE_STATUSES,
    ).exists()
    if not still_has_children:
        Membership.objects.filter(
            user=guardian, school=school, role=Role.PARENT, status__in=LIVE_STATUSES
        ).update(status=MembershipStatus.ENDED)


@transaction.atomic
def unlink_guardian(guardian, student):
    """Remove a parent's link to a child.

    If that was their last child at the school, their PARENT membership there
    ends too — a login should not retain access to a school it has no reason
    to reach. Memberships in other roles at that school are left alone.
    """
    Guardianship.objects.filter(guardian=guardian, student=student).delete()
    _drop_parent_access_without_children(guardian, student.school)


@transaction.atomic
def release_student(student, *, on=None):
    """End an enrolment at the school the child is leaving. Returns the ended row.

    Half of a transfer, and the half the *releasing* school owns. The other half
    is `enroll_student()` at the receiving school. Splitting them is what lets an
    ordinary school admin move a child at all: `transfer_student_as()` needs
    authority at both ends, which in practice meant every transfer routed
    through platform staff. Each half here needs authority at one school, and
    neither school ever writes at the other — which is the property that made
    destination-only authority the wrong answer, since it would let a receiving
    school end a membership at a school it has no relationship with.

    The membership is ended, never deleted: it is the child's record of having
    been here, and the partial unique index keys off `status <> 'ended'`, so
    ending it is also what frees the one-school slot for the receiving school to
    fill.

    Guardianship rows are **kept**, still pointing at the now-ended membership.
    They are history in the same way the membership is, and they are the only
    record of who this child's guardians were — which is what the receiving
    school needs, since it has to re-link them itself (`student.guardianships`
    reaches them). What does not survive is the parents' *access*: a guardian
    with no other live child here loses their PARENT membership at this school,
    exactly as `unlink_guardian()` would have dropped it.

    Two consequences worth knowing, both of them the cost of not writing across
    schools. Between the release and the admission the child belongs to no
    school, so `student_membership()` returns `None` and they appear on no
    parent's dashboard. And nothing here records an *intent* to transfer or who
    agreed to it — a `TransferRequest` handshake would close the window and keep
    that record, and is the next step rather than something this does.
    """
    if student.role != Role.STUDENT:
        raise NotAStudent("Only a STUDENT membership can be released.")
    if not student.is_live:
        raise NotEnrolled(
            f"{student.user} is not currently enrolled at {student.school}; "
            f"that membership is {student.get_status_display().lower()}."
        )

    school = student.school
    guardians = [
        link.guardian
        for link in Guardianship.objects.filter(student=student).select_related("guardian")
    ]

    student.end(on)

    # After the end, never before: the query behind this asks whether a *live*
    # child still keeps the parent here, and the child just stopped being one.
    for guardian in guardians:
        _drop_parent_access_without_children(guardian, school)

    return student


@transaction.atomic
def transfer_student(student, to_school, *, reference=""):
    """Move a student to another school, carrying their guardians with them.

    Ends the old membership (keeping it as history), opens a new one, and
    re-links every guardian — which in turn grants them a PARENT membership at
    the new school and drops the old one if no other child keeps them there.
    """
    if student.role != Role.STUDENT:
        raise NotAStudent("Only a STUDENT membership can be transferred.")
    if student.school_id == to_school.pk:
        return student

    guardians = list(
        Guardianship.objects.filter(student=student).select_related("guardian")
    )

    # End first: the partial unique index allows only one live STUDENT row.
    student.end()

    new_membership = grant_membership(
        student.user,
        to_school,
        Role.STUDENT,
        reference=reference or student.reference,
        display_name=student.display_name,
    )

    for link in guardians:
        link_guardian(
            link.guardian,
            new_membership,
            relationship=link.relationship,
            is_primary_contact=link.is_primary_contact,
            receives_invoices=link.receives_invoices,
            can_collect=link.can_collect,
        )
        # Drop access to the old school unless another child is still there.
        unlink_guardian(link.guardian, student)

    return new_membership


# ---------------------------------------------------------------------------
# Actor-checked entry points.
#
# The functions above are primitives: they keep the data consistent but ask no
# questions about who is calling, which is what lets link_guardian() grant a
# PARENT membership on its own. Anything driven by a request should come
# through here instead, so a school administrator's reach stays inside their
# own school.
# ---------------------------------------------------------------------------


@transaction.atomic
def grant_membership_as(actor, user, school, role, **kwargs):
    _require_grant_authority(actor, school)
    return grant_membership(user, school, role, **kwargs)


@transaction.atomic
def admit_student_as(actor, school, full_name, username, *, reference="", **fields):
    """Create a child's login and enrol them, in one transaction.

    **The two halves are one act.** Creating the `User` and granting the
    STUDENT `Membership` are separate writes to separate tables, and a failure
    between them leaves an account belonging to no school — a row nothing in
    this system can reach, and one the next admission with the same handle then
    collides with. The atomic block is what makes "admit a child" mean either
    both or neither.

    **The handle is the school's, and this does not invent one.** `User.username`
    says so: "students get a school-issued handle such as STM/2026/0042". A
    generated one would be a scheme the school did not choose and would have to
    live with on every register and every card. `canonical_username()` leaves it
    alone unless it is entirely phone-shaped, which is what stops `STM-0803...`
    being rewritten into a phone number.

    **No usable password**, by `create_user(username, None)`. A young child may
    have neither an email nor a phone, so there is no channel to send a
    credential to and nothing to verify — and a password nobody chose is one
    nobody can be accountable for. `IdentifierBackend` refuses an unusable
    password at the door, so the account exists and cannot yet be signed into,
    which is the honest state for a child the school has just admitted.

    Placement is **not** here. A child enrolled and not yet in a class is a real
    state a school has — admissions in August, classes settled in September —
    and folding it in would make the two impossible to tell apart.
    """
    _require_grant_authority(actor, school)
    user = User.objects.create_user(username, None, full_name=full_name)
    return user, enroll_student(user, school, reference=reference, **fields)


@transaction.atomic
def enroll_student_as(actor, user, school, **kwargs):
    _require_grant_authority(actor, school)
    return enroll_student(user, school, **kwargs)


@transaction.atomic
def link_guardian_as(actor, guardian, student, **kwargs):
    # Authority is needed at the child's school, because linking grants the
    # parent a membership there.
    _require_grant_authority(actor, student.school)
    return link_guardian(guardian, student, **kwargs)


@transaction.atomic
def unlink_guardian_as(actor, guardian, student):
    _require_grant_authority(actor, student.school)
    return unlink_guardian(guardian, student)


@transaction.atomic
def release_student_as(actor, student):
    """The releasing school's half of a transfer. Authority at that school only.

    Deliberately takes no destination. This function cannot know where the child
    is going and must not care: the moment it accepted a `to_school` it would be
    a cross-school write wearing a one-sided signature. The receiving school
    admits them with `enroll_student_as()`, under its own authority.
    """
    _require_grant_authority(actor, student.school)
    return release_student(student)


@transaction.atomic
def transfer_student_as(actor, student, to_school, **kwargs):
    """Both halves at once, for a caller with authority at both ends.

    Kept for platform staff, and for the rare admin who genuinely holds a
    membership at both schools, because it does in one transaction what the
    two-sided path does in two — no window where the child belongs to nowhere,
    and guardians carried across rather than re-linked by hand.

    It is not the ordinary path. An admin at one school should use
    `release_student_as()`, and the receiving school `enroll_student_as()`.

    Leaves a `TransferRequest` behind, marked `SINGLE_PARTY`. Without it this
    table would log only the transfers that went through a handshake, which is
    the wrong half: the transfers with the least independent oversight — one
    person, both ends, nobody to disagree — would have been the ones with no
    record at all. The row names `actor` as both signatures and carries no side,
    because there was no second party and no first mover; it says one authority
    did this, which is what happened.
    """
    _require_grant_authority(actor, student.school)
    _require_grant_authority(actor, to_school)

    # Captured before the move: `transfer_student()` ends this row and opens a
    # new one, and the record has to point at the enrolment that was left, the
    # same as a handshake row does.
    leaving = student
    already_there = student.school_id == to_school.pk

    moved = transfer_student(student, to_school, **kwargs)
    if already_there:
        # `transfer_student()` returns the row untouched in this case. Nothing
        # happened, so nothing is recorded as having happened.
        return moved

    TransferRequest.objects.create(
        student=leaving,
        to_school=to_school,
        requested_by=actor,
        resolved_by=actor,
        resolved_at=timezone.now(),
        # No side: see TransferRoute.SINGLE_PARTY.
        requested_side=None,
        route=TransferRoute.SINGLE_PARTY,
        status=TransferRequestStatus.ACCEPTED,
        reference=moved.reference,
    )
    return moved


def parent_dashboard(guardian):
    """Every child of `guardian`, grouped by school — the one-login view.

    Returns [(school, [student memberships]), ...] ordered by school name.
    A single query against the public schema, so a parent with children at
    three schools pays the same cost as a parent with one.
    """
    children = list(guardian.children())
    grouped: dict = {}
    for child in children:
        grouped.setdefault(child.school, []).append(child)
    return sorted(grouped.items(), key=lambda pair: pair[0].name)


def school_directory(school, *, role=None):
    """Everyone at one school, optionally filtered to a single role.

    Relationship-scoped on purpose, so invited and suspended people appear
    alongside active ones. A school's own directory should show who is pending
    and who is suspended rather than hiding them — that is the roster the office
    works from. Do not narrow this to `with_access()`; access and visibility are
    different questions.
    """
    qs = Membership.objects.for_school(school).live().select_related("user")
    return qs.filter(role=role) if role else qs
