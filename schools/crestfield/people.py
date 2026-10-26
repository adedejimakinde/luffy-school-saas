"""Crestfield's made-up people: staff, 300 students and their guardians.

Every name is invented from common Yoruba, Igbo and Hausa names, spelt the
way Nigerian secondary schools record them: plain letters, no tone marks, no
under-dots and no hooked letters (Oluwaseun Adebayo, Chukwuemeka Okafor, Aisha
Bello). Any match with a real person is chance.

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
        "Funmilayo", "Temitope", "Aderonke", "Folake", "Morenike", "Ayinke", "Yemisi",
        "Titilayo", "Busayo", "Omotola", "Oyinkansola", "Ibukun", "Adeola", "Ifeoluwa",
        "Tolani", "Damilola", "Iyanu", "Kehinde",
    ),
    (YORUBA, "male"): (
        "Adebayo", "Babatunde", "Segun", "Kunle", "Gbenga", "Oluwaseun", "Olaoluwa", "Ayodele",
        "Olamide", "Taiwo", "Femi", "Tunde", "Wale", "Damilare", "Ayomide", "Olamilekan",
        "Akinkunmi", "Seun",
    ),
    (IGBO, "female"): (
        "Chiamaka", "Ngozi", "Adaeze", "Chidinma", "Oluchi", "Ifeoma", "Obiageli", "Nkechi",
        "Amarachi", "Chinonso", "Uchechi",
    ),
    (IGBO, "male"): (
        "Chukwuemeka", "Obinna", "Nnamdi", "Ifeanyi", "Uchenna", "Kelechi", "Chinedu", "Chigozie",
        "Ikenna", "Somtochukwu", "Chibuzor", "Uzoma", "Ebuka",
    ),
    (HAUSA, "female"): (
        "Hauwa", "Zainab", "Halima", "Fatima", "Aisha", "Bilkisu", "Hadiza", "Saadatu", "Nafisa",
        "Khadija", "Maryam", "Rahma",
    ),
    (HAUSA, "male"): (
        "Abubakar", "Aminu", "Ibrahim", "Musa", "Yusuf", "Umar", "Sani", "Rabiu", "Danjuma",
        "Kabiru", "Bashir", "Nasiru",
    ),
}

SURNAMES = {
    YORUBA: (
        "Adeyemi", "Ogunleye", "Akinwumi", "Olatunji", "Alabi", "Ajibade", "Falola", "Ojo",
        "Adesanya", "Bamidele", "Oyelaran", "Ajayi", "Adewale", "Olaniyan", "Akinola",
        "Ogundipe", "Adeyinka", "Bolarinwa", "Osuntokun", "Adebayo",
    ),
    IGBO: (
        "Eze", "Nwankwo", "Okeke", "Anyanwu", "Nnadi", "Igwe", "Obi", "Chukwu", "Nwosu", "Ugwu",
        "Okafor", "Ezenwa", "Mbah", "Okoro",
    ),
    HAUSA: (
        "Bello", "Abdullahi", "Danjuma", "Garba", "Usman", "Lawal", "Shehu", "Aliyu", "Danladi",
        "Yakubu", "Sule", "Idris", "Kabir",
    ),
}

#: About half Yoruba, as an Abeokuta school would be, then Igbo, then Hausa.
PEOPLES = ((YORUBA, 50), (IGBO, 30), (HAUSA, 20))

#: The staff who are not class or subject teachers: `(key, role, full name)`.
#: Logins are `cfc.<key>`. The role is `accounts.models.Role`'s value.
OFFICE = (
    ("principal", "principal", "Dr Funmilayo Adeyemi"),
    ("vp", "vp_academic", "Mr Chukwuemeka Nwankwo"),
    ("admin", "admin", "Mrs Hauwa Danjuma"),
    ("bursar", "bursar", "Mr Babatunde Olatunji"),
)

#: Fifteen teachers: `(key, full name, the class they keep or "")`. Who teaches
#: what is `school.SUBJECT_TEACHERS`. `teacher` is the demo's teacher login:
#: JSS mathematics, and JSS 2B's class teacher, whose sheet is still open.
TEACHERS = (
    ("teacher", "Mrs Temitope Alabi", "JSS 2B"),
    ("t02", "Mr Obinna Eze", "SS 3A"),
    ("t03", "Mrs Ngozi Okeke", "JSS 1A"),
    ("t04", "Mr Kunle Ajayi", "SS 3B"),
    ("t05", "Miss Zainab Bello", "JSS 1B"),
    ("t06", "Mr Segun Ogunleye", "JSS 3A"),
    ("t07", "Mrs Chiamaka Anyanwu", "JSS 2A"),
    ("t08", "Mr Ibrahim Abdullahi", "SS 2B"),
    ("t09", "Mrs Aderonke Ojo", "JSS 3B"),
    ("t10", "Mr Ifeanyi Nnadi", "SS 1B"),
    ("t11", "Mrs Halima Garba", "SS 1A"),
    ("t12", "Mr Oluwaseun Adesanya", "SS 2A"),
    ("t13", "Mrs Nkechi Igwe", ""),
    ("t14", "Mr Musa Danladi", ""),
    ("t15", "Mrs Omotola Akinwumi", ""),
)

#: The demo parent (`cfc.parent`) and the two children the brochure shows: one
#: in JSS 2A and one in SS 1A, both classes released.
PARENT = "Mrs Adeola Bamidele"
PARENT_CHILDREN = (("JSS 2A", "Ifeoluwa Bamidele", "female"), ("SS 1A", "Olamide Bamidele", "male"))

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
