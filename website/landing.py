"""The public site's solution pages: one page for each thing a school searches for.

Eight pages, drawn by one template (`website/landing.html`) from the list at the
bottom of this file, so a page is its words and nothing else. Each one has its
own title and description (`website.views._PAGES` reads them from here), one
h1 with the page's main search phrase in it, a few sections under plain h2s,
screenshots of a demo school, four to six questions that are also the page's
FAQPage structured data, two or three related pages, and the two calls to
action every page ends on: "Start your free first term" and WhatsApp.

**Only what is live.** Every feature a page describes is one `website.features`
lists, or a detail of one the code has today (each is named in
`docs/website.md`, "The solution pages"). The price is `website.price`'s, written
here as `{figure}` and filled in on every request, so a changed setting changes
every page.

The writing rules are the homepage's (`website/tests/test_landing.py` holds
them): no en or em dash, no exclamation mark, no question mark outside the
questions, none of the banned words, plain sentences.

The screenshots are Crestfield's: the showcase school (Crestfield Demo College,
`schools/showcase.py`) and the sales demo (Crestfield College (Demo),
`schools/crestfield/`). Every name and figure in them is made up, and each
picture's description says it is a demo school. `scripts/landing_shots.mjs`
takes the new ones and `scripts/landing_shots.py` cuts them.
"""

import re
from dataclasses import dataclass

from django.conf import settings
from django.templatetags.static import static
from django.utils.safestring import mark_safe

from . import price
from .contact import contact


@dataclass(frozen=True)
class Shot:
    """A screenshot: its two files (1x and 2x), its size at 1x, and what it shows."""

    name: str
    alt: str
    width: int
    height: int
    #: "desk" is drawn in the browser frame, "phone" in the phone frame.
    frame: str = "desk"

    @property
    def files(self):
        small, large = (self.width, self.width * 2)
        return (f"website/shots/{self.name}-{small}.webp", small), (f"website/shots/{self.name}-{large}.webp", large)


#: Every screenshot a solution page shows. The `slide-*` files are the homepage
#: slider's (`scripts/site_shots.py`); the rest are `scripts/landing_shots.py`'s.
SHOTS = {
    "broadsheet": Shot(
        "landing-broadsheet",
        "The broadsheet for JSS 2A at Crestfield Demo College, a demo school: every student in order of "
        "class position, with tied students sharing a position, and their percentage in each subject.",
        640, 400,
    ),
    "report": Shot(
        "slide-report-desk",
        "A report sheet on the Ogun State template for a demo student at Crestfield Demo College, with "
        "continuous assessment, exam and weighted average for six subjects.",
        640, 350,
    ),
    "chain": Shot(
        "landing-chain",
        "The results page at Crestfield Demo College, a demo school: each class's result with where it "
        "is in the approval chain, from the class teacher to the principal.",
        640, 400,
    ),
    "home": Shot(
        "slide-home-desk",
        "Home dashboard for Crestfield Demo College, a demo school: 612 students, fees collected against "
        "fees expected, attendance today, and classes' results waiting for approval.",
        640, 350,
    ),
    "fees": Shot(
        "slide-fees-desk",
        "Fee collection for Crestfield Demo College, a demo school: what has been collected of what is "
        "expected this term, how many students owe, and the latest payments.",
        640, 350,
    ),
    "fee-class": Shot(
        "landing-fee-class",
        "The fee book for one class at Crestfield Demo College, a demo school: every student with what "
        "their account owes, so the bursar sees who still has to pay.",
        640, 400,
    ),
    "register": Shot(
        "slide-register-phone",
        "A teacher's phone taking the SS 1A register at Crestfield Demo College, a demo school, with two "
        "children marked absent.",
        300, 649, "phone",
    ),
    "sit": Shot(
        "landing-sit",
        "A student's CBT screen in a demo school's JSS 2 Mathematics test: the question, options A to D, "
        "the time left, the question grid, the flag for review and the calculator.",
        640, 400,
    ),
    "sit-phone": Shot(
        "landing-sit-phone",
        "The same demo CBT test on a phone: one question at a time, the time left at the top and the "
        "answer saved.",
        300, 649, "phone",
    ),
    "checker": Shot(
        "landing-checker",
        "The result checker on a demo school's own address, on a phone: the admission number and the "
        "12-digit PIN from the paper slip.",
        300, 649, "phone",
    ),
    "checker-card": Shot(
        "landing-checker-card",
        "A demo student's released report card, opened on a phone with the result checker.",
        300, 649, "phone",
    ),
    "website": Shot(
        "landing-website",
        "The website of Crestfield College (Demo), a demo school, in the Modern Campus theme: its menu, "
        "the school's facts in its colours, and the principal's message.",
        640, 400,
    ),
    "website-phone": Shot(
        "landing-website-phone",
        "The same demo school's website on a phone: its menu button and the photo album of staff at work.",
        300, 649, "phone",
    ),
    "roll-import": Shot(
        "landing-roll-import",
        "The page that imports students from a spreadsheet at Crestfield Demo College, a demo school: "
        "choose an Excel or CSV file and check every row, or start from the template.",
        640, 400,
    ),
}


@dataclass(frozen=True)
class Section:
    """One h2 and what is under it.

    `body` is paragraphs, written in HTML (a link or a `<b>` at most). `points`
    is a list drawn after them, `table` a comparison drawn after that as
    (header, rows), and `shot` a key of `SHOTS` drawn beside the words.
    """

    heading: str
    body: tuple = ()
    points: tuple = ()
    table: tuple = ()
    shot: str = ""
    after: tuple = ()


@dataclass(frozen=True)
class Landing:
    name: str
    path: str
    keyword: str
    title: str
    description: str
    h1: str
    lead: str
    sections: tuple
    faq: tuple
    related: tuple
    #: The last band's heading and line.
    closing: str = "Start your free first term."
    closing_line: str = "Leave your details and we will call you within two working days to set up your school."
    #: The pricing page also draws the price card and everything in the price.
    pricing: bool = False
    nav: str = ""


def fill(text):
    """`{figure}`, `{price}`, `{email}` and `{location}` in `text`, from today's settings."""
    details = contact()
    return text.format(figure=price.figure(), price=price.sentence(), email=details["email"],
                       location=details["location"])


LANDINGS = (
    Landing(
        name="site-result-computation",
        path="/result-computation-software/",
        keyword="result computation software for schools",
        title="Result computation software for schools | Classnode",
        description="Result computation software for Nigerian secondary schools: CA and exam totals, "
                    "grades, class positions, broadsheets and report cards. Classnode.",
        h1="Result computation software for schools that still add up by hand",
        lead="Teachers enter each CA and the exam once. Classnode works out totals, averages, grades and "
             "class positions, builds the broadsheet, and prints every report card in the class.",
        sections=(
            Section(
                "What result computation looks like in most schools",
                body=(
                    "In a typical Nigerian secondary school, from JSS 1 to SS 3, the end of term is a fortnight of "
                    "scoresheets. "
                    "Subject teachers hand in CA and exam scores on paper or in a spreadsheet. A class "
                    "teacher copies them onto a broadsheet, adds every row, works out each student's "
                    "average and position, and writes it all again onto report cards. One wrong figure in "
                    "Mathematics moves positions across the class, and nobody finds it until a parent asks.",
                    "Result processing in Classnode starts where the mark is made. The subject teacher "
                    "types each score once, on a phone or a computer, and every figure after that is "
                    "worked out from it.",
                ),
            ),
            Section(
                "From CA and exam scores to totals, grades and positions",
                body=(
                    "Your school sets its papers for the term: first test, second test, assignment and "
                    "exam, each out of the mark you choose. Teachers enter scores for their own subjects "
                    "and classes. Classnode then works out:",
                ),
                points=(
                    "each subject's total and percentage, with the letter from your own grading scale, "
                    "A1 to F9 or whatever bands your school uses;",
                    "each student's total, average and class position, if your school prints positions;",
                    "ties the way most schools rank them, 1st, 2nd, 2nd, 3rd, so two students on the same "
                    "average share the position;",
                    "the highest, lowest and class average for every subject.",
                ),
                after=(
                    "A paper that has not been marked shows as \"-\", never as zero. A student with a "
                    "paper still unmarked is shown as not ranked until it is marked, so a late score cannot "
                    "quietly push a child down the class.",
                ),
                shot="broadsheet",
            ),
            Section(
                "The broadsheet, on screen, as a PDF and in Excel",
                body=(
                    "The master broadsheet shows the whole class on one sheet: every subject's CA, exam and "
                    "percentage, then each student's total, average, position, grade counts and the "
                    "promotion decision. It opens on screen and downloads as an A3 or A4 PDF, or as an "
                    "Excel file for anyone who still wants to sort and filter. Every figure on it is the "
                    "figure the report card prints, because both come from the same results.",
                    "Until the class is released, the PDF and the Excel file both say \"Preview, not "
                    "released\", so a draft broadsheet is never mistaken for the final one.",
                ),
            ),
            Section(
                "Checked, approved and released by the right people",
                body=(
                    "Each class's result goes through your school's approval chain. The class teacher "
                    "submits it, the vice principal (academic) checks it, and the principal approves and "
                    "releases it. The vice principal or the principal can send it back to the class teacher, with a reason. Once released, the "
                    "result is locked, and every step is recorded with who took it and when.",
                ),
                shot="chain",
            ),
            Section(
                "Report cards printed for the whole class",
                body=(
                    "Classnode prints the Standard report card or the Ogun State report sheet, with your "
                    "crest, the class teacher's comment and the principal's remark. A whole class prints as "
                    "one PDF. A preview stamp shows on every card until the results are released.",
                    "After release, parents see their own child's report card online, or use the "
                    '<a href="/school-result-checker/">online result checker</a> with the PIN on a paper '
                    "slip. If you are still on spreadsheets, our honest "
                    '<a href="/excel-vs-school-software/">Excel result template comparison</a> shows where '
                    "each one fits.",
                ),
                shot="report",
            ),
        ),
        faq=(
            ("Can we use our own grading scale?",
             "Yes. The default scale runs from A1 to F9, and your school can change the bands. Every "
             "grade on the broadsheet and the report card follows your scale."),
            ("How does Classnode work out class position?",
             "Students are ranked on their average across the subjects they finished. Two students on the "
             "same average share a position, so the order reads 1st, 2nd, 2nd, 3rd. If your school does "
             "not print positions, switch it off and no card or broadsheet shows one."),
            ("What happens when a teacher has not entered a score?",
             "The paper shows as \"-\" and is never counted as zero. That subject has no total for the "
             "student until it is marked, and the student is shown as not ranked until then."),
            ("Can we download the broadsheet in Excel?",
             "Yes. The master broadsheet downloads as an Excel file or as an A3 or A4 PDF. Before release "
             "both are marked as a preview."),
            ("Who can change results after they are released?",
             "Nobody can edit a released result. It is locked at release, so the figures parents see are "
             "the figures the principal approved."),
        ),
        related=("site-school-result-checker", "site-excel-vs-software", "site-cbt"),
    ),
    Landing(
        name="site-cbt",
        path="/cbt-software-for-schools/",
        keyword="CBT software for schools in Nigeria",
        title="CBT software for schools in Nigeria | Classnode",
        description="CBT software for schools in Nigeria: question banks, timed computer based tests on "
                    "phones or computers, automatic marking and scores into CA. Classnode.",
        h1="CBT software for schools in Nigeria, set by your own teachers",
        lead="Your teachers write the questions, the principal approves the test, and students sit it on "
             "a phone or a computer. Classnode marks it and sends the scores into CA.",
        sections=(
            Section(
                "Computer based tests your school runs itself",
                body=(
                    "Your SS 3 students will sit the UTME on a computer, and many schools want them used "
                    "to the screen long before then. Most schools have "
                    "a computer room with too few machines, a generator that does not always come on, "
                    "and teachers who already mark more scripts than they can manage.",
                    "Classnode's CBT is built for that school. It runs in the browser, on the computers "
                    "you have and on students' phones, and it keeps working through a network drop or a "
                    "power cut.",
                ),
            ),
            Section(
                "Question banks by subject and class",
                body=(
                    "Teachers keep a question bank for each subject and class level they teach. They write "
                    "multiple choice questions with options A to D, and build a test from the bank: how "
                    "many questions, how long, and which classes sit it. Teachers see only their own "
                    "subjects and classes. Questions are your school's own, and nothing is copied from any "
                    "exam body.",
                    "The principal or the vice principal approves a test before it opens, or sends it back "
                    "to the teacher.",
                ),
            ),
            Section(
                "An online exam screen students already know",
                body=(
                    "Students sign in with the test code, their admission number and an exam PIN printed "
                    "on a slip, so nobody needs an email address or a password. The test screen works like "
                    "the ones they will meet in external exams:",
                ),
                points=(
                    "a timer that keeps running for the whole test;",
                    "a question grid to jump between questions, and a flag to mark one for review;",
                    "a calculator, when the teacher switches it on for the test;",
                    "answers saved as the student goes, through a network drop.",
                ),
                after=(
                    "If a computer goes off in a power cut, the student signs in again on the same or "
                    "another computer and carries on with the time they had left. A teacher, an exam "
                    "officer or the administrator can give one student extra minutes, with a reason that "
                    "is recorded.",
                ),
                shot="sit",
            ),
            Section(
                "Online exams for secondary schools on any device",
                body=(
                    "The same test runs on a desktop in the computer room and on a phone. On a phone it "
                    "shows one question at a time, with the timer at the top, so a school can run a test "
                    "for a whole class without enough computers for everyone.",
                ),
                shot="sit-phone",
            ),
            Section(
                "Marked by the computer, sent into CA",
                body=(
                    "The computer marks every script the moment it is submitted. The teacher sends the "
                    "scores into a CA column on the marking sheet, and from there they go through the same "
                    'approval chain as every other score, into the <a href="/result-computation-software/">'
                    "result computation</a> and onto the report card. A student who did not sit gets no "
                    "mark, never a zero.",
                    "When the test is released, students and parents see the score. Teachers get item "
                    "analysis, which shows how each question did, so a question most of the class got "
                    "wrong is easy to find and teach again.",
                ),
            ),
        ),
        faq=(
            ("Do we need a computer for every student?",
             "No. A test runs on a computer or a phone, so students without a computer can sit it on a "
             "phone in class."),
            ("What happens if the light goes off during a test?",
             "Answers are saved as the student goes. When the power comes back, the student signs in on "
             "the same or another computer and continues with the time they had left."),
            ("How do students sign in to a CBT test?",
             "With the test code, their admission number and the exam PIN printed on their slip. The "
             "principal, an exam officer or the administrator prints the slips for each class."),
            ("Can CBT scores count towards CA?",
             "Yes. The teacher sends the marked scores into a CA column, and they go through the school's "
             "approval chain like every other score."),
            ("Who writes the questions?",
             "Your own teachers, in a question bank for each subject and class. Nothing is copied from "
             "JAMB, WAEC or NECO, and the principal or vice principal approves each test before it opens."),
        ),
        related=("site-result-computation", "site-school-result-checker", "site-pricing"),
    ),
    Landing(
        name="site-school-result-checker",
        path="/school-result-checker/",
        keyword="online result checker for schools",
        title="Online result checker for schools | Classnode",
        description="An online result checker for your school: parents check results with the admission "
                    "number and a PIN from a paper slip, on any phone. Classnode.",
        h1="An online result checker for schools, on your school's own address",
        lead="After you release results, parents check their child's report card online with the "
             "admission number and a result PIN printed on a paper slip. No account and no app.",
        sections=(
            Section(
                "Parents check results online without an account",
                body=(
                    "Many families will never create an account or remember a password, and some share one "
                    "phone between several people. The result checker is for them. It sits on your school's "
                    "own address, at <b>yourschool.classnode.co/check</b>, and asks for two things: the "
                    "child's admission number and the PIN on their slip.",
                    "Type them in and the child's released report card opens, for that term, on any phone "
                    "with a browser. Nothing is installed and nothing is stored on the phone.",
                ),
                shot="checker",
            ),
            Section(
                "Result PIN slips, printed by the school",
                body=(
                    "Once a class is released, the principal or an administrator prints the PIN slips for "
                    "the whole class as one PDF: one slip per child, with the name, the admission number "
                    "and a 12-digit PIN printed in three groups of four. The slips go home in the child's "
                    "bag with the term's letters.",
                ),
                points=(
                    "A PIN opens one child's card and nothing else.",
                    "A PIN keeps working until the next session starts, so parents can check again.",
                    "A lost slip is reprinted by admission number, and the old PIN stops working.",
                    "Printing again for a class prints only the children who have no slip yet.",
                ),
                after=(
                    "PINs are stored as codes nobody can read back, and the slip PDF is never saved on the "
                    "server, so the slips you print are the only copies. Every press is recorded, with who "
                    "printed the slips and when, so a school can always see which slips are in families' "
                    "hands.",
                ),
            ),
            Section(
                "Safe for the child, simple for the parent",
                body=(
                    "A wrong admission number, a wrong PIN and an old PIN all get the same answer, so "
                    "the checker never tells a stranger whether a child exists. After too many wrong tries "
                    "the next one waits a short while, and the wait ends by itself. Nobody is locked out "
                    "for good, which matters when an admission number is written on every exercise book.",
                    "Parents only see results you have approved and released, never a draft. If your "
                    "school withholds a card for unpaid fees, the checker shows that it is withheld and "
                    "who to call, not the card.",
                ),
                shot="checker-card",
            ),
            Section(
                "Parents with a phone number on record can sign in instead",
                body=(
                    "A parent whose phone number or email your school has verified can sign in with a "
                    "one-time code instead of a PIN, and see every child's released results in one place. "
                    "The checker and the parent sign-in show the same report card, so the two can never "
                    "disagree.",
                    "Both read the results your teachers entered and your principal approved in Classnode's "
                    '<a href="/result-computation-software/">result computation software</a>. Fees, '
                    'withholding and receipts are on the <a href="/school-fees-management-software/">'
                    "fees management</a> page.",
                ),
            ),
        ),
        faq=(
            ("How do parents check results online?",
             "They open the result checker on your school's own address, type the child's admission "
             "number and the PIN from the paper slip, and the released report card opens on the phone."),
            ("What is on a result PIN slip?",
             "The child's name, admission number and a 12-digit PIN in three groups of four. The principal "
             "or an administrator prints a whole class's slips as one PDF after release."),
            ("How long does a result PIN last?",
             "Until the next session starts, so parents can check the card more than once. A lost slip is "
             "reprinted by admission number, and the old PIN stops working."),
            ("Can parents see results before the principal releases them?",
             "No. The checker opens only released results. A class still being checked or approved shows "
             "nothing."),
            ("Can we stop a child's result showing while fees are owed?",
             "Yes, if your school switches withholding on. The principal or the bursar withholds the card, "
             "and the checker tells the family it is withheld and who to call."),
        ),
        related=("site-result-computation", "site-fees", "site-cbt"),
    ),
    Landing(
        name="site-pricing",
        path="/pricing/",
        keyword="school management software price in Nigeria",
        title="School management software price in Nigeria | Classnode",
        description="School management software price in Nigeria, from Classnode. {price}",
        h1="School management software price in Nigeria, in one line",
        lead="The first term is free, then {figure} per student, per term. No setup fee, and everything "
             "below is in the price.",
        pricing=True,
        nav="pricing",
        sections=(
            Section(
                "How the price works",
                body=(
                    "Your school pays for the students on its roll each term, and nothing else. There is no "
                    "setup fee, no charge per teacher or per login, and no separate price for CBT, the "
                    "result checker or your school website.",
                ),
                points=(
                    "<b>First term free.</b> Your school's first term on Classnode costs nothing, with every "
                    "feature switched on.",
                    "<b>Then {figure} per student, per term.</b> A school with 300 students pays for 300.",
                    "<b>No setup fee.</b> We add your classes, students and staff from your lists and walk "
                    "your team through it, at no charge.",
                ),
            ),
            Section(
                "What a proprietor is paying for",
                body=(
                    "School management software price in Nigeria is often quoted as a setup fee, a yearly "
                    "licence and extras on top. We chose one figure a proprietor can work out on a "
                    "calculator before the meeting ends. Multiply your students by {figure}, and that is "
                    "the term's cost, after a free first term.",
                    "For that, the principal sees the whole school on one dashboard, the bursar sees who "
                    "has paid, teachers enter scores and registers on their phones, and parents check "
                    "results online.",
                ),
                shot="home",
            ),
            Section(
                "Before you pay anything",
                body=(
                    "Use the free first term with your real classes. Enter one term's scores, take the "
                    "registers, bill the fees and release results. If it does not work for your school, "
                    "you have paid nothing, and your records are not trapped: the broadsheet downloads in "
                    "Excel and every report card as a PDF.",
                    'Schools in Lagos can ask for <a href="/school-management-software-lagos/">setup and '
                    "training in person</a>. Elsewhere, we set up with you by phone, WhatsApp and email.",
                ),
            ),
        ),
        faq=(
            ("How much does Classnode cost?",
             "The first term is free, then {figure} per student, per term. There is no setup fee."),
            ("Is there a setup fee?",
             "No. We add your classes, students and staff and walk your team through it at no charge."),
            ("Do we pay for teachers and parents too?",
             "No. The price is per student on your roll. Staff and parent logins are not charged."),
            ("Are CBT and the school website extra?",
             "No. CBT, the result checker, fees, registers, report cards and your school website are all "
             "in the same price."),
            ("What happens after the free first term?",
             "From your second term, your school pays {figure} per student, per term. Your broadsheets "
             "download in Excel and your report cards as PDFs at any time."),
        ),
        related=("site-fees", "site-lagos", "site-school-website"),
    ),
    Landing(
        name="site-fees",
        path="/school-fees-management-software/",
        keyword="school fees management software",
        title="School fees management software | Classnode",
        description="School fees management software for Nigerian schools: bills by class, an account "
                    "number for each child, receipts and a debtors list. Classnode.",
        h1="School fees management software for the bursar's office",
        lead="Bill every class, see each payment land on the right child, print or email the receipt, "
             "and know who still owes without matching bank alerts to names.",
        sections=(
            Section(
                "Fee tracking without the alert-matching",
                body=(
                    "In most schools, fee tracking means a bursar with a bank app, a pile of tellers and a "
                    "notebook. A parent pays by transfer with a narration that says \"school fees\", and "
                    "somebody has to work out which child it was for. By the third week of term, nobody is "
                    "sure who has paid.",
                    "With Classnode, each child has their own fee account and their own account number. A "
                    "parent pays by bank transfer, the way they already do, and the payment lands on that "
                    "child's record.",
                ),
                shot="fees",
            ),
            Section(
                "Bills by class and term",
                body=(
                    "The bursar sets the term's fee items for each class: tuition, and any levies your "
                    "school charges. Billing a class charges every child placed in it, once. A child who "
                    "moves class mid-term is never charged the same fee twice. Discounts and concessions "
                    "are given child by child, each with a reason.",
                ),
            ),
            Section(
                "Payments, receipts and corrections",
                body=(
                    "Payments by transfer to a child's account number are recorded for you. Cash, POS, "
                    "cheque and transfers into the school's main account are recorded by the bursar, and a "
                    "bank transfer names its teller or transfer reference.",
                ),
                points=(
                    "Every payment has a numbered receipt, printed with the child's name and admission "
                    "number as they were when it was paid.",
                    "If your school switches it on, the receipt is emailed to the parent the moment the "
                    "payment is recorded.",
                    "A payment cannot be edited or deleted. A mistake is reversed with a reason, so the "
                    "mistake and the fix both stay in the record.",
                    "Pressing save twice records one payment, not two.",
                ),
            ),
            Section(
                "A debtors list you can trust",
                body=(
                    "For every class, the fee book lists each child with what their account owes, is in "
                    "credit, or that nothing is owed. The school's total outstanding, and how much of it "
                    "is this term's, is on the dashboard beside what was collected and what was expected. "
                    "A family in credit is never counted against one that owes.",
                    "The bursar can send a fee reminder to the families who owe, each stating what that "
                    "child's account shows. The proprietor can get a daily summary of money collected and "
                    "billed.",
                ),
                shot="fee-class",
            ),
            Section(
                "Who sees the money",
                body=(
                    "The bursar and the administrator record payments. The principal and the vice principal "
                    "can read the fee book but not change it. Teachers see nothing about fees. If your "
                    "school chooses, the principal or the bursar can withhold a child's report card online "
                    "while fees are owed, and the "
                    '<a href="/school-result-checker/">result checker</a> tells the family who to call.',
                    "Every payment, discount and reversal records who entered it and when, so when a parent "
                    "questions a figure, the bursar can show exactly how the balance was reached.",
                    'Fees are in the same <a href="/pricing/">price</a> as results, CBT and your website: '
                    "{figure} per student, per term, after a free first term.",
                ),
            ),
        ),
        faq=(
            ("How do parents pay school fees?",
             "By bank transfer, the way they already do. Each child has their own account number, so the "
             "payment shows on that child's record."),
            ("Can we still record cash and POS payments?",
             "Yes. The bursar records cash, POS, cheque and bank transfers by hand, and a transfer names "
             "its teller or transfer reference."),
            ("Does Classnode give receipts?",
             "Yes. Every payment has a numbered receipt. If your school switches it on, the receipt is "
             "emailed to the parent as soon as the payment is recorded."),
            ("Can we see a list of students who owe?",
             "Yes. The fee book shows every child in a class with what their account owes, and the "
             "dashboard shows the school's total outstanding."),
            ("What if a payment was recorded wrongly?",
             "It is reversed with a reason and recorded again. Nothing is edited or deleted, so the record "
             "shows both the mistake and the correction."),
        ),
        related=("site-pricing", "site-school-result-checker", "site-lagos"),
    ),
    Landing(
        name="site-school-website",
        path="/school-website-design/",
        keyword="school website design in Nigeria",
        title="School website design in Nigeria | Classnode",
        description="School website design in Nigeria with the portal built in: your colours, a slideshow, "
                    "up to 20 pages and an editor your staff can use. Classnode.",
        h1="School website design in Nigeria, with the school portal built in",
        lead="Your school gets its own website in the Modern Campus theme, in your colours, on the same "
             "address as your school portal. Your staff edit it and the principal approves each change.",
        sections=(
            Section(
                "A school website with a portal, in one place",
                body=(
                    "Many schools pay a designer for a website, then pay someone else for a result portal, "
                    "and end up with two addresses, two logins and a site nobody updates. On Classnode the "
                    "website and the portal are one. Parents read about the school, then sign in or check "
                    "results from the same address, <b>yourschool.classnode.co</b>.",
                    "The sign-in pages and the portal carry your crest, name and colours too, so a parent "
                    "never wonders whether they are in the right place.",
                ),
                shot="website",
            ),
            Section(
                "What your school website includes",
                body=(
                    "The Modern Campus theme is built for Nigerian schools: a large slideshow at the top, "
                    "your colours throughout, and pages that open quickly on a cheap phone and a slow "
                    "connection. Your site can have:",
                ),
                points=(
                    "up to 20 pages in all: the six standard pages and 14 pages of your own;",
                    "a slideshow on the home page, pictures on your pages, and photo albums in the gallery;",
                    "a hero video at the top of the home page;",
                    "a map on the contact page, so visitors find the gate;",
                    "the principal's message, your motto and the school's facts.",
                ),
                shot="website-phone",
            ),
            Section(
                "Edited by your staff, approved by the principal",
                body=(
                    "You do not need a web designer to keep the site current. The principal, or an "
                    "administrator the principal allows, opens the website editor, changes a page, and "
                    "sees a preview of exactly how it will look. The change goes live only when the "
                    "principal approves it, so nothing appears on the school's website without the "
                    "principal's say, and an earlier version can be put back.",
                    "Pictures are resized for you, so a large photo from a phone does not slow the page "
                    "down for parents on mobile data.",
                    "Every change is kept in the website's log, with who made it and who published it, so "
                    "the school always knows how a page came to say what it says.",
                ),
            ),
            Section(
                "An app for staff and parents, with no app store",
                body=(
                    "The school's portal installs from the browser onto a phone or a computer, so staff "
                    "and parents can add it to the home screen beside their other apps. There is nothing to "
                    "download from an app store and nothing to update.",
                    "Inside the portal is everything else Classnode does: "
                    '<a href="/result-computation-software/">results and report cards</a>, CBT, registers '
                    'and <a href="/school-fees-management-software/">school fees</a>.',
                ),
            ),
            Section(
                "What it costs",
                body=(
                    "The website is in the same price as everything else: the first term free, then "
                    "{figure} per student, per term, with no setup fee and no separate design fee. See the "
                    '<a href="/pricing/">pricing page</a> for everything included.',
                    "Your website lives on your school's Classnode address, beside the portal, so there is "
                    "one address to print on letters and the school gate.",
                ),
            ),
        ),
        faq=(
            ("Is the website separate from the school portal?",
             "No. The website and the portal share your school's address, so parents read about the school "
             "and sign in or check results in the same place."),
            ("How many pages can our school website have?",
             "Up to 20: the six standard pages and 14 of your own, with pictures, albums, a hero video and "
             "a map."),
            ("Can our staff update the website themselves?",
             "Yes. The principal, or an administrator the principal allows, edits pages in the website "
             "editor and sees a preview. A change goes live when the principal approves it."),
            ("Is there a design fee for the website?",
             "No. The website is in Classnode's price, the first term free and then {figure} per student, "
             "per term, with no setup fee."),
            ("Does the school website work on phones?",
             "Yes. The Modern Campus theme is built for phones first, and pictures are resized so pages "
             "open quickly on mobile data."),
        ),
        related=("site-pricing", "site-school-result-checker", "site-lagos"),
    ),
    Landing(
        name="site-lagos",
        path="/school-management-software-lagos/",
        keyword="school management software in Lagos",
        title="School management software in Lagos | Classnode",
        description="School management software in Lagos from a Lagos team: setup and staff training at "
                    "your school, and support by phone and WhatsApp. Classnode.",
        h1="School management software in Lagos, from a team in Lagos",
        lead="Classnode is based in {location}. For a Lagos school, that means we can come to you: to set "
             "up, to train your staff in the staff room, and to sort things out face to face.",
        sections=(
            Section(
                "Based in Lagos, Nigeria",
                body=(
                    "Classnode Edtech Limited is based in {location}. For a school in Lagos, that means "
                    "Classnode is set up by people who can visit, in the same city and the same traffic as "
                    "you, and who can be at your gate when something needs looking at in person.",
                    "We work with secondary schools across Nigeria, and Lagos schools get one thing the "
                    "others cannot: a visit.",
                ),
            ),
            Section(
                "In-person setup at your school",
                body=(
                    "Setup starts with your lists. Send us your class lists and fee items, as an Excel or "
                    "CSV file if you have one, and we add your classes, students and staff. For a "
                    "Lagos school we can then come to the school to finish it with you: the session and "
                    "term, your papers and grading scale, your report card, and your fee items for the "
                    "bursar.",
                    "We arrange the visit around your school day, so setup does not take teachers out of "
                    "lessons. Many schools choose the days before resumption, when staff are already in for "
                    "meetings and the timetable is being drawn up.",
                    "There is no setup fee, in Lagos or anywhere else.",
                ),
            ),
            Section(
                "Training in your staff room",
                body=(
                    "Software only helps if the staff use it, and staff learn fastest from a person standing "
                    "beside them. In a Lagos school we train in person, in small groups, on the phones your "
                    "teachers already carry:",
                ),
                points=(
                    "class teachers on taking the register, and subject teachers on entering CA and exam "
                    "scores;",
                    "the vice principal and the principal on checking, approving and releasing results;",
                    "the bursar on billing classes, recording payments and receipts;",
                    "the office on admitting students and printing result PIN slips.",
                ),
                after=(
                    "Teachers who miss the session can follow the same steps on their phones afterwards, "
                    "because every screen they use is the one they were shown.",
                ),
                shot="register",
            ),
            Section(
                "Built for a Lagos school day",
                body=(
                    "A Lagos school runs on phones, mobile data and a generator. Classnode works in the "
                    "browser on a cheap Android phone, and pages are kept light for a slow connection. "
                    "If the network drops in the middle of the register or score entry, it waits on the "
                    "phone and sends when the connection comes back. Parents pay fees by bank transfer "
                    "into their child's own account number.",
                    "Lagos schools print the Standard report card, with your crest, your grading scale and "
                    "the class teacher's and principal's remarks.",
                ),
            ),
            Section(
                "Local support by phone, WhatsApp and email",
                body=(
                    "When something does not look right, call or message us on WhatsApp and speak to the "
                    "team in Lagos, or write to {email}. If it needs a visit, we can come.",
                    'Everything is in one <a href="/pricing/">price</a>: the first term free, then {figure} '
                    "per student, per term, with no setup fee. Lagos schools often start with "
                    '<a href="/result-computation-software/">results</a> and '
                    '<a href="/school-fees-management-software/">fees</a>, the two jobs that take the most '
                    "evenings.",
                ),
            ),
        ),
        faq=(
            ("Where is Classnode based?",
             "In Lagos, Nigeria. Classnode Edtech Limited works with secondary schools across Nigeria."),
            ("Do you set up in person in Lagos?",
             "Yes. For a school in Lagos we can come to the school to finish setup with you and train your "
             "staff. There is no setup fee."),
            ("Can you train our teachers at the school?",
             "Yes. In Lagos we train staff in person, in small groups, on the phones they already use: "
             "registers, scores, approvals, fees and PIN slips."),
            ("How do we get support?",
             "Call or message us on WhatsApp, or email hello@classnode.co. For a Lagos school, we can visit "
             "if it needs one."),
            ("Does it work outside Lagos?",
             "Yes. Classnode works for secondary schools across Nigeria. Outside Lagos we set up and train "
             "by phone, WhatsApp and email."),
        ),
        related=("site-pricing", "site-result-computation", "site-fees"),
    ),
    Landing(
        name="site-excel-vs-software",
        path="/excel-vs-school-software/",
        keyword="Excel result template vs school software",
        title="Excel result template vs school software | Classnode",
        description="Excel result template vs school software, honestly: what a spreadsheet does well, where "
                    "it breaks for a whole school, and how to move. Classnode.",
        h1="Excel result template vs school software: an honest comparison",
        lead="Many good schools run their results on an Excel template, and some should keep doing so. "
             "Here is what Excel does well, where it starts to break, and what school software changes.",
        sections=(
            Section(
                "What an Excel result template does well",
                body=(
                    "A well built Excel result template is a real tool. It is cheap, because most schools "
                    "already have Excel. Somebody in the office understands it. It adds up a row, works "
                    "out an average, ranks a class with RANK, and prints. For one class teacher with one "
                    "class and a laptop, it does the job.",
                    "It is also yours. You can add a column the night before results go out, and nobody "
                    "has to approve it. That freedom is the reason many schools stay with Excel, and it is "
                    "a fair one.",
                ),
            ),
            Section(
                "Where the spreadsheet starts to break",
                body=(
                    "The trouble starts when a whole school runs on copies of one file. The problems are "
                    "rarely Excel's fault. They come from people sharing a file that was built for one:",
                ),
                points=(
                    "<b>Copies.</b> Each class teacher has a copy, then a copy of the copy. By the end of "
                    "term nobody knows which file is final.",
                    "<b>Formulas.</b> One pasted value over a formula, or a range that stops one row short, "
                    "gives a wrong total that looks right.",
                    "<b>Blank and zero.</b> A score still to be entered counts as zero in an average, so a child "
                    "drops down the class until somebody notices.",
                    "<b>Ties.</b> Two students on the same average are ranked in whatever order the sheet "
                    "found them, unless someone writes the formula with care.",
                    "<b>No approval.</b> Anyone with the file can change a score after the principal has "
                    "seen it, and there is no record of who did.",
                    "<b>Retyping.</b> Report cards are filled in by hand or with a mail merge, from figures "
                    "copied once more.",
                ),
            ),
            Section(
                "Excel and school software side by side",
                table=(
                    ("", "Excel result template", "Classnode"),
                    (
                        ("Cost", "Usually already paid for", "First term free, then {figure} per student, per term"),
                        ("Entering scores", "One file per class, on a laptop", "Each teacher on their own phone, for their own subjects"),
                        ("A score not entered", "Counts as zero unless the formula checks", "Shows as \"-\", never zero"),
                        ("Class position", "Depends on the formula", "Ties shared: 1st, 2nd, 2nd, 3rd"),
                        ("Approval", "None, or an email", "Class teacher, vice principal, principal"),
                        ("After release", "The file can still be edited", "Locked"),
                        ("Report cards", "Typed or mail merged", "Printed for the whole class as one PDF"),
                        ("Parents", "A printed card", "Online, or with a result PIN"),
                        ("Changing the layout", "Any time, by anyone", "From the report cards Classnode prints"),
                    ),
                ),
            ),
            Section(
                "What school software changes",
                body=(
                    "In Classnode each teacher enters scores for their own subjects, once, and every figure "
                    "after that is worked out from them: totals, grades on your own scale, averages and "
                    "class positions. The broadsheet and the report card are drawn from the same results, so "
                    "they cannot disagree. Each class goes from the class teacher to the vice principal to "
                    "the principal, and is locked when it is released.",
                    "You do lose some freedom. You cannot add a new column the night before, and the report "
                    "card is the Standard report card or the Ogun State report sheet. If your school depends on a custom "
                    "sheet nobody else prints, Excel may still suit you better.",
                ),
                shot="broadsheet",
            ),
            Section(
                "Moving from Excel without starting again",
                body=(
                    "You do not have to retype your students. Send us your class lists as an Excel or CSV "
                    "file and we import them into your classes, or the office imports them itself: the "
                    "file is checked row by row, any problem names its row, and nothing is admitted until "
                    "the whole file is right. Sending the same file twice admits nobody twice.",
                    "And Excel does not go away. The master broadsheet still downloads as an Excel file "
                    'when you want one. Read more about <a href="/result-computation-software/">result '
                    'computation</a> or see the <a href="/pricing/">price</a>.',
                ),
                shot="roll-import",
            ),
        ),
        faq=(
            ("Is an Excel result template good enough for a school?",
             "For one class teacher and one class, often yes. It gets harder when many teachers share copies "
             "of one file, because totals, blanks, ties and late changes are easy to get wrong."),
            ("Why does a blank score matter in Excel?",
             "Most averages treat a blank cell as zero or skip it without saying so. A child can drop down "
             "the class because a paper was still to be entered. Classnode shows an unmarked paper as \"-\" and "
             "does not rank the child on that subject."),
            ("Can we import our students from Excel?",
             "Yes. Send your class lists as an Excel or CSV file and they are imported into your classes. "
             "Each problem is shown with its row, and nothing is admitted until the file is right."),
            ("Can we still get our results in Excel?",
             "Yes. The master broadsheet downloads as an Excel file, as well as an A3 or A4 PDF."),
            ("When should a school stay with Excel?",
             "When it depends on a custom report sheet nobody else prints, or has one class teacher who "
             "does every result. Classnode prints the Standard and the Ogun State report cards."),
        ),
        related=("site-result-computation", "site-pricing", "site-school-result-checker"),
    ),
)

BY_NAME = {landing.name: landing for landing in LANDINGS}

#: The footer's and the homepage's "Solutions": each page's short name and, for
#: the homepage, one line, in this order.
SOLUTIONS = (
    ("site-result-computation", "Result computation", "CA and exam scores to broadsheets, positions and report cards."),
    ("site-cbt", "CBT software", "Tests set by your teachers and marked by the computer."),
    ("site-school-result-checker", "Result checker", "Parents check released results with a PIN slip."),
    ("site-fees", "School fees", "Bills, account numbers, receipts and who still owes."),
    ("site-school-website", "School website", "Your school's own website, with the portal built in."),
    ("site-pricing", "Pricing", "The first term free, then {figure} per student, per term."),
    ("site-lagos", "Schools in Lagos", "Setup and staff training in person, from our Lagos team."),
    ("site-excel-vs-software", "Excel vs software", "What a spreadsheet does well, and where it breaks."),
)


def pages():
    """Each solution page's route name and (title, description), in the order above."""
    return {landing.name: (landing.title, landing.description) for landing in LANDINGS}


def faq(landing):
    """The page's questions with today's price in them, as (question, answer in HTML)."""
    return [(fill(q), fill(a)) for q, a in landing.faq]


def drawn(section, index):
    """A section as the template draws it: today's price in its words, its
    screenshot's files, and which side of the words the picture sits on."""
    shot = SHOTS[section.shot] if section.shot else None
    picture = None
    if shot:
        (small, small_width), (large, large_width) = shot.files
        picture = {
            "src": static(small),
            "srcset": f"{static(small)} {small_width}w, {static(large)} {large_width}w",
            "width": shot.width,
            "height": shot.height,
            "alt": shot.alt,
            "phone": shot.frame == "phone",
        }
    header, rows = section.table or ((), ())
    return {
        "heading": fill(section.heading),
        "body": [mark_safe(fill(p)) for p in section.body],
        "points": [mark_safe(fill(p)) for p in section.points],
        "after": [mark_safe(fill(p)) for p in section.after],
        "header": header,
        "rows": [[fill(cell) for cell in row] for row in rows],
        "picture": picture,
        "flip": index % 2 == 1,
        "tint": index % 2 == 1,
    }


def whatsapp():
    """The support phone's WhatsApp chat address (`settings.SITE_PHONE`), or "" without one."""
    digits = re.sub(r"\D", "", settings.SITE_PHONE)
    return f"https://wa.me/{digits}" if digits else ""
