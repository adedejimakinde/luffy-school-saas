"""Identity and school access.

Everything here lives in the public schema, once for the whole platform.

The shape to keep in mind:

    User            a person, one login, no role of its own
    Membership      (person, school, role) — the only place a role exists
    Guardianship    (parent user, a child's STUDENT membership)
    TransferRequest one school's proposal to move a child to another, and the
                    other school's answer — two signatures, one transfer
    GuardianAccount one guardian, once, and the opaque handle for them
    GuardianContact the channel they are reached and verified on, append-only

A person is not "a teacher"; a person *is a teacher at a school*, and may
simultaneously be a parent at that school and at two others. So role is an
attribute of the relationship, never of the user.
"""

import uuid
from datetime import timedelta

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, models, transaction
from django.db.models import F, Q
from django.utils import timezone

from .identifiers import canonical_username, normalize_email, normalize_phone, try_normalize_phone


class Role(models.TextChoices):
    """Every role that gets a login. There is no flat "staff" role."""

    ADMIN = "admin", "School administrator"
    PRINCIPAL = "principal", "Principal"
    #: The academic checker between the class teacher and the principal in the
    #: results approval chain. Named for the scope that exists: the chain runs
    #: per (class, term) and carries no subject, so a head of department — who
    #: is head *of a subject area* — would have nothing here to be head of.
    #:
    #: The stored value is short because `Membership.role` is `max_length=16`
    #: and "vice_principal_academic" is 23 characters. The value is an internal
    #: key like "admin" and "bursar"; the label is what anybody actually reads.
    VICE_PRINCIPAL_ACADEMIC = "vp_academic", "Vice Principal (Academic)"
    TEACHER = "teacher", "Teacher"
    BURSAR = "bursar", "Bursar"
    PARENT = "parent", "Parent or guardian"
    STUDENT = "student", "Student"


# Role groupings for permission checks — not a second source of truth.
# These hold role *values*, which is what the database hands back. Role members
# are interchangeable with them: TextChoices mixes in str, so a member hashes
# and compares by value. (A plain enum.Enum would hash by name and silently
# fail set membership here.)
STAFF_ROLES = frozenset(
    {
        Role.ADMIN.value,
        Role.PRINCIPAL.value,
        Role.VICE_PRINCIPAL_ACADEMIC.value,
        Role.TEACHER.value,
        Role.BURSAR.value,
    }
)
FAMILY_ROLES = frozenset({Role.PARENT.value, Role.STUDENT.value})
# Every role except STUDENT may be held at several schools at once.
SINGLE_SCHOOL_ROLES = frozenset({Role.STUDENT.value})
# Roles that may hand out memberships — at their own school only, never
# platform-wide. Principals are deliberately not included; add them here if
# that changes. Cross-school authority belongs to User.is_platform_staff.
MEMBERSHIP_GRANTING_ROLES = frozenset({Role.ADMIN.value})


def is_staff_role(role) -> bool:
    return role in STAFF_ROLES


def is_family_role(role) -> bool:
    return role in FAMILY_ROLES


class MembershipStatus(models.TextChoices):
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    ENDED = "ended", "Ended"


#: Statuses that still tie a person to a school — everything but ended history.
#: A graduated or transferred student keeps the row but frees the constraint.
#: This is the "does the relationship exist?" predicate: it decides whether a
#: student's single-school slot is occupied and whether a child shows up on
#: their parent's dashboard.
LIVE_STATUSES = frozenset(
    {MembershipStatus.INVITED.value, MembershipStatus.ACTIVE.value, MembershipStatus.SUSPENDED.value}
)

#: Statuses that let a person actually act at a school. Deliberately narrower:
#: an invitation is an offer rather than access, and a suspension withdraws it.
#: Both still occupy the relationship above — see LIVE_STATUSES. Keeping these
#: two predicates apart is what lets a parent see an invited child before that
#: child can sign in.
ACCESS_STATUSES = frozenset({MembershipStatus.ACTIVE.value})


class Relationship(models.TextChoices):
    MOTHER = "mother", "Mother"
    FATHER = "father", "Father"
    GUARDIAN = "guardian", "Guardian"
    OTHER = "other", "Other"


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, *, email=None, phone=None, **extra):
        if not username:
            raise ValueError("A username is required.")
        # save() normalizes username/email/phone, so raw input is fine here.
        user = self.model(username=username, email=email, phone=phone, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def matching_identifier(self, identifier):
        """Every user `identifier` could refer to, as one query.

        Checks username and email case-insensitively, and phone by its
        normalized value when `identifier` is phone-shaped. This is the
        single source of truth for identifier resolution: both
        User.assert_identifiers_unambiguous() and IdentifierBackend call
        this, so the collision rule and the sign-in resolution can never
        drift apart.
        """
        identifier = (identifier or "").strip()
        if not identifier:
            return self.none()
        query = Q(username__iexact=identifier) | Q(email__iexact=identifier)
        phone = try_normalize_phone(identifier)
        if phone:
            query |= Q(phone=phone)
        return self.filter(query)

    def create_superuser(self, username, password=None, *, email=None, phone=None, **extra):
        extra.setdefault("is_platform_staff", True)
        extra.setdefault("is_superuser", True)
        if not extra["is_platform_staff"] or not extra["is_superuser"]:
            raise ValueError("A superuser must be platform staff and a superuser.")
        return self.create_user(username, password, email=email, phone=phone, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """One person, one login, for the life of their relationship with the platform.

    Carries no role and no school. A student who becomes a teacher years later
    keeps this row; a parent with children at three schools has exactly one.
    """

    username = models.CharField(
        max_length=150,
        unique=True,
        help_text=(
            "Stable sign-in handle. Staff and parents usually get their email; "
            "students get a school-issued handle such as STM/2026/0042. A "
            "username that is itself a phone number is stored in E.164, "
            "matching the phone field."
        ),
    )
    # Optional: a young student may have neither. Unique when present.
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)

    full_name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=100, blank=True)

    is_active = models.BooleanField(default=True)
    # The SaaS operator — us, not a school. School authority comes from
    # Membership.role; this flag is only for platform-wide access.
    is_platform_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name or self.username

    def save(self, *args, **kwargs):
        self.normalize_identifiers()
        update_fields = kwargs.get("update_fields")
        # update_last_login fires on every sign-in and only ever touches
        # last_login, so it must not pay for a collision check that can't
        # possibly apply to it. Any save that could touch an identifier
        # column — including a plain save() with no update_fields at all —
        # still runs the check.
        if update_fields is None or set(update_fields) & {"username", "email", "phone"}:
            self.assert_identifiers_unambiguous()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.normalize_identifiers()
        self.assert_identifiers_unambiguous()

    def normalize_identifiers(self):
        self.username = canonical_username(self.username)
        self.email = normalize_email(self.email)
        self.phone = normalize_phone(self.phone)

    def assert_identifiers_unambiguous(self):
        """Option C: refuse to save if an identifier of this user's already
        resolves to a different account.

        Application-level, not (yet) a database constraint, and racy by
        construction: two concurrent saves can both pass this SELECT before
        either commits, because there is no row yet for either to lock
        against. Only this cross-column comparison rides on that race —
        same-column uniqueness (two users sharing one phone, say) is still
        enforced by real unique indexes regardless of this check. Acceptable
        pre-launch because the failure mode is safe: a genuinely ambiguous
        identifier is refused at sign-in (see IdentifierBackend), never
        silently resolved to the wrong person. The upgrade path is a
        UserIdentifier(kind, canonical_value) table with one unique index
        spanning all three kinds — a change of mechanism, not of rule.
        """
        for value in filter(None, {self.username, self.email, self.phone}):
            matches = User.objects.matching_identifier(value)
            if self.pk is not None:
                matches = matches.exclude(pk=self.pk)
            if matches.exists():
                raise ValidationError(f"{value!r} is already in use by another account.")

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        if self.short_name:
            return self.short_name
        return self.full_name.split(" ")[0] if self.full_name else self.username

    @property
    def is_staff(self):
        """Only for django.contrib.admin's login check.

        "Staff" in this codebase means a school staff role (see STAFF_ROLES),
        which is a Membership concern and has nothing to do with this.
        """
        return self.is_platform_staff

    # -- access questions, all answerable without leaving the public schema --

    def live_memberships(self):
        """Every relationship that still exists, invited and suspended included."""
        return self.memberships.live().select_related("school")

    def schools(self):
        """Every school this login can act at."""
        from schools.models import School

        return School.objects.filter(
            memberships__user=self, memberships__status__in=ACCESS_STATUSES
        ).distinct()

    #: Set on `request.user` by `SchoolAccessMiddleware` for a session opened
    #: with a guardian sign-in code, and read by `roles_at()` below. An instance
    #: attribute rather than a column, because it is a fact about *this request*
    #: and not about the person — the same login signing in with a password the
    #: next minute is entitled to everything again.
    #:
    #: A class-level default so nothing has to remember to set it. Every user
    #: object that was not narrowed reads False here, including one loaded in a
    #: management command where there is no request at all.
    parent_scoped_credential = False

    def roles_at(self, school) -> set:
        """Roles this login may currently exercise at `school`.

        Access-scoped, so an invited or suspended person has no roles here even
        though the membership exists. Authorisation reads this.

        **And it is the only thing authorisation reads**, which is why the
        guardian-code narrowing is here rather than beside the membership query
        in the middleware. `SchoolAccessMiddleware` sets `request.school_roles`,
        but nothing else in the platform consults it: `card_api._may_read()`,
        `gradebook.services.can_enter_marks()`, `results.services
        ._require_authority()` and every other guard call `actor.roles_at()`
        with `request.user`. Narrowing the middleware's own copy would have been
        a restriction that looked enforced and was not — the defect class this
        phase keeps finding.

        `parent_scoped_credential` is what a six-digit code buys.
        `settings.GUARDIAN_SESSION_AGE` is thirty days on the argument that a
        lost handset reaches "a parent-scoped read of their own children", and
        this filter is the sentence being true. A guardian who is also a bursar
        reads her own child's card on that session as a parent — served or
        withheld by the same fee gate as any other family — rather than as staff
        who is spared it, and cannot withhold anybody's card. Her staff roles are
        a password away, which is the point.
        """
        roles = set(
            self.memberships.with_access()
            .filter(school=school)
            .values_list("role", flat=True)
        )
        if self.parent_scoped_credential:
            return roles & {Role.PARENT.value}
        return roles

    def membership_id_at(self, school, role) -> int | None:
        """This login's membership pk in one role at one school, or `None`.

        Access-scoped exactly like `roles_at()`, so a suspended teacher has no
        membership here to be a class teacher with — the authorisation and the
        identity have to agree, and they only do if both ask the same question.

        Returns the **id**, not the object, because that is the shape every
        tenant table stores: a bare integer with no foreign key, the policy
        docs/tenancy.md settles. "Is this person the class teacher" is a
        comparison against one of those columns.
        """
        return (
            self.memberships.with_access()
            .filter(school=school, role=role)
            .values_list("pk", flat=True)
            .first()
        )

    def has_access_to(self, school) -> bool:
        return (
            self.is_platform_staff
            or self.memberships.with_access().filter(school=school).exists()
        )

    def children(self):
        """Every child this login guards, across every school.

        One query, no schema switching — this is what lets a parent with kids
        at two schools see all of them from one login.

        Scoped to LIVE_STATUSES rather than ACCESS_STATUSES on purpose: a parent
        should see an invited child on their dashboard before that child can
        sign in themselves.
        """
        return (
            Membership.objects.filter(
                guardianships__guardian=self, status__in=LIVE_STATUSES
            )
            .select_related("user", "school")
            .order_by("school__name", "user__full_name")
        )

    def student_membership(self):
        """A student has exactly one school, so this is singular by design.

        Relationship-scoped: an invited student already belongs to their school.
        """
        return self.memberships.live().filter(role=Role.STUDENT).select_related("school").first()


class MembershipQuerySet(models.QuerySet):
    def live(self):
        """Relationships that still exist — everything but ended history.

        Includes invited and suspended people, who hold a place at the school
        without being able to act there. For "may they do things?" use
        `with_access()`.
        """
        return self.filter(status__in=LIVE_STATUSES)

    def with_access(self):
        """Memberships that let the person act at the school. Active only."""
        return self.filter(status__in=ACCESS_STATUSES)

    def staff(self):
        return self.filter(role__in=STAFF_ROLES)

    def family(self):
        return self.filter(role__in=FAMILY_ROLES)

    def students(self):
        return self.filter(role=Role.STUDENT)

    def parents(self):
        return self.filter(role=Role.PARENT)

    def for_school(self, school):
        return self.filter(school=school)


class Membership(models.Model):
    """One person's standing at one school, in one capacity.

    Multiple rows per (user, school) are expected and correct: the maths
    teacher whose daughter attends the same school holds a TEACHER membership
    and a PARENT membership there.

    **Two columns here are held in place by a table this class never mentions.**
    `role` and `user` are read by `Guardianship.clean()`'s two rules *through*
    `Guardianship.student`, so changing either underneath a live link
    invalidates that link without writing a single guardianship row. Migration
    `0009_a_guardianship_pins_the_membership_under_it` therefore puts
    `accounts_membership_guardianship_rules` on **this** table — a guard on one
    table protecting another table's invariant, which is a shape nothing else
    in this repository has. Issue #96.

    What that means in practice, since nothing in this class would suggest it:

    * A statement that names only `accounts_membership` can be refused by
      guardianship. Moving a child's membership to another role, or to another
      user, raises `IntegrityError` while a link stands; the message says which
      link and tells the caller to call `services.unlink_guardian()` first.
    * Nothing else is affected. The trigger fires only when `role` or `user`
      actually changes, which is why `release_student()` can end an enrolment
      under live links — and must, because those rows are kept.
    * **Dropping or re-scoping `Guardianship` has to drop a trigger that lives
      on this table.** There is no third place that is written down.
    """

    user = models.ForeignKey(User, related_name="memberships", on_delete=models.CASCADE)
    # PROTECT, not CASCADE: these rows are the family history. Deleting a school
    # must not quietly take enrolments and guardianships with it as a side
    # effect. Ending a membership (status='ended') is the supported way to close
    # a relationship, and ended rows still block the delete — that is the point.
    school = models.ForeignKey(
        "schools.School", related_name="memberships", on_delete=models.PROTECT
    )
    role = models.CharField(max_length=16, choices=Role)
    status = models.CharField(
        max_length=16, choices=MembershipStatus, default=MembershipStatus.ACTIVE
    )

    # What this school calls them — a school may know a parent by a different
    # name than the one on their login.
    display_name = models.CharField(max_length=255, blank=True)
    # School-issued identifier: admission number, staff number.
    reference = models.CharField(max_length=64, blank=True)

    started_on = models.DateField(default=timezone.localdate)
    ended_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MembershipQuerySet.as_manager()

    class Meta:
        ordering = ["school__name", "role", "user__full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "school", "role"],
                name="uniq_membership_user_school_role",
            ),
            # A student has exactly one school. Enforced in the database, and
            # global rather than per-school precisely because Membership is
            # shared: a second live STUDENT row anywhere is rejected. Ended
            # rows are excluded so transfers and graduations keep their history.
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(role="student") & ~Q(status="ended"),
                name="one_live_student_membership_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["school", "role", "status"]),
            models.Index(fields=["user", "role"]),
            models.Index(fields=["school", "reference"]),
        ]

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} at {self.school}"

    def clean(self):
        if self.role and not is_staff_role(self.role) and not is_family_role(self.role):
            raise ValidationError({"role": f"Unknown role {self.role!r}."})

    @property
    def is_live(self) -> bool:
        """The relationship exists — not necessarily usable. See grants_access."""
        return self.status in LIVE_STATUSES

    @property
    def grants_access(self) -> bool:
        return self.status in ACCESS_STATUSES

    @property
    def is_staff_role(self) -> bool:
        return is_staff_role(self.role)

    @property
    def name(self) -> str:
        return self.display_name or self.user.full_name

    def guardians(self):
        """Who may see this student. Empty for non-student memberships."""
        return User.objects.filter(guardianships__student=self).distinct()

    def end(self, on=None, *, save=True):
        self.status = MembershipStatus.ENDED
        self.ended_on = on or timezone.localdate()
        if save:
            self.save(update_fields=["status", "ended_on", "updated_at"])
        return self


class Guardianship(models.Model):
    """Links a parent's login to one child.

    Points at the child's STUDENT *membership* rather than their user, because
    that single foreign key pins both the child and the school they attend.
    A parent with three children at two schools has three rows here and two
    PARENT memberships.
    """

    # Both sides PROTECT. These rows are family history, and no delete of a
    # person or a membership should erase them as a side effect. Call
    # services.unlink_guardian() first — it keeps both sides in step.
    guardian = models.ForeignKey(
        User, related_name="guardianships", on_delete=models.PROTECT
    )
    student = models.ForeignKey(
        Membership,
        related_name="guardianships",
        on_delete=models.PROTECT,
        help_text="The child's STUDENT membership, which pins the school too.",
    )
    relationship = models.CharField(
        max_length=16, choices=Relationship, default=Relationship.GUARDIAN
    )
    is_primary_contact = models.BooleanField(default=False)
    receives_invoices = models.BooleanField(default=True)
    can_collect = models.BooleanField(default=True, help_text="Authorised for pickup.")
    # What the school typed when it made this link. Shown to that school in
    # place of the `User`'s own name and channel until the guardian is live
    # there: a contact can resolve to somebody else's parent, and their stored
    # details are not this school's to read (#135, and `InvitationOut`'s rule).
    # `db_default` as well as `default`: the rules on this table are tested by
    # raw INSERTs that never reach `save()`, and a Python-only default leaves
    # them violating NOT NULL instead of the rule they were written to reach.
    entered_name = models.CharField(max_length=255, blank=True, default="", db_default="")
    entered_contact = models.CharField(
        max_length=254, blank=True, default="", db_default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["student__user__full_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["guardian", "student"], name="uniq_guardianship_guardian_student"
            ),
            models.UniqueConstraint(
                fields=["student"],
                condition=Q(is_primary_contact=True),
                name="one_primary_contact_per_student",
            ),
        ]

    def __str__(self):
        return f"{self.guardian} → {self.student.name}"

    def clean(self):
        """The two rules, in the copy every Python caller goes through.

        It was "the only copy there is" until #96; the note below says where
        the other two now live and why they had to exist.

        Both are **cross-table** — each compares a column on this row against a
        column on the `Membership` row it points at — and that is why neither
        appears in `Meta.constraints` above. Confirmed against this project's
        own Django and Postgres rather than assumed, because "there is no
        constraint here" is the kind of absence a later reader otherwise has to
        re-derive:

            CheckConstraint(condition=Q(student__role=Role.STUDENT))
            CheckConstraint(condition=~Q(guardian=F("student__user")))
            -> FieldError: Joined field references are not permitted in this query

            ALTER TABLE ... CHECK ((SELECT role FROM accounts_membership ...) = 'student')
            -> NotSupportedError: cannot use subquery in check constraint

        **This is no longer the only enforcement, and has not been since #96.**
        Two row-level triggers now carry the same two rules, because `save()`
        below closes the ORM paths and there were three that never reach it:

        * `accounts_guardianship_rules`
          (`0008_guardianship_rules_are_a_trigger`) on this table, for
          `bulk_create()`, `QuerySet.update()` and a `psql` session.
        * `accounts_membership_guardianship_rules`
          (`0009_a_guardianship_pins_the_membership_under_it`) on
          **`accounts_membership`**, for the third: changing the `role` or the
          `user` of a membership a live link points at breaks that link without
          writing a row here at all, so no trigger on this table can see it.

        Three copies of two rules, then, and that is the cost of the rules
        being cross-table — `Meta.constraints` cannot hold them. Keeping them in
        step is manual: if either rule changes here, both migrations change
        too, and `GuardianshipRulesHoldOnEverySavePathTests` plus the two
        classes after it are what go red if only one of the three moves.

        Each error carries an explicit `code`. `accounts.services` translates on
        those codes rather than on the message text — a message is shared
        prose, a code names *which rule* refused.
        """
        if self.student_id and self.student.role != Role.STUDENT:
            raise ValidationError(
                {
                    "student": ValidationError(
                        "A guardianship must point at a STUDENT membership.",
                        code="not_a_student",
                    )
                }
            )
        if self.guardian_id and self.student_id and self.guardian_id == self.student.user_id:
            raise ValidationError(
                {
                    "guardian": ValidationError(
                        "A student cannot be their own guardian.",
                        code="self_guardian",
                    )
                }
            )

    def save(self, *args, **kwargs):
        """Ask `clean()` on the way past, so no write can skip the rules.

        `Model.save()` does not call `full_clean()`, so before this override
        `Guardianship.objects.create()` wrote a row that violated either rule
        without complaint. The rules were stated in `clean()` and reached only
        from the tests; what actually held them in production was a second,
        hand-written copy of both inside `services.link_guardian()`. Two copies
        of a rule are one copy and one place for it to drift. Issue #91.

        Raising `ValidationError` rather than a `services.MembershipError`
        subclass is forced, not chosen: `services` imports this module, so
        reaching the other way for an exception type is the circular import
        `TransferError` already declines to make below. The service translates
        at its own boundary instead.

        `validate_constraints=False` is the one flag here, and it is
        load-bearing. It keeps a duplicate pair travelling all the way to
        `uniq_guardianship_guardian_student` in the database, so the failure a
        losing caller meets is an `IntegrityError`. That matters because
        `link_guardian()` reaches this through `get_or_create()`, which catches
        `IntegrityError` and nothing else:

            except IntegrityError:
                try:
                    return self.get(**kwargs), False
                except self.model.DoesNotExist:
                    pass
                raise

        Turn the flag on and the same duplicate is refused in Python as a
        `ValidationError` *before* the INSERT. `get_or_create()` does not catch
        that, so a caller who simply lost a race stops recovering and starts
        raising. `test_the_loser_of_a_race_recovers_instead_of_raising` in
        `accounts/tests/test_guardianship_concurrency.py` arranges exactly that
        lost race and is the test that goes red if this flag flips.

        Two things that are *not* reasons, both checked rather than assumed:

        * `validate_unique` is not involved and is not passed. This model's
          uniqueness is a `UniqueConstraint` in `Meta.constraints`, which
          `validate_unique()` does not inspect — `unique_together` is empty — so
          it is inert in every combination. It was passed as `False` here and
          read as if it were doing the work above; it is gone.
        * `one_primary_contact_per_student` does not need this flag either.
          `link_guardian()` clears the previous primary before it saves, so the
          partial index is not in breach by the time validation runs, and
          constraint validation would not have refused that sequence.

        Nothing is excluded, so the field-level rules are asked here too rather
        than only at the database.
        """
        self.full_clean(exclude=None, validate_constraints=False)
        return super().save(*args, **kwargs)

    @property
    def school(self):
        return self.student.school


class TransferError(Exception):
    """A transfer could not be requested, accepted or called off as asked.

    The base for every refusal in the handshake, on both sides of the seam: the
    states this module enforces (already resolved, the enrolment moved on) and
    the ones `transfers.py` enforces (wrong side, nothing to answer). It lives
    here rather than there because the dependency already runs that way —
    `transfers.py` imports this module, not the reverse — so one
    `except TransferError` catches the whole flow.

    Deliberately not a subclass of `services.MembershipError`: that hierarchy
    lives in `services.py`, which imports *this* module, and reaching the other
    way for a base class would be a circular import. `NotPermitted` is still
    raised from `services` for authority, exactly as the invitation flow does.
    """


class TransferAlreadyResolved(TransferError):
    """This request has already been accepted, declined or withdrawn."""


class EnrolmentMovedOn(TransferError):
    """The enrolment this request would move is no longer live.

    Its own type because the fix differs: nothing is wrong with the request, and
    nobody did anything wrong. The child left by another route — released
    without a destination, graduated, transferred by platform staff — while this
    sat pending, so there is nothing left to hand over.
    """


class TransferSide(models.TextChoices):
    """Which end of a transfer somebody is acting from.

    Two schools, and every act in the handshake belongs to exactly one of them.
    Naming the side rather than the school is what keeps the rules readable: the
    requester signs for their own side, the answerer for the other, and neither
    statement has to mention which school is which.
    """

    RELEASING = "releasing", "Releasing school"
    RECEIVING = "receiving", "Receiving school"

    @property
    def other(self) -> "TransferSide":
        return (
            TransferSide.RECEIVING
            if self == TransferSide.RELEASING
            else TransferSide.RELEASING
        )


class TransferRoute(models.TextChoices):
    """How a transfer came to happen — and therefore what this row is evidence of.

    Set by the code path that wrote the row, never by a caller: neither
    `request_transfer_as()` nor `transfer_student_as()` accepts it as an
    argument, so a row cannot claim to be something it is not. The check
    constraints below make the same guarantee at the database level, so it holds
    against a shell session and a data migration too.

    HANDSHAKE     Two schools agreed. Two distinct signatories, `requested_side`
                  says who spoke first, and the row passed through `pending`.
    SINGLE_PARTY  One actor held authority at both ends and did the whole thing
                  through `services.transfer_student_as()`. There was never a
                  second party, so the row names one person twice and has no
                  side — and says so rather than dressing itself up as consent
                  that nobody gave.
    """

    HANDSHAKE = "handshake", "Agreed between two schools"
    SINGLE_PARTY = "single_party", "Carried out by one authority"


class TransferRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"
    WITHDRAWN = "withdrawn", "Withdrawn"


class TransferRequestQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(status=TransferRequestStatus.PENDING)

    def for_school(self, school):
        """Everything either side of `school` — outgoing and incoming alike."""
        return self.filter(Q(student__school=school) | Q(to_school=school))

    def awaiting(self, school):
        """Pending requests it is `school`'s turn to answer, and can still answer.

        The other side asked; this side has not replied. Note it is keyed off
        which side *requested*, not off which school appears where: a school
        both receives requests to admit and receives requests to release, and
        the only thing separating them is who spoke first.

        The live-enrolment filter is what keeps this list honest. A request whose
        child left by another route stays PENDING — nobody declined it, and
        rewriting its status to pretend otherwise would put a lie in the record
        this table exists to be. But it can never be accepted again, so showing
        it as work waiting on a school would be its own kind of lie. It drops
        out of the queue and keeps its status.
        """
        return self.pending().filter(
            Q(student__status__in=LIVE_STATUSES)
            & (
                Q(requested_side=TransferSide.RELEASING, to_school=school)
                | Q(requested_side=TransferSide.RECEIVING, student__school=school)
            )
        )


class TransferRequest(models.Model):
    """One school's proposal to move a child to another, and the other's answer.

    `release_student_as()` and `enroll_student_as()` already let two schools move
    a child without either writing at the other, but they are two unconnected
    acts: nothing ties a release to the admission it was meant for, nothing
    records that anyone agreed, and between them the child belongs to no school.
    This is what connects them.

    **The handshake assembles two-sided authority out of two one-sided acts.**
    That is the whole idea, and it is worth stating plainly. `transfer_student()`
    genuinely needs authority at both ends — it ends a membership at one school
    and opens one at the other. Requiring one caller to hold both is what made
    ordinary transfers impossible. So one school signs by *requesting*, the other
    signs by *accepting*, and only when both signatures exist does the transfer
    run — in a single transaction, which is what closes the window the two-act
    path leaves open. Neither side ever acted at the other's school; the pair of
    consents did.

    Either side may initiate. A releasing school saying "we are letting this
    child go to Grace Academy" and a receiving school saying "we would like to
    admit this child from St Mary's" are the same proposal from opposite ends,
    and which one happens first is a fact about the family, not about the model.
    `requested_side` records which it was, because "who asked" is the first
    question anyone will have when a transfer is disputed.

    Points at the child's STUDENT `Membership` rather than repeating the child
    and the school they are leaving. That one foreign key pins both, and it
    cannot drift out of step with the enrolment it is proposing to move — which
    two loose columns could. `student_user` and `from_school` read them back off
    it.
    """

    student = models.ForeignKey(
        Membership,
        related_name="transfer_requests",
        on_delete=models.PROTECT,
        help_text="The child's STUDENT membership, which pins the leaving school too.",
    )
    to_school = models.ForeignKey(
        "schools.School", related_name="incoming_transfer_requests", on_delete=models.PROTECT
    )

    requested_by = models.ForeignKey(
        User, related_name="transfer_requests_made", on_delete=models.PROTECT
    )
    #: Which end asked. Not derivable after the fact: an admin can hold
    #: authority at both schools, and by the time anyone reads this row the
    #: memberships that granted it may have changed.
    #:
    #: Null on a SINGLE_PARTY row, and null rather than a default, because there
    #: was no side: one actor held both ends. Writing RELEASING there to avoid a
    #: nullable column would be inventing a fact, and this table's whole purpose
    #: is to be believed. A constraint below ties the two fields together.
    requested_side = models.CharField(
        max_length=16, choices=TransferSide, null=True, blank=True
    )
    requested_at = models.DateTimeField(auto_now_add=True)

    #: Whether two schools agreed or one authority acted alone. See TransferRoute.
    route = models.CharField(
        max_length=16, choices=TransferRoute, default=TransferRoute.HANDSHAKE
    )

    #: Who took this out of `pending`, and when. Null while it is still open.
    #:
    #: "Resolved", not "answered", and the difference is load-bearing. An accept
    #: or a decline is an *answer*, and comes from the other side of the table by
    #: definition. A withdrawal comes from the side that asked, and may well be
    #: the same person who asked — so a column called `answered_by` invited the
    #: rule "these two names always differ", which is false for exactly that
    #: case. The constraint below states the narrower thing that is actually
    #: true: an *answered* transfer names two people.
    resolved_by = models.ForeignKey(
        User,
        related_name="transfer_requests_answered",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=16, choices=TransferRequestStatus, default=TransferRequestStatus.PENDING
    )
    #: What the receiving school will call the child. Carried on the request so
    #: it can be offered when the receiving school initiates, and supplied at
    #: acceptance otherwise; either way it is the receiving school's to set.
    reference = models.CharField(max_length=64, blank=True)
    note = models.TextField(blank=True, help_text="Free text, shown to both schools.")

    objects = TransferRequestQuerySet.as_manager()

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            # At most one pending request per enrolment, in the database rather
            # than in application code — the same spirit as the one-school slot
            # it protects. Two pending requests would let one school agree to
            # Grace and another admin agree to Hillside for the same child, and
            # whichever landed second would find the enrolment already gone.
            # A second destination has to wait for the first to be declined or
            # withdrawn, which is a real constraint on schools and the honest
            # one: a child is transferring to one place.
            models.UniqueConstraint(
                fields=["student"],
                condition=Q(status="pending"),
                name="one_pending_transfer_request_per_student",
            ),
            # The next four are what stop a row lying about how it came about.
            # Application code already writes `route` itself rather than taking
            # it from a caller, but "the only code that writes this is careful"
            # is a property of today's code; these are properties of the table.
            #
            # An answered handshake names two different people. This is
            # `SameSignatory` again, one layer down — and the layer that also
            # catches a shell session, a data migration, or a future endpoint
            # that forgets.
            #
            # Scoped to accepted and declined, which are the outcomes that claim
            # something about the *other* school. A withdrawal is the asking
            # side retracting its own proposal, so it names its own people and
            # frequently the very person who asked; demanding two names there
            # would forbid the most ordinary thing a school can do with a
            # request it no longer wants.
            models.CheckConstraint(
                condition=Q(route=TransferRoute.SINGLE_PARTY)
                | Q(
                    status__in=[
                        TransferRequestStatus.PENDING,
                        TransferRequestStatus.WITHDRAWN,
                    ]
                )
                | (
                    Q(resolved_by__isnull=False)
                    & ~Q(requested_by=F("resolved_by"))
                ),
                name="answered_transfer_names_two_signatories",
            ),
            # A single-party row names one person, twice, and never nobody: it
            # is written only after the transfer has happened, so an unanswered
            # one would describe an event with no author.
            models.CheckConstraint(
                condition=Q(route=TransferRoute.HANDSHAKE)
                | (Q(resolved_by__isnull=False) & Q(requested_by=F("resolved_by"))),
                name="single_party_transfer_names_one_signatory",
            ),
            # ...and only after it succeeded, so it is never pending, declined
            # or withdrawn. There was no proposal to answer.
            models.CheckConstraint(
                condition=Q(route=TransferRoute.HANDSHAKE)
                | Q(status=TransferRequestStatus.ACCEPTED),
                name="single_party_transfer_is_always_accepted",
            ),
            # A side is exactly the thing a single-party transfer does not have,
            # and exactly the thing a handshake must record.
            models.CheckConstraint(
                condition=Q(route=TransferRoute.HANDSHAKE, requested_side__isnull=False)
                | Q(route=TransferRoute.SINGLE_PARTY, requested_side__isnull=True),
                name="transfer_side_matches_route",
            ),
        ]
        indexes = [
            models.Index(fields=["to_school", "status"]),
            models.Index(fields=["student", "status"]),
        ]

    def __str__(self):
        return (
            f"{self.get_status_display()} transfer of {self.student.name} "
            f"to {self.to_school}"
        )

    # -- read the pair back off the membership --------------------------------

    @property
    def student_user(self):
        return self.student.user

    @property
    def from_school(self):
        return self.student.school

    @property
    def is_pending(self) -> bool:
        return self.status == TransferRequestStatus.PENDING

    def school_for(self, side):
        """The school somebody acting for `side` must hold authority at.

        Asked as a question about a side rather than about a user, because a
        person may hold authority at both ends and the model should not have to
        care which. `school_for(requested_side.other)` is therefore "who still
        has to sign this".
        """
        return self.from_school if side == TransferSide.RELEASING else self.to_school

    # -- answering ------------------------------------------------------------

    def _lock_pending(self):
        """This row, locked, if it is still open to an answer.

        Every answer starts here, so "is this still pending?" is asked once, of
        a row this transaction holds, rather than of whatever the caller happened
        to load. The invitation flow learned that the expensive way: a guard
        reading an in-memory copy is answering a question about the past, and two
        answers arriving together both passed it before either wrote.

        `.order_by()` for the reason `Meta.ordering` always needs it under
        `FOR UPDATE` — this one sorts by a local column, but the habit is what
        keeps the next person from adding a joined sort and locking two more
        tables without noticing.
        """
        locked = (
            TransferRequest.objects.select_for_update().order_by().get(pk=self.pk)
        )
        if locked.status != TransferRequestStatus.PENDING:
            # Bring the caller's object in line with what the lock read, so it
            # stops asserting the state this transaction has just disproved.
            self.status = locked.status
            self.resolved_by_id = locked.resolved_by_id
            self.resolved_at = locked.resolved_at
            raise TransferAlreadyResolved(
                f"This transfer request was already "
                f"{locked.get_status_display().lower()}."
            )
        return locked

    def _record_answer(self, by, status, *, extra_fields=()):
        self.status = status
        self.resolved_by = by
        self.resolved_at = timezone.now()
        self.save(
            update_fields=["status", "resolved_by", "resolved_at", *extra_fields]
        )
        return self

    @transaction.atomic
    def accept(self, by, *, reference=""):
        """Both signatures are now in. Runs the transfer, returns the new membership.

        The transfer itself is `services.transfer_student()`, unchanged, and
        called here for the first time by something other than an admin who
        holds both schools. That is the point: the two consents recorded on this
        row *are* the two-sided authority it has always needed, so it can run in
        one transaction — no window where the child belongs to nowhere, and the
        guardians carried across rather than re-linked by hand.

        The enrolment is re-checked rather than assumed. A pending request is a
        proposal about a relationship, and the relationship may have moved on
        while the request sat there — the child released without a destination,
        graduated, or moved by platform staff. Accepting then would either fail
        on the one-live-student index or quietly revive an ended enrolment, so
        `EnrolmentMovedOn` says what actually happened instead.

        The answer is written **last**, after everything that could refuse has
        refused. A row reading "accepted" beside an enrolment that never moved
        would be a worse record than no row at all, and this is a record whose
        whole purpose is to be trusted when a transfer is disputed.
        """
        # Imported here, not at module scope: `services` imports this module, so
        # a module-level import would close the loop.
        from .services import transfer_student

        self._lock_pending()

        student = (
            Membership.objects.select_for_update().order_by().get(pk=self.student_id)
        )
        if not student.is_live:
            raise EnrolmentMovedOn(
                f"{student.user}'s enrolment at {student.school} is "
                f"{student.get_status_display().lower()}, so there is nothing to "
                f"hand over. A fresh admission is the way in now."
            )

        if reference:
            self.reference = reference

        moved = transfer_student(student, self.to_school, reference=self.reference)
        self._record_answer(by, TransferRequestStatus.ACCEPTED, extra_fields=["reference"])
        return moved

    @transaction.atomic
    def decline(self, by):
        """The other side says no. The enrolment is untouched."""
        self._lock_pending()
        return self._record_answer(by, TransferRequestStatus.DECLINED)

    @transaction.atomic
    def withdraw(self, by):
        """The side that asked calls it off. The enrolment is untouched."""
        self._lock_pending()
        return self._record_answer(by, TransferRequestStatus.WITHDRAWN)


class SignInScope(models.TextChoices):
    """The three things a run of failed sign-ins is counted against.

    They answer different questions. IDENTIFIER bounds how many guesses one
    account can absorb; ADDRESS bounds how many guesses one machine can make
    across all accounts, which is the credential-stuffing shape the first one
    cannot see.

    CHANNEL is the guardian door's, and it is **not** IDENTIFIER under another
    name. `throttling.key_for()` normalises through `canonical_username()`, so a
    phone number typed at the code door and the same number typed at the
    password door would land in one bucket — and a parent's number is on the
    enrolment form, which is exactly the semi-public identifier
    `accounts.throttling` refuses to let anyone weaponise. Shared, it would let
    whoever can read that form close a teacher's password door by guessing codes
    at it. Two doors, two buckets. See `accounts.guardian_signin`.
    """

    IDENTIFIER = "identifier", "Identifier"
    ADDRESS = "address", "Network address"
    CHANNEL = "channel", "Guardian contact channel"


class SignInAttempts(models.Model):
    """One row per throttled key, holding a count and the window it counts in.

    A counter rather than a row per attempt, so the table is bounded by the
    number of distinct keys seen rather than by how hard somebody is trying.
    That trades away an audit trail; if one is wanted later it belongs in the
    log stream, not here, where it would be a second copy with different
    retention.

    **In the public schema, like everything else in this app.** A throttle that
    lived per-tenant would count each school separately, and sign-in does not
    happen at a school — it happens on the portal, before any school is chosen.

    **The identifier is stored as a digest, the address in the clear**, and the
    asymmetry is deliberate. Whatever was typed into the identifier box is not
    always an identifier: people type their password into it, and a table of
    those in plain text is a credential store nobody decided to build. Hashing
    costs nothing here because the key is only ever compared for equality — the
    same reasoning `schools.models.hash_token()` gives for invitation tokens.
    An address is not a credential and is the one field an incident is actually
    investigated from, so it stays readable.
    """

    scope = models.CharField(max_length=16, choices=SignInScope.choices)
    key = models.CharField(
        max_length=255,
        help_text="SHA-256 of the normalized identifier, or the address itself.",
    )
    failures = models.PositiveIntegerField(default=0)
    window_started_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "key"], name="one_signin_counter_per_key"
            )
        ]

    def __str__(self):
        return f"{self.scope}:{self.key} ({self.failures})"


class ContactChannel(models.TextChoices):
    """How a guardian is reached, and therefore how they prove who they are.

    A field rather than a hardcoded assumption, and that is the whole point of
    it (`docs/parent-access.md`, D9). Whether Nigerian schools hold usable
    guardian *emails* is unverified — the September 2026 confirmation was about
    phone numbers — so the design must not depend on the answer. If schools turn
    out to hold good emails, email is the identity; if they only hold numbers,
    phone works. No rewrite either way.
    """

    EMAIL = "email", "Email"
    PHONE = "phone", "Phone"


#: How long a verification code stays good for. Short, because the code is six
#: digits and the window is part of what bounds guessing (see
#: `accounts.guardian_contacts`), and because a guardian reads it off a handset
#: they are holding — this is not an emailed link that has to survive a weekend
#: the way `schools.models.DEFAULT_INVITATION_TTL` does.
DEFAULT_VERIFICATION_TTL = timedelta(minutes=15)

#: Digits in a verification code. Six is what a person will retype off an SMS
#: without giving up. It is also only a million possibilities, which is why the
#: attempt cap below — not the hash — is what stands between a code and a
#: guess. See `guardian_contacts.hash_code()`.
VERIFICATION_CODE_DIGITS = 6

#: Wrong guesses one code absorbs before it is dead. Five against 10**6, inside
#: a fifteen-minute window, leaves an attacker a 1-in-200,000 shot per code.
#:
#: This bounds guessing *per code*, which is only half the answer: without a
#: bound on how many codes may be minted, an attacker resends and gets another
#: five. The other half is the send limit in settings
#: (`MAX_VERIFICATION_SENDS_PER_CHANNEL`), applied in
#: `guardian_contacts.request_verification()`.
MAX_VERIFICATION_ATTEMPTS = 5


class GuardianAccount(models.Model):
    """One guardian, once, and the opaque handle that names them.

    This is *the guardian record* of D9 and D10: one row, reached by one
    action, whichever door it came through. A parent with three children at two
    schools still has exactly one of these — alongside the three `Guardianship`
    rows and two PARENT memberships that D5 already gives them.

    **Why this is not `Guardianship`.** A guardianship is per child, so putting
    the channel there would mean a parent of three verifying the same phone
    three times, and holding three opaque identifiers for one person. D10 says
    "one row with one opaque identifier", and the contact channel is verified
    "exactly once per channel" — neither is expressible per child.

    **Why this is not `User`.** It nearly is, and `User` is already one row per
    person across every school. But the credential here is guardian-shaped and
    guardian-only — no password (D3), a channel instead — and a student or a
    teacher has no use for any of it. Keeping it off `User` also means the
    creation path is one table with one creator, which is what makes "never
    auto-create a guardian from an inbound contact" a thing you can point at
    rather than a rule spread across the account model.

    `public_id` is D9's stable opaque identifier: **not the channel value**,
    which changes and is reassignable, and **not the row pk**, which is a
    sequence number that leaks how many guardians exist and cannot survive a
    records merge. Read it as a handle, not as an identity system — D5 still
    owns cross-school identity, and this does not replace it.
    """

    user = models.OneToOneField(
        User,
        related_name="guardian_account",
        on_delete=models.PROTECT,
        help_text="The person. One guardian account per login, forever.",
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Guardian account for {self.user}"

    # -- the gate D9 describes, as a question anything can ask ---------------

    def live_contact(self):
        """The channel currently standing for this guardian, or None.

        At most one, held by `one_live_contact_per_guardian`. Verified or not:
        a channel entered and not yet confirmed is still the live one, it just
        does not open anything yet.
        """
        return self.contacts.filter(revoked_at__isnull=True).first()

    def has_verified_channel(self) -> bool:
        """Whether this guardian's link is live, per D9.

        **This is the predicate; it is not yet the gate.** Nothing reads it to
        refuse access today, because sign-in does not exist yet — that is the
        next slice, and it is where "the guardian link does not go live until
        Classnode verifies the channel in-band" stops being a sentence in a
        design doc. Linking a guardian still grants an ACTIVE PARENT membership
        (`services.link_guardian()`), deliberately unchanged here.
        """
        return self.contacts.filter(
            revoked_at__isnull=True, verified_at__isnull=False
        ).exists()


class GuardianContact(models.Model):
    """A channel a guardian is reached on: a type, a value, and whether it is proven.

    Append-only, and enforced as such by `accounts_guardian_contact_append_only`
    rather than by this docstring (operating rule 3). Two one-way stamps are the
    only writes an existing row ever takes:

    * `verified_at` — set once, when a code sent to this channel comes back.
    * `revoked_at` — set once, when a later channel replaces this one. **Nothing
      writes it yet.** The contact-change flow of D11 is the next slice; the
      trigger permits the stamp now so that landing D11 is a service, not a
      second migration rewriting a trigger this one already got right.

    **`value` carries no unique constraint, and that is deliberate.** One
    handset per household is the ordinary case for the parents this is built
    for, so two guardians sharing a number must both be able to hold it. This is
    the same trap `schools.models.Invitation` already records — "a phone number
    shared between two people (a household with one handset — the case that
    arrives with parents) must not collide" — and it is the reason the channel
    could not simply be `User.phone`, which is `unique=True` and would have
    refused the second parent outright.

    The consequence lands at sign-in, not here: a value can resolve to more than
    one guardian, and whatever reads it must be built for that rather than
    assuming `.get()`.
    """

    guardian = models.ForeignKey(
        GuardianAccount, related_name="contacts", on_delete=models.PROTECT
    )
    channel_type = models.CharField(max_length=8, choices=ContactChannel)
    value = models.CharField(
        max_length=254,
        help_text=(
            "Normalized before it is stored: E.164 for a phone, lowercased "
            "domain for an email. Never what was typed."
        ),
    )
    # Which admin typed it. D11 makes contact changes clerical — any school
    # admin may make one — which is workable precisely because every row says
    # who wrote it, so "who changed this and when" has an answer without having
    # had to predict who would be allowed to.
    created_by = models.ForeignKey(
        User, related_name="guardian_contacts_recorded", on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # Sign-in resolves a typed value to whoever holds it. Not unique:
            # see the class docstring on shared handsets.
            models.Index(fields=["value"]),
        ]
        constraints = [
            # D9 gives a guardian *a* channel, singular, and D11's change flow
            # is a replacement — "new channel entered → old binding revoked
            # immediately" — not an addition. Until that flow exists, this
            # refuses a second channel outright rather than letting a guardian
            # quietly acquire two live ones that disagree about who they are.
            models.UniqueConstraint(
                fields=["guardian"],
                condition=Q(revoked_at__isnull=True),
                name="one_live_contact_per_guardian",
            ),
        ]

    def __str__(self):
        return f"{self.get_channel_type_display()} {self.value} ({self.state})"

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    @property
    def is_live(self) -> bool:
        """Verified and not replaced. What D9 means by the link being live."""
        return self.verified_at is not None and self.revoked_at is None

    @property
    def state(self) -> str:
        if self.revoked_at is not None:
            return "revoked"
        return "verified" if self.verified_at is not None else "unverified"

    def save(self, *args, **kwargs):
        """Normalize on the way past, so no write can store what was typed.

        `Model.save()` does not call `full_clean()`, so without this
        `GuardianContact.objects.create(value="0803 123 4567")` stores the
        spacing verbatim, and that channel never matches the number again —
        neither at sign-in nor against the `User` row holding the same person's
        phone. Exactly the shape of issue #91, which `Guardianship.save()`
        records in full: a rule reachable only from `clean()` is a rule the
        tests hold and production does not.

        **Unconditional, and it was briefly guarded by `self._state.adding`.**
        That guard was removed because no control run could turn it red, which
        made it an unreachable branch rather than a protection: a stamp write is
        `save(update_fields=["verified_at"])`, so only that column reaches the
        UPDATE and the append-only trigger never sees `value` at all — and
        normalization is idempotent, so a full save of an unchanged row
        normalizes to what is already there. Two code paths where one suffices,
        and the shorter one is the one whose behaviour can be demonstrated.
        """
        self.normalize_value()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.normalize_value()

    def normalize_value(self):
        """Put `value` in the one form this system stores, by its declared type.

        Reuses PR #2's normalizers rather than restating them, which is what
        keeps a channel and a `User` identifier agreeing about what "the same
        phone number" means. `matching_identifier()` resolves `User` columns and
        cannot see this table, so the two resolvers are separate code — the
        normalization underneath them must not be.
        """
        if self.channel_type == ContactChannel.PHONE:
            self.value = normalize_phone(self.value)
        elif self.channel_type == ContactChannel.EMAIL:
            # `normalize_email()` lowercases and nothing more — it is not a
            # validator, and `value` is a CharField because it also holds E.164.
            # Without this, "not-an-address" would be stored as an email channel
            # and every later send to it would fail silently at the gateway.
            validate_email(self.value or "")
            self.value = normalize_email(self.value)
        else:
            raise ValidationError(
                {"channel_type": f"{self.channel_type!r} is not a contact channel."}
            )
        if not self.value:
            raise ValidationError({"value": "A contact channel needs a value."})


class VerificationCodeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    #: Dead for any reason other than having worked: guesses exhausted, or
    #: superseded by a resend. Expiry is *not* a status — it is read off
    #: `expires_at` when the code is presented, the same lazy sweep
    #: `Invitation.validate_token()` argues for, so a row cannot sit live past
    #: its date because a cron job is broken.
    SPENT = "spent", "Spent"


class GuardianContactCode(models.Model):
    """The in-band proof: a one-time code sent to a channel, stored as a digest.

    Follows the storage pattern of `schools.models.Invitation` — only ever the
    SHA-256, never the code, so whoever can read this table still cannot mint a
    working one from it — and **departs from it in one load-bearing place.**

    `Invitation.validate_token()` looks a token up *globally* by `token_hash`.
    That is safe for 32 bytes of entropy, where a collision will not happen and
    a guess will not land. It would be a hole here: a six-digit code has a
    million values, so a global lookup would let a code minted for one guardian
    confirm a different guardian's channel — the holder of `123456` would verify
    whoever else was issued `123456`. Every lookup in `guardian_contacts` is
    therefore **scoped to the contact row**, and `code_hash` is deliberately
    *not* unique.

    The corollary is that the digest is not the security boundary here, the way
    it is for an invitation token. `attempts` against `MAX_VERIFICATION_ATTEMPTS`
    is, and the fifteen-minute `expires_at` behind it.
    """

    contact = models.ForeignKey(
        GuardianContact, related_name="codes", on_delete=models.PROTECT
    )
    # Which school caused this send, for the per-school half of the rate limit.
    # Nullable because not every send has a school behind it: platform staff act
    # across schools (`_require_authority_over_guardian()` returns no school for
    # them), and a guardian-initiated resend in the sign-in slice will have none
    # either. A send with no school named is still counted against its channel —
    # the limit that protects the handset — and only escapes the aggregate one.
    requested_by_school = models.ForeignKey(
        "schools.School",
        related_name="guardian_verification_codes",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    #: SHA-256 of the code. Not unique: see the class docstring.
    code_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16, choices=VerificationCodeStatus, default=VerificationCodeStatus.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["contact", "status"]),
            # Both halves of the send limit are a COUNT over a time window, so
            # each gets the (what, when) index that makes it an index scan
            # rather than a walk of every code ever minted.
            models.Index(fields=["contact", "created_at"]),
            models.Index(fields=["requested_by_school", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_status_display()} code for {self.contact_id}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def attempts_exhausted(self) -> bool:
        return self.attempts >= MAX_VERIFICATION_ATTEMPTS


class GuardianSignIn(models.Model):
    """One opened guardian session: who was offered, who was picked, what proved it.

    `GuardianContact.value` carries no unique constraint on purpose — one
    household, one handset, two parents — so `resolve_guardians()` may hand back
    several people for one number and the person holding the phone says which of
    them they are. Nothing at sign-in can check that claim: D3 makes the handset
    the credential and it belongs to both parents equally. A self-asserted choice
    is the honest shape of the thing, and a self-asserted choice nobody wrote
    down is the shape nobody can audit afterwards.

    So this row exists to answer one question a term later, when a guardian says
    they never saw a card their co-parent acted on: **what were the
    alternatives, which was taken, and what proved the handset.**

    **`offered` is every guardian the value resolved to, including `picked`.**
    Storing only the ones not chosen would make the row unreadable on its own —
    "offered two, picked one" needs both halves in one place — and storing only
    the count would answer "was there a choice" without answering "between
    whom", which is the question that actually gets asked.

    **`proof` is the answered code row, not a timestamp of its own.**
    `confirm_sign_in_code()` returns the row rather than `True` for exactly this:
    it carries `confirmed_at`, the fold `last_authenticated_at()` reads for
    dormancy, and it names the channel the code went to. A duplicated timestamp
    here would be a second copy of that with its own way of being wrong.

    **One code, one session, held by the constraint and not by the flow.** The
    shared-handset path parks a spent code on the session and spends it on a
    second call, so "this code already opened a session" is a state two
    concurrent picks can both read as false. `one_session_per_answered_code` is
    what makes it true rather than likely; `record()` reads the refusal and hands
    the caller the module's one refusal, so a replay is indistinguishable from a
    wrong code.

    **Public schema, like `SignInAttempts`.** Sign-in happens on the portal,
    before any school is chosen, and a guardian with children at two schools has
    one of these rows rather than one per school.
    """

    picked = models.ForeignKey(
        GuardianAccount,
        related_name="sign_ins",
        on_delete=models.PROTECT,
        help_text="The guardian this session was opened as.",
    )
    offered = models.ManyToManyField(
        GuardianAccount,
        related_name="sign_ins_offered",
        help_text=(
            "Every guardian the typed value resolved to, including the one "
            "picked. One entry is the ordinary case; two is a shared handset."
        ),
    )
    proof = models.ForeignKey(
        GuardianContactCode,
        related_name="sign_ins",
        on_delete=models.PROTECT,
        help_text="The answered code that proved control of the handset.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["proof"], name="one_session_per_answered_code"
            )
        ]

    def __str__(self):
        return f"{self.picked} signed in at {self.created_at:%Y-%m-%d %H:%M}"

    @classmethod
    def record(cls, *, offered, picked, proof):
        """Write the row, or None if this code has already opened a session.

        Its own `atomic()` block, because an `IntegrityError` leaves the
        enclosing transaction unusable and the caller still has a refusal to
        raise — `throttling._locked_counter()`'s reasoning, for the same reason.
        """
        try:
            with transaction.atomic():
                row = cls.objects.create(picked=picked, proof=proof)
        except IntegrityError:
            return None
        row.offered.set(offered)
        return row
