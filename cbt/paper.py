"""A test's paper as one student's device receives it: their order, and **no key**.

`docs/cbt.md`, "Offline": "No keys and no explanations ever reach the device." This is
the one function that shapes a paper for a student, so the rule is held in one place:
`for_device()` builds each item from the fields named in `SENT`, and nothing else of a
`TestItem` is read. A test asserts the payload carries no `correct_index`, no
`explanation` and no other student's order.

Each option keeps its **original index**, because marking compares original indexes,
never letters (`docs/cbt.md`, "Integrity"); the letters a student sees are only their
order on this student's screen. The order comes from a seed (stored on the attempt in
step 4), so a student who signs in again gets the same paper in the same order.

In step 3 nothing sends this to a student: the preview a teacher, the vice principal or
the principal opens ("Try it as a student") is the same function, so what they review is
what a student would get.
"""

import random

#: The only fields of a `TestItem` a device is sent.
SENT = ("id", "stem", "image_key", "image_alt", "options", "marks")


def order_for(seed, count: int, shuffle: bool) -> list:
    """The positions `0..count-1` in this seed's order, or as set if not shuffled."""
    order = list(range(count))
    if shuffle:
        random.Random(f"q:{seed}").shuffle(order)
    return order


def option_order_for(seed, item_id, count: int, shuffle: bool) -> list:
    order = list(range(count))
    if shuffle:
        random.Random(f"o:{seed}:{item_id}").shuffle(order)
    return order


def for_device(test, items, seed, *, image_url=None) -> dict:
    """The paper for one student: items in their order, options in theirs, no answers.

    `items` are the test's `TestItem` rows; `image_url(key)` says where a picture is
    fetched from, or the key is left out.
    """
    items = sorted(items, key=lambda i: i.position)
    shown = []
    for number, at in enumerate(order_for(seed, len(items), test.shuffle_questions), start=1):
        item = items[at]
        values = {name: getattr(item, name) for name in SENT}
        options = values["options"]
        picture = values["image_key"]
        shown.append(
            {
                "id": values["id"],
                "number": number,
                "stem": values["stem"],
                "image": image_url(picture) if picture and image_url else None,
                "image_alt": values["image_alt"] if picture else "",
                "marks": values["marks"],
                "options": [
                    {"index": i, "text": options[i]}
                    for i in option_order_for(seed, values["id"], len(options), test.shuffle_options)
                ],
            }
        )
    return {
        "title": test.title,
        "duration": test.duration,
        "can_go_back": test.can_go_back,
        "grid": test.grid,
        "calculator": test.calculator,
        "items": shown,
    }


__all__ = ["SENT", "for_device", "option_order_for", "order_for"]
