import json
from unittest.mock import patch

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.sessions.models import Session
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase

from .models import User
from .tests import VALID


class AccountPersistenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.encoded = make_password(VALID["password"])

    def fields(self, email):
        return {"name": VALID["name"], "email": email, "role": "BUYER", "password": self.encoded}

    def test_fields_identifiers_and_framework_hash(self):
        first = User.objects.create_user(**{**VALID, "email": "  ANA@EXAMPLE.COM  "})
        second = User.objects.create_user(**{**VALID, "email": "seller@example.com", "role": "SELLER"})
        self.assertNotEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertEqual(first.email, "ana@example.com")
        self.assertEqual(first.name, VALID["name"])
        self.assertEqual(first.role, "BUYER")
        self.assertTrue(check_password(VALID["password"], first.password))
        self.assertFalse(check_password(VALID["password"].strip(), first.password))
        self.assertNotEqual(first.password, VALID["password"])

    def test_normalization_on_direct_create_save_and_bulk_create(self):
        created = User.objects.create(**self.fields("  CREATED@Example.COM  "))
        saved = User(**self.fields("\tSAVED@Example.COM\n"))
        saved.save()
        bulk = User(**self.fields("\u2003BULK@EXAMPLE.COM\u2003"))
        User.objects.bulk_create([bulk])
        for user, expected in ((created, "created@example.com"), (saved, "saved@example.com"), (bulk, "bulk@example.com")):
            user.refresh_from_db()
            self.assertEqual(user.email, expected)
        self.assertEqual(created.email, "created@example.com")

    def test_normalization_on_updates_and_unicode_email(self):
        user = User.objects.create(**self.fields("before@example.com"))
        User.objects.filter(pk=user.pk).update(email="  AFTER@EXAMPLE.COM  ")
        user.refresh_from_db()
        self.assertEqual(user.email, "after@example.com")
        user.email = "\tFINAL@EXAMPLE.COM\n"
        User.objects.bulk_update([user], ["email"])
        user.refresh_from_db()
        self.assertEqual(user.email, "final@example.com")
        user.email = "  ANA@\u00d1ANDU.COM  "
        user.save(update_fields=["email"])
        user.refresh_from_db()
        self.assertEqual(user.email, "ana@\u00f1andu.com")

    def test_database_uniqueness_for_all_orm_creation_routes(self):
        User.objects.create(**self.fields("ana@example.com"))
        attempts = [
            lambda: User.objects.create_user(**{**VALID, "email": " ANA@Example.COM "}),
            lambda: User.objects.create(**self.fields("ANA@EXAMPLE.COM")),
            lambda: User(**self.fields("\tAna@Example.Com\n")).save(),
            lambda: User.objects.bulk_create([User(**self.fields(" ANA@EXAMPLE.COM "))]),
        ]
        for attempt in attempts:
            with self.assertRaises(IntegrityError), transaction.atomic():
                attempt()
        self.assertEqual(User.objects.count(), 1)
        # The connection remains usable after each rejected insertion.
        self.assertEqual(User.objects.get().email, "ana@example.com")

    def test_database_rejects_duplicate_update_and_invalid_bulk_role(self):
        User.objects.create(**self.fields("ana@example.com"))
        other = User.objects.create(**self.fields("other@example.com"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=other.pk).update(email=" ANA@EXAMPLE.COM ")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(**{**self.fields("bad@example.com"), "role": "ADMIN"})])
        other.refresh_from_db()
        self.assertEqual(other.email, "other@example.com")
        self.assertEqual(User.objects.count(), 2)

    def test_constraints_apply_to_sql_without_endpoint_validation(self):
        User.objects.create(**self.fields("ana@example.com"))
        for email, role in (("ana@example.com", "BUYER"), ("other@example.com", "ADMIN")):
            with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO accounts_user (name, email, password, role) VALUES (%s, %s, %s, %s)",
                    [VALID["name"], email, self.encoded, role],
                )
        self.assertEqual(User.objects.count(), 1)

    def test_database_rejects_noncanonical_sql_and_expression_writes(self):
        from django.db.models.functions import Upper
        user = User.objects.create(**self.fields("ana@example.com"))
        for email in (" ANA@EXAMPLE.COM ", "\tother@example.com\n", "other@\u00d1ANDU.COM", "\u2003other@example.com\u2003"):
            with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO accounts_user (name, email, password, role) VALUES (%s, %s, %s, %s)",
                    [VALID["name"], email, self.encoded, "BUYER"],
                )
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=user.pk).update(email=Upper("email"))
        self.assertEqual(User.objects.count(), 1)
        user.refresh_from_db()
        self.assertEqual(user.email, "ana@example.com")

    def test_other_integrity_failure_with_existing_email_is_500(self):
        User.objects.create(**self.fields("ana@example.com"))
        with patch.object(User, "save", side_effect=IntegrityError("secret_database_credential")), self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.client.post("/api/auth/register", data=json.dumps(VALID), content_type="application/json")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret_database_credential", response.content.decode())
        self.assertNotIn("secret_database_credential", " ".join(logs.output))
        self.assertNotIn("sessionid", response.cookies)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Session.objects.count(), 0)


class EmailMigrationTests(TransactionTestCase):
    before = [("accounts", "0001_initial")]
    after = [("accounts", "0002_normalize_account_emails")]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        self.old_user = executor.loader.project_state(self.before).apps.get_model("accounts", "User")

    def tearDown(self):
        # Only the isolated test database. Restore schema even after a failed test.
        self.old_user.objects.all().delete()
        MigrationExecutor(connection).migrate(self.after)
        super().tearDown()

    def test_existing_account_preserves_id_password_and_role(self):
        password = make_password(VALID["password"])
        old = self.old_user.objects.create(name=VALID["name"], email="\tANA@EXAMPLE.COM\n", password=password, role="SELLER")
        MigrationExecutor(connection).migrate(self.after)
        stored = User.objects.get(pk=old.pk)
        self.assertEqual(stored.email, "ana@example.com")
        self.assertEqual(stored.name, old.name)
        self.assertEqual(stored.password, password)
        self.assertEqual(stored.role, "SELLER")
        self.assertTrue(stored.check_password(VALID["password"]))

    def test_collision_aborts_without_changing_any_accounts(self):
        password = make_password(VALID["password"])
        for email in (" FIRST@EXAMPLE.COM ", "ANA@example.com", " ana@EXAMPLE.COM "):
            self.old_user.objects.create(name=VALID["name"], email=email, password=password, role="BUYER")
        snapshot = list(self.old_user.objects.order_by("pk").values())
        with self.assertRaisesRegex(RuntimeError, "collide after normalization") as error:
            MigrationExecutor(connection).migrate(self.after)
        self.assertEqual(list(self.old_user.objects.order_by("pk").values()), snapshot)
        self.assertNotIn(("accounts", "0002_normalize_account_emails"), MigrationRecorder(connection).applied_migrations())
        self.assertNotIn("example.com", str(error.exception))
        self.assertNotIn(password, str(error.exception))
