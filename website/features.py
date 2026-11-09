"""What Classnode does today: the one list the public site draws from.

The homepage's price card, the pricing page, the FAQ's feature answers and
`/llms.txt` all read `GROUPS` and nothing else, so a feature is written once:
a name, one plain line and, where there is more to say, a detail.

**Only what is live.** A feature is added here the day it ships and not before.
Nothing here is labelled "coming soon", and a test refuses the words anywhere on
the public site. News posts, admissions forms, custom domains, a school's own
email domain, ID cards and password reset are not built yet and are not listed
(`docs/website.md`).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    key: str
    name: str
    line: str
    detail: str = ""


#: (heading, features). The headings are the pricing page's groups, in its order.
GROUPS = [
    ("Results and report cards", [
        Feature(
            "results", "Results",
            "CA and exam scores go in once. Totals, averages, grades and class positions are "
            "worked out for you.",
            "Class positions follow your school's tie rule. A paper not yet marked shows as \"-\", "
            "never as zero. Results go through the school's approval chain before release, and are "
            "locked after release.",
        ),
        Feature(
            "report-cards", "Report cards",
            "Standard and Ogun State report cards, with a whole class printed as one PDF.",
            "A preview stamp shows on every card until the results are released. The master "
            "broadsheet opens on screen, as a PDF and in Excel.",
        ),
    ]),
    ("Tests", [
        Feature(
            "cbt", "CBT",
            "Computer-based tests, set by your teachers and marked by the computer.",
            "Teachers keep question banks for each subject and class. The principal or vice "
            "principal approves a test before it opens. Students sit it on a phone or a computer, "
            "on a JAMB-style screen with a timer, a question grid, flag for review and a "
            "calculator. Answers are saved through a network drop or a power cut. Scores are sent "
            "into CA, and results are released to students and parents. Teachers get item "
            "analysis, to see how each question did.",
        ),
    ]),
    ("Fees, registers and parents", [
        Feature(
            "fees-and-registers", "Fees, attendance and registers",
            "Each child has their own fee account, you see what is still owed, and class teachers "
            "take the register on their phones.",
            "The register and score entry keep working when the network drops, and send when it "
            "comes back.",
        ),
        Feature(
            "parents", "Parents",
            "Parents see their children's released results and report cards online.",
            "A parent can also use the result checker, with the PIN on a paper slip.",
        ),
    ]),
    ("Your school, under its own name", [
        Feature(
            "portal", "Your school's own portal",
            "The school's crest, name and colours are on the sign-in and on every page.",
            "Your school signs in at its own address, such as school.classnode.co.",
        ),
        Feature(
            "app", "Installable app",
            "Staff and parents add the school's own app to the home screen of a phone or "
            "computer.",
            "No app store is needed.",
        ),
        Feature(
            "school-website", "School website",
            "The school's own website, in the Modern Campus theme with the school's colours and "
            "a slideshow.",
            "Up to 20 custom pages, pictures, albums, a hero video and a map. The editor shows a "
            "preview, and the principal approves a change before it goes live.",
        ),
    ]),
    ("Fast and safe", [
        Feature(
            "fast", "Fast on slow networks and phones",
            "Pages are kept light, so they open quickly on a cheap phone and a slow connection.",
        ),
        Feature(
            "backups", "Nightly off-site backups",
            "The database is backed up every night, to a place away from the server.",
        ),
    ]),
]

#: Every feature, in the order the pricing page draws them.
FEATURES = [feature for _, features in GROUPS for feature in features]

_BY_KEY = {feature.key: feature for feature in FEATURES}


def feature(key):
    """The feature called `key`. A typo is an error, not a blank on a public page."""
    return _BY_KEY[key]


def groups():
    """`GROUPS` as a template draws them: a heading and its features."""
    return [{"heading": heading, "items": items} for heading, items in GROUPS]
