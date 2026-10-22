from django.test import TestCase
from django.urls import reverse

from accounts import roles
from accounts.models import User

PW = "Sturdy-pass-993"


class RegistrationLoginTests(TestCase):
    def post_register(self, **over):
        data = {"full_name": "Ada Obi", "student_id": "biu/csc/21/001", "password1": PW, "password2": PW}
        data.update(over)
        return self.client.post(reverse("register"), data)

    def test_register_normalizes_id_and_logs_in(self):
        r = self.post_register(student_id="  biu / csc/21/001 ")
        self.assertRedirects(r, reverse("dashboard"))
        u = User.objects.get()
        self.assertEqual(u.student_id, "BIU/CSC/21/001")
        self.assertTrue(u.check_password(PW))
        self.assertNotEqual(u.password, PW)
        self.assertFalse(u.is_superuser or u.is_staff or u.has_usher_role)

    def test_duplicate_id_rejected_case_and_space_insensitive(self):
        self.post_register()
        self.client.logout()
        r = self.post_register(full_name="Someone Else", student_id=" BIU/CSC/21/001")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already exists")
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_data(self):
        self.assertContains(self.post_register(password2="different"), "do not match")
        self.assertContains(self.post_register(password1="123", password2="123"), "too short")
        self.assertContains(self.post_register(student_id="!!"), "Student ID")
        self.assertEqual(User.objects.count(), 0)

    def test_cannot_self_assign_roles(self):
        self.post_register(is_superuser="on", is_staff="on", groups="1")
        u = User.objects.get()
        self.assertFalse(u.is_superuser)
        self.assertFalse(u.is_staff)

    def test_login_logout(self):
        User.objects.create_user("S001", "Test User", PW)
        bad = self.client.post(reverse("login"), {"username": "S001", "password": "wrong"})
        self.assertContains(bad, "Incorrect student ID or password")
        ok = self.client.post(reverse("login"), {"username": " s001 ", "password": PW})
        self.assertRedirects(ok, reverse("dashboard"))
        self.client.post(reverse("logout"))
        self.assertRedirects(self.client.get(reverse("dashboard")), f"{reverse('login')}?next=/")

    def test_inactive_account_cannot_login(self):
        User.objects.create_user("S002", "Gone Away", PW, is_active=False)
        r = self.client.post(reverse("login"), {"username": "S002", "password": PW})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class RoleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("ADM1", "Admin One", PW)
        self.user = User.objects.create_user("USR1", "Regular", PW)

    def test_usher_grant_revoke_and_permission(self):
        roles.grant_usher(self.user.pk, self.admin)
        user = User.objects.get(pk=self.user.pk)
        self.assertTrue(user.has_perm("meetings.take_attendance"))
        roles.revoke_usher(self.user.pk, self.admin)
        self.assertFalse(User.objects.get(pk=self.user.pk).has_perm("meetings.take_attendance"))

    def test_non_admin_cannot_change_roles(self):
        with self.assertRaises(roles.RoleError):
            roles.grant_usher(self.user.pk, self.user)

    def test_last_admin_protected(self):
        with self.assertRaisesMessage(roles.RoleError, "last administrator"):
            roles.revoke_admin(self.admin.pk, self.admin)
        roles.grant_admin(self.user.pk, self.admin)
        roles.revoke_admin(self.admin.pk, self.admin)  # now allowed: another admin exists
        self.assertFalse(User.objects.get(pk=self.admin.pk).is_superuser)

    def test_role_endpoint_requires_admin(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("manage_user_role", args=[self.user.pk]), {"action": "grant_admin"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(User.objects.get(pk=self.user.pk).is_superuser)
