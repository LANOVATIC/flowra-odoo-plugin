# Part of Flowra. See LICENSE file for full copyright and licensing details.
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBridge(TransactionCase):
    def setUp(self):
        super().setUp()
        self.service = self.env["flowra.connection"]._service_user()
        self.Bridge = self.env["flowra.bridge"].with_user(self.service)
        self.product = self.env["product.product"].create({"name": "Widget"})
        self.partner = self.env["res.partner"].create({"name": "Supplier"})

    def test_the_flowra_user_cannot_write_the_record_itself(self):
        # Why the bridge exists: least privilege means no edit right on products.
        with self.assertRaises(AccessError):
            self.product.with_user(self.service).write({"name": "changed"})

    def test_anyone_else_is_refused(self):
        clerk = self.env["res.users"].create({"name": "Clerk", "login": "clerk-bridge"})
        with self.assertRaises(AccessError):
            self.env["flowra.bridge"].with_user(clerk).capabilities()
        with self.assertRaises(AccessError):
            self.env["flowra.bridge"].with_user(clerk).post_note("res.partner", self.partner.id, "x")

    def test_capabilities(self):
        self.assertEqual(self.Bridge.capabilities()["actions"], ["schedule_activity", "post_note"])

    def test_an_activity_lands_typed_and_on_a_person(self):
        self.env["ir.config_parameter"].sudo().set_param("flowra.connected_by_uid", str(self.env.ref("base.user_admin").id))
        activity_id = self.Bridge.schedule_activity(
            "product.product", self.product.id, "Reorder", "2026-12-01", "<p>cover &lt; 5</p>", False
        )
        activity = self.env["mail.activity"].browse(activity_id)
        self.assertEqual(activity.activity_type_id, self.env.ref("flowra.mail_activity_type_flowra"))
        self.assertEqual(activity.res_model, "product.product")
        self.assertEqual(activity.res_id, self.product.id)
        self.assertEqual(activity.user_id, self.env.ref("base.user_admin"))
        self.assertNotEqual(activity.user_id, self.service)
        self.assertEqual(activity.create_uid, self.service)
        self.assertEqual(str(activity.date_deadline), "2026-12-01")
        # No assignment email is queued.
        self.assertFalse(self.env["mail.mail"].sudo().search([("model", "=", "mail.activity"), ("res_id", "=", activity_id)]))

    def test_a_named_assignee_must_be_an_active_internal_user(self):
        portal = self.env["res.users"].create({
            "name": "Portal", "login": "portal-bridge",
            "groups_id" if "groups_id" in self.env["res.users"]._fields else "group_ids":
                [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        with self.assertRaises(UserError):
            self.Bridge.schedule_activity("res.partner", self.partner.id, "x", "2026-12-01", False, portal.id)

    def test_only_three_models(self):
        with self.assertRaises(AccessError):
            self.Bridge.post_note("res.users", self.env.ref("base.user_admin").id, "x")
        with self.assertRaises(AccessError):
            self.Bridge.schedule_activity("account.move", 1, "x", "2026-12-01")

    def test_a_missing_record_is_refused(self):
        with self.assertRaises(UserError):
            self.Bridge.post_note("res.partner", 999999, "x")

    def test_a_note_is_internal_and_signed_by_flowra(self):
        message_id = self.Bridge.post_note("res.partner", self.partner.id, "late again", "Flowra")
        message = self.env["mail.message"].browse(message_id)
        self.assertEqual(message.subtype_id, self.env.ref("mail.mt_note"))
        self.assertEqual(message.author_id, self.service.partner_id)
        self.assertIn("late again", message.body)
