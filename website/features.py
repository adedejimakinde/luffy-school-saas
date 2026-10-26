"""What the price includes, as the pricing page lists it (`docs/website.md`).

Each feature is a label and one plain sentence, and the ones not yet on `main`
name the setting that governs their "Coming soon" label (`settings.COMING_SOON_*`).
Switching that setting off removes the label and nothing else; the page, the
sitemap and the structured data do not change. A feature that has shipped has
no setting at all, so a feature added here without one is live.
"""

from django.conf import settings

#: (heading, [(label, sentence, setting or None)]). In the order the page draws them.
INCLUDED = [
    ("Results and report cards", [
        ("Report cards, including the Ogun State sheet",
         "Totals, grades, class positions and remarks worked out for you. Schools in Ogun State can "
         "switch on the report sheet the Ministry asks for.", None),
        ("CA and exam scores",
         "Teachers enter scores once, on their phones, and you approve each class before release.", None),
        ("Affective and psychomotor traits",
         "Conduct and skills ratings, set up by the school and printed on the report card.", None),
        ("Parent result checks",
         "A parent opens a child's report card with the admission number and the PIN on a paper slip. "
         "No account is needed.", None),
    ]),
    ("Registers, fees and notices", [
        ("Attendance registers",
         "Class teachers mark the register on their phones. If the network drops, it sends when it "
         "comes back.", None),
        ("Fees and payments tracking",
         "Each child has their own account number, so a transfer lands on the right record.", None),
        ("Notices",
         "Absence alerts, fee reminders and payment receipts to parents.", None),
    ]),
    ("Staff and exams", [
        ("Staff roles and subject-teacher assignment",
         "The principal, bursar, teachers and others each see their own part. The principal says "
         "who teaches which subject to which class.", None),
        ("Exam PIN slips",
         "Print a PIN slip for each student in a class, with exam officers the principal names.", None),
        ("CBT: school tests",
         "Teachers write questions, set timed tests, and the computer marks them.",
         "COMING_SOON_CBT_SCHOOL_TESTS"),
        ("CBT: UTME-style practice",
         "Timed practice in the format the exam body publishes, on questions the school writes.",
         "COMING_SOON_CBT_UTME_PRACTICE"),
        ("CBT: WASSCE-style practice",
         "Timed objective papers, one subject at a time, on questions the school writes.",
         "COMING_SOON_CBT_WASSCE_PRACTICE"),
    ]),
    ("Your school online", [
        ("A school website on its Classnode address",
         "A public website for the school at its own address on Classnode, built from the details "
         "the school publishes.", "COMING_SOON_SCHOOL_WEBSITE"),
    ]),
    ("Safe and separate", [
        ("Backups",
         "The database is backed up every night, with the changes in between kept so it can be "
         "restored to a recent moment.", None),
        ("Each school's data kept apart",
         "Every school's records are kept apart from every other school's.", None),
    ]),
]

#: The premium add-on, priced by asking. Sending from the school's own email
#: domain is the school's results and notices going out under its own name; it
#: is not a mailbox, and nothing here promises one.
PREMIUM = [
    ("A custom domain for the school website",
     "The school's website on an address the school owns.", "COMING_SOON_CUSTOM_DOMAIN"),
    ("Results and notices from the school's own email domain",
     "Results and notices sent from an address on the school's own domain.", "COMING_SOON_SENDER_DOMAIN"),
]

#: Every setting a feature above is governed by.
SETTINGS = sorted({s for _, items in INCLUDED for *_, s in items if s} | {s for *_, s in PREMIUM if s})


def coming_soon(setting):
    """Whether the feature governed by `setting` still wears its label. No setting, no label."""
    return bool(setting) and bool(getattr(settings, setting))


def _items(rows):
    return [
        {"label": label, "sentence": sentence, "coming_soon": coming_soon(setting)}
        for label, sentence, setting in rows
    ]


def included():
    """`INCLUDED` as the template draws it: a heading and its items, each with its label decided now."""
    return [{"heading": heading, "items": _items(rows)} for heading, rows in INCLUDED]


def premium():
    return _items(PREMIUM)
