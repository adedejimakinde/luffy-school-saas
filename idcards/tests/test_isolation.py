"""Two schools, and one school's cards never reach the other. `docs/id-cards.md`.

Isolation here has two layers, and each has its own tests so that taking one
away leaves the other's red:

1. **The token's own schema.** A card's row is in the school that printed it.
   The verification page reads the school this *host* is, so a card from another
   school finds no row and is refused. That is the tenancy of the table.
2. **The child is this school's.** Both the print (who is on a class's roll) and
   the verification (whose card this is) check the child's membership is a
   student of **this** school, so a row that somehow named another school's
   child, by a bad import or a forged placement, still prints no card and
   verifies nothing. The tests below plant exactly that row, because it is the
   only way to ask the second layer a question the first would otherwise answer.

`TheControlTests` is the other half of the claim: each school's own card works,
at its own host, so a refusal above is isolation and not a page that refuses
everything.

The pull request records the check made against these: layer two's two filters
(`school=school` in `cards.students_of` and in `cards.verification`) removed,
these tests run and seen red, and the filters put back.
"""

from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts.models import Role
from idcards import cards
from idcards.models import IdCard, IdCardPrint
from schools.tests.tenants import connected_to

from .base import HOST, THEIR_HOST, IdCardSetUp


class TheControlTests(IdCardSetUp):
    def setUp(self):
        super().setUp()
        self.printed(self.principal)
        self.printed(self.their_staff[Role.PRINCIPAL], self.grace)

    def test_each_schools_card_opens_at_its_own_host(self):
        ada = self.verify(self.token_of(self.ada), host=HOST)
        ngozi = self.verify(self.token_of(self.ngozi, self.grace), host=THEIR_HOST)
        self.assertContains(ada, 'data-verdict="valid"')
        self.assertContains(ada, "Ada Obi")
        self.assertContains(ngozi, 'data-verdict="valid"')
        self.assertContains(ngozi, "Ngozi Ade")

    def test_each_cards_qr_points_at_its_own_schools_host(self):
        with connected_to(self.stmarys):
            ours = cards.verify_url_for("x")
        with connected_to(self.grace):
            theirs = cards.verify_url_for("x")
        self.assertEqual((ours, theirs), (f"https://{HOST}/verify/x/", f"https://{THEIR_HOST}/verify/x/"))


class LayerOneTheTokensOwnSchemaTests(IdCardSetUp):
    def setUp(self):
        super().setUp()
        self.printed(self.principal)
        self.printed(self.their_staff[Role.PRINCIPAL], self.grace)
        self.ours = self.token_of(self.ada)
        self.theirs = self.token_of(self.ngozi, self.grace)

    def test_another_schools_card_is_refused_here_and_names_nobody(self):
        response = self.verify(self.theirs, host=HOST)
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'data-verdict="unknown"', status_code=404)
        for name in ("Ngozi", "Ada", "Bola", "Grace"):
            self.assertNotContains(response, name, status_code=404)

    def test_and_the_other_way_round(self):
        response = self.verify(self.ours, host=THEIR_HOST)
        self.assertEqual(response.status_code, 404)
        for name in ("Ada", "Bola", "Ngozi", "Mary"):
            self.assertNotContains(response, name, status_code=404)

    def test_it_makes_no_difference_who_is_asking(self):
        for user in (None, self.principal, self.their_staff[Role.PRINCIPAL], self.mama):
            with self.subTest(user=getattr(user, "username", None)):
                self.assertEqual(self.verify(self.theirs, host=HOST, user=user).status_code, 404)
                self.assertEqual(self.verify(self.ours, host=THEIR_HOST, user=user).status_code, 404)

    def test_the_token_is_a_row_in_one_schema_only(self):
        with connected_to(self.stmarys):
            self.assertFalse(IdCard.objects.filter(token=self.theirs).exists())
        with connected_to(self.grace):
            self.assertFalse(IdCard.objects.filter(token=self.ours).exists())


class LayerTwoTheChildIsThisSchoolsTests(IdCardSetUp):
    """Rows that name another school's child, planted directly: no service writes them."""

    def test_a_card_row_naming_another_schools_child_verifies_nothing(self):
        with connected_to(self.stmarys):
            planted = IdCard.objects.create(
                student_membership_id=self.ngozi.pk, session=self.session, expires_on=self.today.replace(year=self.today.year + 1)
            )
            token = planted.token
        response = self.verify(token, host=HOST)
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Ngozi", status_code=404)
        self.assertNotContains(response, 'data-verdict="valid"', status_code=404)

    def test_a_placement_naming_another_schools_child_prints_no_card_for_her(self):
        with connected_to(self.stmarys):
            ClassPlacement.objects.create(
                class_group=ClassGroup.objects.get(pk=self.group_id),
                term=Term.objects.get(pk=self.terms[TermName.FIRST.value]),
                student_membership_id=self.ngozi.pk,
            )
        # Not on the roll the page offers, nor in the count, nor in the file.
        names = [c["name"] for c in self.roster(self.principal).json()["children"]]
        self.assertEqual(names, ["Ada Obi", "Bola Eze"])
        self.assertEqual(self.overview(self.principal).json()["classes"][0]["students"], 2)
        job, _ = self.printed(self.principal)
        self.assertEqual(job.card_count, 2)
        with connected_to(self.stmarys):
            self.assertFalse(IdCard.objects.filter(student_membership_id=self.ngozi.pk).exists())
        # And she cannot be asked for by id either.
        refused = self.start(self.principal, ids=[self.ngozi.pk])
        self.assertEqual(refused.status_code, 422)

    def test_a_staff_membership_is_not_a_student_and_has_no_card(self):
        staff = self.staff[Role.TEACHER].memberships.get(school=self.stmarys)
        with connected_to(self.stmarys):
            ClassPlacement.objects.create(
                class_group=ClassGroup.objects.get(pk=self.group_id),
                term=Term.objects.get(pk=self.terms[TermName.FIRST.value]),
                student_membership_id=staff.pk,
            )
        self.assertEqual(
            [c["name"] for c in self.roster(self.principal).json()["children"]], ["Ada Obi", "Bola Eze"]
        )


class ThePrintsAreEachSchoolsOwnTests(IdCardSetUp):
    def test_a_job_id_means_a_job_in_this_school_only(self):
        """Per-schema sequences: both schools' first print is job 1."""
        ours, _ = self.printed(self.principal)
        theirs, _ = self.printed(self.their_staff[Role.PRINCIPAL], self.grace)
        self.assertEqual(ours.pk, theirs.pk)
        self.assertIn(self.download(self.their_staff[Role.PRINCIPAL], ours.pk, host=HOST).status_code, (403, 404))
        self.assertIn(self.download(self.principal, theirs.pk, host=THEIR_HOST).status_code, (403, 404))

    def test_the_log_and_the_overview_are_each_schools_own(self):
        self.printed(self.principal)
        self.assertEqual(len(self.overview(self.principal).json()["prints"]), 1)
        self.assertEqual(self.overview(self.their_staff[Role.PRINCIPAL], self.grace).json()["prints"], [])
        with connected_to(self.grace):
            self.assertFalse(IdCardPrint.objects.exists())

    def test_the_file_is_in_the_school_the_message_named(self):
        from files import storage
        from files.models import StoredFile

        from idcards import printing

        job_id = self.start(self.principal).json()["id"]
        with connected_to(self.grace):
            # The worker is told St Mary's, whatever the connection was on.
            self.run_job(job_id, self.stmarys)
        with connected_to(self.stmarys):
            job = IdCardPrint.objects.get(pk=job_id)
            stored = StoredFile.objects.get(key=job.file_key)
        with connected_to(self.grace):
            self.assertFalse(StoredFile.objects.filter(key=job.file_key).exists())
        self.assertEqual(stored.schema_name, "st_marys")
        self.assertTrue(storage.path_of("st_marys", job.file_key, printing.VARIANT).exists())
        self.as_(self.their_staff[Role.PRINCIPAL])
        self.assertEqual(
            self.client.get(f"/files/{job.file_key}/{printing.VARIANT}", HTTP_HOST=THEIR_HOST).status_code, 404
        )

    def test_a_card_printed_at_one_school_carries_that_schools_name_phone_and_address_only(self):
        from idcards import render

        def sheet(school, group_id, term_id):
            with connected_to(school):
                group = ClassGroup.objects.get(pk=group_id)
                term = Term.objects.get(pk=term_id)
                kids = cards.students_of(school, group, term)
                faces = [
                    cards.face_for(k, class_name=group.name, session=term.session, expires_on=term.ends_on, by_id=None)
                    for k in kids
                ]
                return render.html_for(cards.school_face(school), group.name, faces)

        ours = sheet(self.stmarys, self.group_id, self.terms[TermName.FIRST.value])
        theirs = sheet(self.grace, self.their_group_id, self.their_terms[TermName.FIRST.value])
        self.assertIn("0803 123 4567", ours)
        self.assertNotIn("0809 999 0000", ours)
        self.assertNotIn("Grace", ours)
        self.assertNotIn("Ngozi", ours)
        self.assertIn("0809 999 0000", theirs)
        self.assertNotIn("0803 123 4567", theirs)
        self.assertNotIn("Ada Obi", theirs)
        self.assertNotIn("Palm Road", theirs)
