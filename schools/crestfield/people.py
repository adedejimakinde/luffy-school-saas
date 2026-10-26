"""Crestfield's made-up people: staff, 300 students and their guardians.

Every name is invented from common Yorùbá, Igbo and Hausa names, written the
way each language writes them: Yorùbá with its tone marks and under-dots
(Fúnmiláyọ̀, Ọlátúnjí), Igbo with its dotted vowels (Ọbịnna, Nnamdị), Hausa
with its hooked ɗ (Ɗanjuma) and its apostrophe for the glottal stop (Sa'adatu).
Any match with a real person is chance.

Everybody is dealt by a seeded `random.Random`, so a reset makes the same
school every time: the same child in the same seat with the same admission
number, which is what lets a salesperson learn the demo.

Contacts are reserved for fiction: staff email at `example.com` (RFC 2606),
guardians' phones in the North American 555-01xx range (`messaging.reserved`).
"""

import random
from dataclasses import dataclass

YORUBA, IGBO, HAUSA = "yoruba", "igbo", "hausa"

FIRST = {
    (YORUBA, "female"): (
        "Fúnmiláyọ̀", "Tèmítọ́pẹ́", "Adérónkẹ́", "Fọlákẹ́", "Mọ́rẹ́nikẹ́", "Àyìnkẹ́", "Yẹ́misí",
        "Títílayọ̀", "Bùsáyọ̀", "Ọmọ́tọ́lá", "Oyínkánsọ́lá", "Ìbùkún", "Adéọlá", "Ìfẹ́olúwa",
        "Tọ́lání", "Damilọ́lá", "Ìyanu", "Kẹ́hìndé",
    ),
    (YORUBA, "male"): (
        "Adébáyọ̀", "Babátúndé", "Ṣẹ́gun", "Kúnlé", "Gbénga", "Olúwaṣeun", "Ọláolúwa", "Ayọ̀délé",
        "Ọlámidé", "Táíwò", "Fẹ́mi", "Túndé", "Wálé", "Dámilárè", "Ayọ̀mídé", "Ọlámilékan",
        "Akínkúnmi", "Ṣeun",
    ),
    (IGBO, "female"): (
        "Chiamaka", "Ngozi", "Adaeze", "Chidinma", "Oluchi", "Ifeoma", "Obiageli", "Nkechi",
        "Amarachi", "Chinonso", "Ụchechi",
    ),
    (IGBO, "male"): (
        "Chukwuemeka", "Ọbịnna", "Nnamdị", "Ifeanyị", "Ụchenna", "Kelechi", "Chinedu", "Chigozie",
        "Ikenna", "Somtochukwu", "Chibụzọ", "Ụzọma", "Ebuka",
    ),
    (HAUSA, "female"): (
        "Hauwa", "Zainab", "Halima", "Fatima", "Aisha", "Bilkisu", "Hadiza", "Sa'adatu", "Nafisa",
        "Khadija", "Maryam", "Rahma",
    ),
    (HAUSA, "male"): (
        "Abubakar", "Aminu", "Ibrahim", "Musa", "Yusuf", "Umar", "Sani", "Rabi'u", "Ɗanjuma",
        "Kabiru", "Bashir", "Nasiru",
    ),
}

SURNAMES = {
    YORUBA: (
        "Adéyẹmí", "Ògúnlẹ́yẹ", "Akínwùmí", "Ọlátúnjí", "Àlàbí", "Ajíbádé", "Fálọlá", "Ọ̀jó",
        "Adésànyà", "Bámidélé", "Oyèláràn", "Àjàyí", "Adéwálé", "Ọláníyàn", "Akínọlá",
        "Ògúndípẹ̀", "Adéyínká", "Bọ́lárìnwá", "Ọ̀ṣúntókùn", "Adébáyọ̀",
    ),
    IGBO: (
        "Eze", "Nwankwọ", "Okeke", "Anyanwụ", "Nnadị", "Igwe", "Obi", "Chukwu", "Nwosu", "Ugwu",
        "Ọkafọ", "Ezenwa", "Mbah", "Okoro",
    ),
    HAUSA: (
        "Bello", "Abdullahi", "Ɗanjuma", "Garba", "Usman", "Lawal", "Shehu", "Aliyu", "Ɗanladi",
        "Yakubu", "Sule", "Idris", "Kabir",
    ),
}

#: About half Yorùbá, as an Abẹ́òkúta school would be, then Igbo, then Hausa.
PEOPLES = ((YORUBA, 50), (IGBO, 30), (HAUSA, 20))

#: The staff who are not class or subject teachers: `(key, role, full name)`.
#: Logins are `cfc.<key>`. The role is `accounts.models.Role`'s value.
OFFICE = (
    ("principal", "principal", "Dr Fúnmiláyọ̀ Adéyẹmí"),
    ("vp", "vp_academic", "Mr Chukwuemeka Nwankwọ"),
    ("admin", "admin", "Mrs Hauwa Ɗanjuma"),
    ("bursar", "bursar", "Mr Babátúndé Ọlátúnjí"),
)

#: Fifteen teachers: `(key, full name, the class they keep or "")`. Who teaches
#: what is `school.SUBJECT_TEACHERS`. `teacher` is the demo's teacher login:
#: JSS mathematics, and JSS 2B's class teacher, whose sheet is still open.
TEACHERS = (
    ("teacher", "Mrs Tèmítọ́pẹ́ Àlàbí", "JSS 2B"),
    ("t02", "Mr Ọbịnna Eze", "SS 3A"),
    ("t03", "Mrs Ngozi Okeke", "JSS 1A"),
    ("t04", "Mr Kúnlé Àjàyí", "SS 3B"),
    ("t05", "Miss Zainab Bello", "JSS 1B"),
    ("t06", "Mr Ṣẹ́gun Ògúnlẹ́yẹ", "JSS 3A"),
    ("t07", "Mrs Chiamaka Anyanwụ", "JSS 2A"),
    ("t08", "Mr Ibrahim Abdullahi", "SS 2B"),
    ("t09", "Mrs Adérónkẹ́ Ọ̀jó", "JSS 3B"),
    ("t10", "Mr Ifeanyị Nnadị", "SS 1B"),
    ("t11", "Mrs Halima Garba", "SS 1A"),
    ("t12", "Mr Olúwaṣeun Adésànyà", "SS 2A"),
    ("t13", "Mrs Nkechi Igwe", ""),
    ("t14", "Mr Musa Ɗanladi", ""),
    ("t15", "Mrs Ọmọ́tọ́lá Akínwùmí", ""),
)

#: The demo parent (`cfc.parent`) and the two children the brochure shows: one
#: in JSS 2A and one in SS 1A, both classes released.
PARENT = "Mrs Adéọlá Bámidélé"
PARENT_CHILDREN = (("JSS 2A", "Ìfẹ́olúwa Bámidélé", "female"), ("SS 1A", "Ọlámidé Bámidélé", "male"))

#: Area codes for the guardians' 555-01xx numbers: a hundred numbers each.
AREA_CODES = ("201", "202", "203", "205", "206", "207")


def staff_email(key: str) -> str:
    return f"cfc.{key}@example.com"


def guardian_phone(n: int) -> str:
    """The `n`th guardian's number, E.164: +1 201 555 0100, +1 201 555 0101 ..."""
    return f"+1{AREA_CODES[n // 100]}55501{n % 100:02d}"


@dataclass
class Child:
    class_name: str
    seat: int
    first: str
    surname: str
    sex: str
    people: str
    #: Index into the guardians list.
    guardian: int = -1

    @property
    def name(self) -> str:
        return f"{self.first} {self.surname}"


@dataclass
class Guardian:
    full_name: str
    relationship: str
    children: list


def _people(rng):
    roll = rng.randrange(100)
    for people, weight in PEOPLES:
        if roll < weight:
            return people
        roll -= weight
    return PEOPLES[-1][0]


def roll(class_names, per_class, seed):
    """`(children by class name, guardians)`, dealt the same way for the same seed.

    One guardian per family. Every ninth child after the first few is a younger
    or older sibling of a child in another class, with the same surname and the
    same guardian, so some guardians have two children here, as they do.
    """
    rng = random.Random(seed)
    taken = set()
    by_class = {name: [] for name in class_names}
    guardians = []

    # The demo parent's two children first, so they keep their seats.
    parent = Guardian(PARENT, "mother", [])
    guardians.append(parent)
    for class_name, full, sex in PARENT_CHILDREN:
        first, surname = full.split(" ", 1)
        child = Child(class_name, len(by_class[class_name]), first, surname, sex, YORUBA, guardian=0)
        by_class[class_name].append(child)
        parent.children.append(child)
        taken.add(full)

    everyone = []
    for class_name in class_names:
        while len(by_class[class_name]) < per_class:
            sibling_of = everyone[-37] if len(everyone) > 40 and len(everyone) % 9 == 0 else None
            if sibling_of is not None and sibling_of.class_name != class_name:
                people, surname = sibling_of.people, sibling_of.surname
            else:
                sibling_of = None
                people = _people(rng)
                surname = rng.choice(SURNAMES[people])
            sex = rng.choice(("female", "male"))
            first = rng.choice(FIRST[(people, sex)])
            if f"{first} {surname}" in taken:
                continue
            taken.add(f"{first} {surname}")
            child = Child(class_name, len(by_class[class_name]), first, surname, sex, people)
            if sibling_of is not None:
                child.guardian = sibling_of.guardian
                guardians[child.guardian].children.append(child)
            else:
                mother = rng.random() < 0.6
                title, gsex = ("Mrs", "female") if mother else ("Mr", "male")
                given = rng.choice(FIRST[(people, gsex)])
                guardians.append(Guardian(f"{title} {given} {surname}", "mother" if mother else "father", [child]))
                child.guardian = len(guardians) - 1
            by_class[class_name].append(child)
            everyone.append(child)
    return by_class, guardians


__all__ = [
    "AREA_CODES",
    "Child",
    "Guardian",
    "OFFICE",
    "PARENT",
    "PARENT_CHILDREN",
    "TEACHERS",
    "guardian_phone",
    "roll",
    "staff_email",
]
