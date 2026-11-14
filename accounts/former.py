"""A child who has left still reads the report cards that went home to them.

Audit finding G-05. Graduating or leaving ends a child's enrolment
(`services.release_student()`), and an ended membership grants nothing: the
school's own sign-in refused the login and `SchoolAccessMiddleware` refused
every page. So from the day promotion was confirmed, the SS 3 leavers could not
open the third-term card they had just earned. The card routes themselves were
never the obstacle: `results.card_api` serves a child their own released cards
whatever became of the membership (`CardClaim.SELF`), and holds a card back over
fees exactly as it does for anybody else in the family.

So this opens two things and no more:

- **the door**: a login whose STUDENT membership at this school has **ended**
  may sign in on the school's host (`signin.belongs_at()`);
- **the cards**: with no role here, that login reaches the paths in
  `CARD_PATHS` and nothing else. Every other page and route still answers as it
  does to somebody with no membership.

It grants **no role**. `User.roles_at()` is what every guard on the platform
reads, and it still answers nothing for this login, so no route that asks for a
student, a parent or staff is opened by this. What is reached is what the card
routes decide for themselves from who the card belongs to.

Guardians are not here: promotion and taking a child off the roll leave a
guardian's PARENT membership as it was (`keep_family_access`).

A **suspended** student is not a former one and is still refused: suspension is
a decision about access, and this is not a way round it.
"""

from .models import Membership, MembershipStatus, Role

#: What a former student may open: the list of their cards, a card, its PDF.
#: Prefixes, each ending in a slash so `/cards-of-everybody/` is not one.
CARD_PATHS = ("/cards/", "/api/results/cards/")


def was_a_student_here(user, school) -> bool:
    """Has `user` a STUDENT membership at `school` that has ended?"""
    if not getattr(user, "is_authenticated", False) or school is None:
        return False
    return Membership.objects.filter(
        user=user, school=school, role=Role.STUDENT, status=MembershipStatus.ENDED
    ).exists()


def may_open(user, school, path: str) -> bool:
    """May this login, holding no role at `school`, open `path`? Cards only."""
    return path.startswith(CARD_PATHS) and was_a_student_here(user, school)


__all__ = ["CARD_PATHS", "may_open", "was_a_student_here"]
