import threading
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts import roles
from accounts.models import User
from meetings.models import AttendanceAuditLog, AttendanceRecord, ImmutableRecordError, MeetingSession
from meetings.services import (AttendanceError, close_session_now, correct_attendance, finalize_session,
                               record_attendance)

PW = "Sturdy-pass-993"
S = MeetingSession.Status


def make_session(admin, *, opens=-60, closes=60, title="Weekly", days=0, **kw):
    now = timezone.now()
    return MeetingSession.objects.create(
        title=title, meeting_date=(now + timedelta(days=days)).date(), created_by=admin,
        opens_at=now + timedelta(minutes=opens), closes_at=now + timedelta(minutes=closes), **kw)


class Base:
    def setUp(self):
        self.admin = User.objects.create_superuser("ADM1", "Admin One", PW)
        self.usher = User.objects.create_user("USH1", "Usher One", PW)
        roles.grant_usher(self.usher.pk, self.admin)
        self.usher = User.objects.get(pk=self.usher.pk)
        self.u1 = User.objects.create_user("S001", "Alice Adams", PW)
        self.u2 = User.objects.create_user("S002", "Bob Brown", PW)
        self.u3 = User.objects.create_user("S003", "Carol Clark", PW)
        self.session = make_session(self.admin)

    def record(self, users, actor=None, session=None, **kw):
        return record_attendance(session_id=(session or self.session).pk, raw_user_ids=[u.pk for u in users],
                                 actor=actor or self.usher, **kw)


class SessionRuleTests(Base, TestCase):
    def test_effective_status_follows_clock(self):
        now = timezone.now()
        self.assertEqual(make_session(self.admin, opens=10, closes=20).effective_status(now), S.SCHEDULED)
        self.assertEqual(self.session.effective_status(now), S.OPEN)
        self.assertEqual(make_session(self.admin, opens=-20, closes=-10).effective_status(now), S.CLOSED)

    def test_closing_enforced_without_scheduler(self):
        late = make_session(self.admin, opens=-120, closes=-1, status=S.OPEN)  # stored OPEN, clock says closed
        with self.assertRaisesMessage(AttendanceError, "not open"):
            self.record([self.u1], session=late)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_scheduled_session_rejects_attendance(self):
        future = make_session(self.admin, opens=30, closes=90)
        with self.assertRaises(AttendanceError):
            self.record([self.u1], session=future)

    def test_exact_closing_boundary(self):
        with self.assertRaises(AttendanceError):
            self.record([self.u1], now=self.session.closes_at)
        self.record([self.u1], now=self.session.closes_at - timedelta(seconds=1))

    def test_sync_statuses_and_command(self):
        late = make_session(self.admin, opens=-120, closes=-1, status=S.OPEN)
        MeetingSession.sync_statuses()
        late.refresh_from_db()
        self.assertEqual(late.status, S.CLOSED)
        self.assertEqual(late.closed_at, late.closes_at)

    def test_cannot_finalize_before_closed_and_stats_after(self):
        with self.assertRaises(AttendanceError):
            finalize_session(self.session.pk, self.admin)
        close_session_now(self.session.pk, self.admin)
        finalize_session(self.session.pk, self.admin)
        with self.assertRaises(AttendanceError):
            finalize_session(self.session.pk, self.admin)

    def test_only_admin_can_finalize_or_close(self):
        with self.assertRaises(PermissionDenied):
            close_session_now(self.session.pk, self.usher)
        with self.assertRaises(PermissionDenied):
            finalize_session(self.session.pk, self.usher)

    def test_close_check_constraint(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            MeetingSession.objects.filter(pk=self.session.pk).update(closes_at=self.session.opens_at)


class AttendanceSubmissionTests(Base, TestCase):
    def test_bulk_record_only_selected_and_includes_staff(self):
        result = self.record([self.u1, self.admin, self.usher])
        self.assertEqual(result, {"created": 3, "already_recorded": 0})
        self.assertEqual(set(AttendanceRecord.objects.values_list("user_id", flat=True)),
                         {self.u1.pk, self.admin.pk, self.usher.pk})
        self.assertFalse(AttendanceRecord.objects.filter(user=self.u2).exists())

    def test_acting_user_not_auto_marked(self):
        self.record([self.u1])
        self.assertFalse(AttendanceRecord.objects.filter(user=self.usher).exists())

    def test_resubmission_does_not_duplicate_or_overwrite(self):
        self.record([self.u1])
        original = AttendanceRecord.objects.get(user=self.u1)
        result = self.record([self.u1, self.u2], actor=self.admin)
        self.assertEqual(result, {"created": 1, "already_recorded": 1})
        again = AttendanceRecord.objects.get(user=self.u1)
        self.assertEqual((again.recorded_by_id, again.recorded_at), (original.recorded_by_id, original.recorded_at))

    def test_db_unique_constraint(self):
        from django.db import IntegrityError, transaction
        self.record([self.u1])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendanceRecord(session=self.session, user=self.u1, recorded_by=self.usher).save()

    def test_validation_is_all_or_nothing(self):
        for bad in (["abc"], [str(self.u1.pk), str(self.u1.pk)], [str(self.u1.pk), "999999"], [], ["-1"]):
            with self.assertRaises(AttendanceError):
                record_attendance(session_id=self.session.pk, raw_user_ids=bad, actor=self.usher)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_inactive_users_not_eligible(self):
        self.u2.is_active = False
        self.u2.save()
        with self.assertRaises(AttendanceError):
            self.record([self.u1, self.u2])
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_regular_user_cannot_record(self):
        with self.assertRaises(PermissionDenied):
            self.record([self.u1], actor=self.u2)

    def test_records_are_immutable(self):
        self.record([self.u1])
        rec = AttendanceRecord.objects.get()
        rec.user = self.u2
        with self.assertRaises(ImmutableRecordError):
            rec.save()
        with self.assertRaises(ImmutableRecordError):
            rec.delete()


class AttendanceViewTests(Base, TestCase):
    def setUp(self):
        super().setUp()
        for i in range(60):
            User.objects.create_user(f"X{i:03d}", f"Person {i:02d} Tester", PW)
        self.url = reverse("usher_attendance", args=[self.session.pk])

    def test_access_control(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.u1)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse("usher_sessions")).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"session_id": self.session.pk, "user_ids": [self.u2.pk]}).status_code, 403)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_search_and_pagination_server_side(self):
        self.client.force_login(self.usher)
        r = self.client.get(self.url)
        self.assertEqual(len(r.context["page_obj"]), 25)
        self.assertEqual(r.context["total_matching"], 65)  # 60 + admin + usher + 3 users
        r = self.client.get(self.url, {"q": "person 07"})  # every term must match
        self.assertEqual([p.student_id for p in r.context["page_obj"]], ["X007"])
        r = self.client.get(self.url, {"q": "x059"})
        self.assertEqual([p.student_id for p in r.context["page_obj"]], ["X059"])
        r = self.client.get(self.url, {"page": 3})
        self.assertEqual(r.context["page_obj"].number, 3)

    def test_pagination_preserves_query(self):
        self.client.force_login(self.usher)
        r = self.client.get(self.url, {"q": "tester"})
        self.assertContains(r, "q=tester&amp;page=2")

    def test_admin_and_usher_appear_in_list(self):
        self.client.force_login(self.usher)
        r = self.client.get(self.url, {"q": "Admin One"})
        self.assertEqual(r.context["total_matching"], 1)
        r = self.client.get(self.url, {"q": "usher one"})
        self.assertEqual(r.context["total_matching"], 1)

    def test_post_saves_and_marks_signed(self):
        self.client.force_login(self.usher)
        r = self.client.post(self.url, {"session_id": self.session.pk, "user_ids": [self.u1.pk, self.admin.pk]}, follow=True)
        self.assertContains(r, "Saved attendance for 2 person")
        self.assertEqual(AttendanceRecord.objects.filter(session=self.session).count(), 2)
        r = self.client.get(self.url, {"q": "Alice"})
        self.assertTrue(r.context["page_obj"][0].signed)

    def test_post_to_wrong_session_id_rejected(self):
        other = make_session(self.admin, title="Other")
        self.client.force_login(self.usher)
        self.client.post(self.url, {"session_id": other.pk, "user_ids": [self.u1.pk]})
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_post_to_closed_session_rejected(self):
        closed = make_session(self.admin, opens=-120, closes=-1, title="Old")
        self.client.force_login(self.usher)
        r = self.client.post(reverse("usher_attendance", args=[closed.pk]),
                             {"session_id": closed.pk, "user_ids": [self.u1.pk]}, follow=True)
        self.assertContains(r, "not open")
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_usher_cannot_use_admin_endpoints(self):
        self.record([self.u1])
        self.client.force_login(self.usher)
        for name, args in [("manage_dashboard", []), ("manage_sessions", []), ("manage_users", []), ("manage_audit", []),
                           ("manage_session_create", []), ("manage_session_detail", [self.session.pk]),
                           ("manage_correct", [self.session.pk, self.u1.pk]), ("manage_report_csv", [])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403, name)
        for name in ("manage_session_finalize", "manage_session_close"):
            self.assertEqual(self.client.post(reverse(name, args=[self.session.pk])).status_code, 403)
        close_session_now(self.session.pk, self.admin)
        r = self.client.post(reverse("manage_correct", args=[self.session.pk, self.u1.pk]),
                             {"action": "remove", "reason": "usher trying"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(AttendanceRecord.objects.count(), 1)

    def test_no_view_lets_usher_remove_records(self):
        self.record([self.u1])
        self.client.force_login(self.usher)
        # Posting nothing / crafted payloads never deletes anything.
        self.client.post(self.url, {"session_id": self.session.pk})
        self.client.post(self.url, {"session_id": self.session.pk, "delete": self.u1.pk, "user_ids": ["x"]})
        self.assertEqual(AttendanceRecord.objects.count(), 1)


class CorrectionTests(Base, TestCase):
    def test_correction_requires_closed_and_reason_and_logs(self):
        self.record([self.u1])
        with self.assertRaisesMessage(AttendanceError, "after a session has closed"):
            correct_attendance(session_id=self.session.pk, user_id=self.u1.pk, action="remove",
                               reason="mistake entered", actor=self.admin)
        close_session_now(self.session.pk, self.admin)
        with self.assertRaisesMessage(AttendanceError, "reason"):
            correct_attendance(session_id=self.session.pk, user_id=self.u1.pk, action="remove", reason=" ", actor=self.admin)
        entry = correct_attendance(session_id=self.session.pk, user_id=self.u1.pk, action="remove",
                                   reason="Marked by mistake", actor=self.admin)
        self.assertFalse(AttendanceRecord.objects.filter(user=self.u1).exists())
        self.assertTrue(entry.original_values["present"])
        self.assertFalse(entry.corrected_values["present"])
        self.assertEqual((entry.performed_by, entry.reason, entry.user), (self.admin, "Marked by mistake", self.u1))
        self.assertIsNotNone(entry.attendance_record_id)

    def test_add_correction_on_finalized_session(self):
        close_session_now(self.session.pk, self.admin)
        finalize_session(self.session.pk, self.admin)
        entry = correct_attendance(session_id=self.session.pk, user_id=self.u2.pk, action="add",
                                   reason="Was present, missed", actor=self.admin)
        self.assertTrue(AttendanceRecord.objects.filter(user=self.u2, session=self.session).exists())
        self.assertFalse(entry.original_values["present"])
        self.assertTrue(entry.corrected_values["present"])

    def test_only_admin_and_state_consistency(self):
        close_session_now(self.session.pk, self.admin)
        with self.assertRaises(PermissionDenied):
            correct_attendance(session_id=self.session.pk, user_id=self.u1.pk, action="add", reason="usher try", actor=self.usher)
        with self.assertRaises(AttendanceError):
            correct_attendance(session_id=self.session.pk, user_id=self.u1.pk, action="remove", reason="not present", actor=self.admin)
        self.assertEqual(AttendanceAuditLog.objects.count(), 0)

    def test_audit_entries_immutable(self):
        close_session_now(self.session.pk, self.admin)
        entry = correct_attendance(session_id=self.session.pk, user_id=self.u1.pk, action="add", reason="late sign-in", actor=self.admin)
        entry.reason = "edited"
        with self.assertRaises(ImmutableRecordError):
            entry.save()
        with self.assertRaises(ImmutableRecordError):
            entry.delete()

    def test_admin_correction_view(self):
        self.record([self.u1])
        close_session_now(self.session.pk, self.admin)
        self.client.force_login(self.admin)
        url = reverse("manage_correct", args=[self.session.pk, self.u1.pk])
        self.assertContains(self.client.get(url), "mark them <strong>absent")
        self.client.post(url, {"action": "remove", "reason": "ok"})  # too short
        self.assertEqual(AttendanceRecord.objects.count(), 1)
        self.client.post(url, {"action": "remove", "reason": "Entered under wrong name"})
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        self.assertEqual(AttendanceAuditLog.objects.count(), 1)


class StatsTests(Base, TestCase):
    def make_final(self, title, attendees, days):
        s = make_session(self.admin, title=title, days=days)
        self.record(attendees, session=s)
        close_session_now(s.pk, self.admin)
        finalize_session(s.pk, self.admin)
        return s

    def test_personal_stats_use_finalized_only(self):
        self.make_final("M1", [self.u1, self.u2], -14)
        self.make_final("M2", [self.u1], -7)
        self.record([self.u1])  # open session: must not count
        self.client.force_login(self.u1)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.context["stats"], {"held": 2, "attended": 2, "missed": 0, "percent": 100.0})
        self.client.force_login(self.u2)
        self.assertEqual(self.client.get(reverse("dashboard")).context["stats"],
                         {"held": 2, "attended": 1, "missed": 1, "percent": 50.0})

    def test_no_finalized_sessions_no_division_by_zero(self):
        self.client.force_login(self.u3)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.context["stats"], {"held": 0, "attended": 0, "missed": 0, "percent": None})
        self.assertContains(r, "—")

    def test_history_shows_only_own_records(self):
        self.make_final("M1", [self.u1], -7)
        self.client.force_login(self.u2)
        r = self.client.get(reverse("history"))
        self.assertEqual([s.present for s in r.context["page_obj"]], [False])
        self.assertNotContains(r, "Alice")

    def test_regular_user_cannot_see_other_users_pages(self):
        self.client.force_login(self.u2)
        self.assertEqual(self.client.get(reverse("manage_user_detail", args=[self.u1.pk])).status_code, 403)

    def test_admin_dashboard_numbers(self):
        self.make_final("M1", [self.u1, self.u2, self.admin], -14)
        self.make_final("M2", [self.u1], -7)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("manage_dashboard"))
        # 5 active users x 2 sessions = 10 slots; 4 attendance records
        self.assertEqual(r.context["totals"], {"sessions": 2, "attendance": 4, "absences": 6, "percent": 40.0})
        self.assertEqual(r.context["total_users"], 5)
        rows = {row["session"].title: row for row in r.context["rows"]}
        self.assertEqual((rows["M1"]["eligible"], rows["M1"]["attendees"], rows["M1"]["absent"], rows["M1"]["percent"]), (5, 3, 2, 60.0))

    def test_date_filter_and_csv(self):
        self.make_final("Old", [self.u1], -30)
        self.make_final("New", [self.u1], -1)
        self.client.force_login(self.admin)
        since = (timezone.now() - timedelta(days=10)).date().isoformat()
        r = self.client.get(reverse("manage_dashboard"), {"date_from": since})
        self.assertEqual(r.context["totals"]["sessions"], 1)
        csv_resp = self.client.get(reverse("manage_report_csv"), {"date_from": since})
        body = csv_resp.content.decode()
        self.assertIn("New", body)
        self.assertNotIn("Old", body)

    def test_csv_formula_injection_neutralised(self):
        evil = User.objects.create_user("EVIL1", "=HYPERLINK(1)", PW)
        s = self.make_final("M1", [evil], -7)
        self.client.force_login(self.admin)
        body = self.client.get(reverse("manage_session_csv", args=[s.pk])).content.decode()
        self.assertIn("'=HYPERLINK(1)", body)


class AdminPagesTests(Base, TestCase):
    def test_create_session_validation(self):
        self.client.force_login(self.admin)
        now = timezone.localtime()
        fmt = "%Y-%m-%dT%H:%M"
        data = {"title": "Week 9", "meeting_date": now.date().isoformat(),
                "opens_at": now.strftime(fmt), "closes_at": (now - timedelta(hours=1)).strftime(fmt)}
        r = self.client.post(reverse("manage_session_create"), data)
        self.assertContains(r, "must be after the opening time")
        data["closes_at"] = (now + timedelta(hours=2)).strftime(fmt)
        r = self.client.post(reverse("manage_session_create"), data)
        s = MeetingSession.objects.get(title="Week 9")
        self.assertRedirects(r, reverse("manage_session_detail", args=[s.pk]))
        self.assertEqual(s.created_by, self.admin)
        self.assertFalse(AttendanceRecord.objects.exists())  # creating a session never marks anyone present
        self.assertEqual(s.status, S.OPEN)  # opened immediately, synced by the clock

    def test_user_management_search_and_role_change(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("manage_users"), {"q": "bob"})
        self.assertEqual([u.student_id for u in r.context["page_obj"]], ["S002"])
        self.client.post(reverse("manage_user_role", args=[self.u2.pk]), {"action": "grant_usher"})
        self.assertTrue(User.objects.get(pk=self.u2.pk).has_perm("meetings.take_attendance"))
        r = self.client.post(reverse("manage_user_role", args=[self.admin.pk]), {"action": "revoke_admin"}, follow=True)
        self.assertContains(r, "last administrator")
        self.assertTrue(User.objects.get(pk=self.admin.pk).is_superuser)

    def test_edit_blocked_for_closed_session(self):
        close_session_now(self.session.pk, self.admin)
        self.client.force_login(self.admin)
        r = self.client.get(reverse("manage_session_edit", args=[self.session.pk]), follow=True)
        self.assertContains(r, "Only scheduled or open")


class ConcurrencyTests(TransactionTestCase):
    def test_simultaneous_submissions_never_duplicate(self):
        if connection.vendor != "postgresql":
            self.skipTest("needs PostgreSQL row locking")
        admin = User.objects.create_superuser("ADM1", "Admin", PW)
        users = [User.objects.create_user(f"C{i:03d}", f"User {i}", PW) for i in range(30)]
        session = make_session(admin)
        errors, results = [], []

        def worker(chunk):
            try:
                results.append(record_attendance(session_id=session.pk, raw_user_ids=[u.pk for u in chunk], actor=admin))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(users[i * 5: i * 5 + 15],)) for i in range(4)]  # overlapping
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        covered = {u.pk for i in range(4) for u in users[i * 5: i * 5 + 15]}
        self.assertEqual(AttendanceRecord.objects.count(), len(covered))
        self.assertEqual(sum(r["created"] for r in results), len(covered))
