import asyncio
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import (
     init_db, save_connected_page, delete_connected_page,
     set_setting, get_db_connection
)
from app.channels.facebook import (
     handle_facebook_webhook_event, reply_to_fb_comment, send_fb_private_reply_to_comment
)

class TestFacebookCommentAutoReply(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.page_id = "fb_test_page_1001"
        self.page_token = "TEST_TOKEN_1001_ABC"
        save_connected_page({
            "page_id": self.page_id,
            "page_name": "RS Graphics Test",
            "shop_name": "RS Graphics Test",
            "page_access_token": self.page_token,
            "workspace_id": 1,
            "comments_enabled": 1,
            "ai_enabled": 1
        })
        set_setting("comment_auto_reply", "true")
        set_setting("private_message_on_comment", "true")
        set_setting("comment_ai_mode", "ai_smart")

    def tearDown(self):
        delete_connected_page(self.page_id)

    @patch("app.channels.facebook.reply_to_fb_comment")
    @patch("app.channels.facebook.send_fb_private_reply_to_comment")
    @patch("app.channels.facebook.process_customer_message")
    def test_01_feed_comment_triggers_ai_public_and_private_reply(
        self, mock_process, mock_private, mock_public
    ):
        """Test that user comment on post triggers AI public reply and private message."""
        mock_process.return_value = {
            "reply_text": "ধন্যবাদ স্যার! বিস্তারিত তথ্য আপনার ইনবক্সে পাঠানো হয়েছে 🥰",
            "matched_images": []
        }
        mock_public.return_value = True
        mock_private.return_value = True

        event = {
            "object": "page",
            "entry": [{
                "id": self.page_id,
                "changes": [{
                    "field": "feed",
                    "value": {
                        "from": {"id": "user_123", "name": "Md Rahman"},
                        "item": "comment",
                        "comment_id": "comment_999001",
                        "post_id": "post_777",
                        "verb": "add",
                        "message": "আইডি কার্ডের রেট কত?"
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(event))

        # Check public reply called
        self.assertTrue(mock_public.called)
        pub_args, pub_kwargs = mock_public.call_args
        self.assertEqual(pub_args[0], "comment_999001")
        self.assertIn("ধন্যবাদ", pub_args[1])
        self.assertEqual(pub_kwargs.get("page_id"), self.page_id)

        # Check private reply called
        self.assertTrue(mock_private.called)
        priv_args, priv_kwargs = mock_private.call_args
        self.assertEqual(priv_args[0], "comment_999001")
        self.assertEqual(priv_kwargs.get("page_id"), self.page_id)

        # Check logged in comment_logs
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM comment_logs WHERE comment_id = ?", ("comment_999001",))
        row = c.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["user_name"], "Md Rahman")
        print("✓ Test 1 Passed: Feed comment triggers AI public & private replies with database logging.")

    @patch("app.channels.facebook.reply_to_fb_comment")
    @patch("app.channels.facebook.send_fb_private_reply_to_comment")
    def test_02_own_page_comment_is_ignored(self, mock_private, mock_public):
        """Test that comments posted by the page itself do not trigger self-reply loop."""
        event = {
            "object": "page",
            "entry": [{
                "id": self.page_id,
                "changes": [{
                    "field": "feed",
                    "value": {
                        "from": {"id": self.page_id, "name": "RS Graphics Test"},
                        "item": "comment",
                        "comment_id": "comment_self_111",
                        "post_id": "post_777",
                        "verb": "add",
                        "message": "আমাদের সাথে থাকার জন্য ধন্যবাদ।"
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(event))

        self.assertFalse(mock_public.called)
        self.assertFalse(mock_private.called)
        print("✓ Test 2 Passed: Own page comments strictly ignored without infinite self-reply loops.")

    @patch("app.channels.facebook.reply_to_fb_comment")
    @patch("app.channels.facebook.send_fb_private_reply_to_comment")
    @patch("app.channels.facebook.process_customer_message")
    def test_03_comments_field_and_no_verb_supported(
        self, mock_process, mock_private, mock_public
    ):
        """Test that alternate Meta webhook format (field: comments) is fully supported."""
        mock_process.return_value = {
            "reply_text": "ধন্যবাদ ম্যাম! ইনবক্স চেক করুন 🥰"
        }
        mock_public.return_value = True

        event = {
            "object": "page",
            "entry": [{
                "id": self.page_id,
                "changes": [{
                    "field": "comments",
                    "value": {
                        "from": {"id": "user_456", "name": "Fatema Begum"},
                        "comment_id": "comment_comments_222",
                        "post_id": "post_888",
                        "message": "ফিতার দাম কত?"
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(event))

        self.assertTrue(mock_public.called)
        pub_args, _ = mock_public.call_args
        self.assertEqual(pub_args[0], "comment_comments_222")
        print("✓ Test 3 Passed: 'comments' webhook field format cleanly processed.")

    @patch("app.channels.facebook.reply_to_fb_comment")
    @patch("app.channels.facebook.send_fb_private_reply_to_comment")
    def test_04_comments_disabled_setting_skips_replies(self, mock_private, mock_public):
        """Test that when comments_enabled is set to 0, webhook skips comment auto reply."""
        save_connected_page({
            "page_id": self.page_id,
            "page_name": "RS Graphics Test",
            "shop_name": "RS Graphics Test",
            "page_access_token": self.page_token,
            "workspace_id": 1,
            "comments_enabled": 0,
            "ai_enabled": 1
        })

        event = {
            "object": "page",
            "entry": [{
                "id": self.page_id,
                "changes": [{
                    "field": "feed",
                    "value": {
                        "from": {"id": "user_789", "name": "Akram Khan"},
                        "item": "comment",
                        "comment_id": "comment_disabled_333",
                        "post_id": "post_777",
                        "verb": "add",
                        "message": "ডেলিভারি চার্জ কত?"
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(event))

        self.assertFalse(mock_public.called)
        self.assertFalse(mock_private.called)
        print("✓ Test 4 Passed: Disabling comments on page cleanly disables auto-reply.")

if __name__ == "__main__":
    unittest.main()
