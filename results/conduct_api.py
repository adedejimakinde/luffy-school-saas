"""The report card settings for the conduct and skills sections, over HTTP.

`results/ratings.py` has always held the rules; this is the door the setup page
uses. Two sections, **Affective (conduct)** and **Psychomotor (skills)**, each
with a switch, a list of traits the principal can rename, add, hide and reorder,
and one scale of five points whose words can be edited and whose numbers cannot.

Every route is for `ratings.CONFIGURING_ROLES`, the principal and the
administrator, and every one asks that **before** it looks anything up, for the
oracle reason `academics.api` gives: the status of a refusal must not tell a
class teacher which trait ids exist. Reading is as narrow as writing, because
the list of changes names people.

Nothing here reaches a released card. A card froze its own section and its own
scale when it went home; `ratings.card_sections()` and `scale_of_card()` read
those and never the settings below.
"""

from typing import List, Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth

from . import ratings
from .models import Trait, TraitGroup

router = Router(auth=session_auth)

_MAY_NOT = (
    "What a report card prints for conduct and skills is set by a principal or "
    "an administrator of the school."
)


class MessageOut(Schema):
    detail: str


class TraitOut(Schema):
    trait_id: int
    name: str
    is_hidden: bool
    #: Whether a rating has ever been made against it. A rated trait can be
    #: hidden but never deleted, and the page says why.
    has_ratings: bool


class SectionOut(Schema):
    group: str
    label: str
    enabled: bool
    traits: List[TraitOut]


class ScalePointOut(Schema):
    value: int
    label: str


class ChangeOut(Schema):
    at: str
    by: str
    summary: str


class ConductOut(Schema):
    sections: List[SectionOut]
    scale: List[ScalePointOut]
    changes: List[ChangeOut]


class EnabledIn(Schema):
    enabled: bool


class NewTraitIn(Schema):
    name: str


class TraitIn(Schema):
    #: Either or both. Omitted means leave it as it is.
    name: Optional[str] = None
    hidden: Optional[bool] = None


class OrderIn(Schema):
    trait_ids: List[int]


class LabelIn(Schema):
    label: str


_RESPONSES = {200: ConductOut, 403: MessageOut, 404: MessageOut, 422: MessageOut}


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No report card settings on this host.")
    return school


def _refuse_outsiders(request, school):
    if not ratings.can_configure_ratings(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT)
    return None


def settings_payload() -> ConductOut:
    from .models import TraitRating

    rated = set(TraitRating.objects.values_list("trait_id", flat=True).distinct())
    sections = []
    for group in TraitGroup:
        sections.append(
            SectionOut(
                group=group.value,
                label=group.label,
                enabled=ratings.is_enabled(group.value),
                traits=[
                    TraitOut(
                        trait_id=t.pk,
                        name=t.name,
                        is_hidden=t.is_hidden,
                        has_ratings=t.pk in rated,
                    )
                    for t in ratings.traits(group.value, include_hidden=True)
                ],
            )
        )
    return ConductOut(
        sections=sections,
        scale=[ScalePointOut(value=p.value, label=p.label) for p in ratings.scale()],
        changes=[
            ChangeOut(
                at=c.at.isoformat(),
                by=c.by_name or "The platform",
                summary=c.summary,
            )
            for c in ratings.changes()
        ],
    )


def _guarded(request, act):
    """Authority first, then the act, then the whole settings as they now stand."""
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused
    try:
        act()
    except ratings.NotAllowedToConfigureRatings:
        return 403, MessageOut(detail=_MAY_NOT)
    except ratings.RatingsError as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, settings_payload()


def _trait(trait_id: int) -> Trait:
    try:
        return Trait.objects.get(pk=trait_id)
    except Trait.DoesNotExist:
        raise Http404("No such trait.") from None


@router.get("/report-card/conduct/", response={200: ConductOut, 403: MessageOut})
def conduct_settings(request):
    """The two sections, their traits and the scale, and the latest changes."""
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused
    return 200, settings_payload()


@router.put("/report-card/conduct/{group}/enabled/", response=_RESPONSES)
def set_section(request, group: str, payload: EnabledIn):
    """Switch a section on or off. Off keeps every rating already entered."""
    return _guarded(
        request, lambda: ratings.set_group_enabled_as(request.user, group, payload.enabled)
    )


@router.post("/report-card/conduct/{group}/traits/", response=_RESPONSES)
def add_trait(request, group: str, payload: NewTraitIn):
    return _guarded(
        request, lambda: ratings.add_trait_as(request.user, group, payload.name)
    )


@router.put("/report-card/conduct/{group}/order/", response=_RESPONSES)
def reorder_traits(request, group: str, payload: OrderIn):
    return _guarded(
        request, lambda: ratings.reorder_as(request.user, group, payload.trait_ids)
    )


@router.put("/report-card/conduct/traits/{int:trait_id}/", response=_RESPONSES)
def change_trait(request, trait_id: int, payload: TraitIn):
    """Rename a trait, hide it or show it again. Never deletes."""
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused
    trait = _trait(trait_id)

    def act():
        if payload.name is not None:
            ratings.rename_trait_as(request.user, trait, payload.name)
        if payload.hidden is not None:
            ratings.set_trait_hidden_as(request.user, trait, payload.hidden)

    return _guarded(request, act)


@router.put("/report-card/conduct/scale/{int:value}/", response=_RESPONSES)
def set_scale_label(request, value: int, payload: LabelIn):
    """Rename a point of the 1 to 5 scale. The numbers do not move."""
    return _guarded(
        request, lambda: ratings.set_scale_label_as(request.user, value, payload.label)
    )
