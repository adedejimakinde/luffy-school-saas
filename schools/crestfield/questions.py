"""A sample question bank for Crestfield, written for it from scratch.

Thirty multiple-choice questions at JSS 2 level, ten each in Mathematics,
Basic Science and English Language. Nothing here is from WAEC, NECO, JAMB or
any other exam body or past paper (`docs/cbt.md`: "Nothing from JAMB, WAEC or
NECO is seeded, scraped or copied").

**Not loaded yet.** The question bank is CBT step 3 and is not built, so there
is no table to put these in: `manage.py crestfield` says so when it runs. When
step 3 lands, the builder writes them into Crestfield's bank as its teachers
would, and nothing here changes. `tests/test_crestfield.py` checks that each
question has four different options and one answer among them.

Each question is `(text, (four options), the index of the right one)`.
"""

BANK = {
    "Mathematics": (
        ("What is 3/4 of 120?", ("80", "90", "100", "60"), 1),
        ("Simplify 2x + 5x − 3x.", ("10x", "6x", "4x", "4"), 2),
        (
            "A trader buys a bag of rice for ₦45,000 and sells it for ₦54,000. "
            "What is her profit as a percentage of what she paid?",
            ("9%", "18%", "20%", "25%"),
            2,
        ),
        ("Find y if 3y − 7 = 14.", ("5", "7", "9", "21"), 1),
        ("What is the LCM of 6 and 8?", ("12", "24", "48", "2"), 1),
        ("Round 7.348 to one decimal place.", ("7.3", "7.4", "7.35", "7.0"), 0),
        ("Two angles of a triangle are 50° and 60°. What is the third?", ("60°", "70°", "80°", "110°"), 1),
        ("Write 0.35 as a fraction in its lowest terms.", ("35/100", "7/20", "3/5", "7/2"), 1),
        ("A rectangle is 12 cm long and 5 cm wide. What is its perimeter?", ("17 cm", "34 cm", "60 cm", "24 cm"), 1),
        ("What is (−3) × (−4) − 5?", ("−17", "7", "−7", "17"), 1),
    ),
    "Basic Science": (
        ("Which part of a plant takes in water from the soil?", ("The leaves", "The flower", "The roots", "The fruit"), 2),
        ("At what temperature does pure water boil at sea level?", ("0 °C", "37 °C", "50 °C", "100 °C"), 3),
        ("Which of these is a renewable source of energy?", ("Coal", "Sunlight", "Crude oil", "Natural gas"), 1),
        ("Which organ pumps blood round the body?", ("The lungs", "The liver", "The heart", "The kidneys"), 2),
        (
            "Iron rusts when it meets both",
            ("water and oxygen", "sand and water", "oxygen and nitrogen", "heat and salt"),
            0,
        ),
        ("Which of these is a mixture?", ("Air", "Oxygen", "Pure water", "Common salt"), 0),
        ("What is the unit of force?", ("The joule", "The newton", "The watt", "The metre"), 1),
        (
            "Which cells in the blood help the body fight infection?",
            ("Red blood cells", "Platelets", "White blood cells", "Plasma"),
            2,
        ),
        ("A magnet will pick up", ("a plastic ruler", "a copper wire", "an iron nail", "a wooden pencil"), 2),
        (
            "Which gas do green plants give off when they make food in sunlight?",
            ("Carbon dioxide", "Oxygen", "Nitrogen", "Hydrogen"),
            1,
        ),
    ),
    "English Language": (
        ("Choose the word closest in meaning to BEGIN.", ("start", "finish", "delay", "forget"), 0),
        ("Fill the gap: She ___ to school every day.", ("walk", "walks", "walking", "have walked"), 1),
        ("Which of these words is a noun? The tall boy kicked the ball quickly.", ("tall", "kicked", "boy", "quickly"), 2),
        ("Choose the word opposite in meaning to GENEROUS.", ("stingy", "kind", "rich", "gentle"), 0),
        ("Which word is spelt correctly?", ("neccessary", "necessary", "necesary", "nessecary"), 1),
        ("What is the plural of CHILD?", ("childs", "childes", "children", "childrens"), 2),
        ("Fill the gap: The book is ___ the table.", ("on", "of", "with", "by"), 0),
        (
            "Which sentence is in the past tense?",
            (
                "We visit Olúmọ Rock every year.",
                "We will visit Olúmọ Rock next year.",
                "We visited Olúmọ Rock last year.",
                "We are visiting Olúmọ Rock today.",
            ),
            2,
        ),
        ("Fill the gap: Neither Bọ́lá nor her brothers ___ at home.", ("was", "were", "is", "has been"), 1),
        ("Which word is the adjective? Amaka wore a beautiful dress.", ("Amaka", "wore", "beautiful", "dress"), 2),
    ),
}

__all__ = ["BANK"]
