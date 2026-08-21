import unittest
import asyncio
from unittest.mock import patch, MagicMock

from app.database import (
    get_db_connection, save_connected_page, get_connected_page,
    set_setting, get_setting
)
from app.channels.facebook import (
    handle_facebook_webhook_event, reply_to_fb_comment, send_fb_private_reply_to_comment,
    get_fb_token
)

class TestFacebookCommentAutoReply(unittest.TestCase):
    def setUp(self):
        self.page_id = "105116472071659"
        self.page_name = "RS Graphics (আরএস গ্রাফিক্স)"
        self.token = "EAAB_VALID_TEST_TOKEN_XYZ1234567890"

        save_connected_page({
            "page_id": self.page_id,
            "page_name": self.page_name,
            "page_access_token": self.token,
            "workspace_id": 1,
            "messenger_enabled": 1,
            "comments_enabled": 1,
            "ai_enabled": 1
        })
        set_setting("comment_auto_reply", "true")
        set_setting("private_message_on_comment", "true")
        set_setting("comment_ai_mode", "ai_smart")

    def tearDown(self):
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM comment_logs WHERE page_id = ?", (self.page_id,))
            conn.commit()
        finally:
            conn.close()

    @patch("app.channels.facebook.requests.post")
    def test_01_reply_to_fb_comment_success(self, mock_post):
        """reply_to_fb_comment sends POST request to Meta Graph API /comments endpoint."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "105116472071659_9999"}
        mock_post.return_value = mock_resp

        success = reply_to_fb_comment(
            comment_id="105116472071659_123456",
            message="ধন্যবাদ স্যার! বিস্তারিত ইনবক্সে পাঠানো হয়েছে।",
            page_token=self.token,
            page_id=self.page_id
        )
        self.assertTrue(success)
        mock_post.assert_called()
        call_url = mock_post.call_args[0][0]
        self.assertIn("105116472071659_123456/comments", call_url)

    @patch("app.channels.facebook.requests.post")
    def test_02_send_fb_private_reply_success(self, mock_post):
        """send_fb_private_reply_to_comment sends private message to comment_id."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"recipient_id": "5197770284", "message_id": "m_mid123"}
        mock_post.return_value = mock_resp

        success = send_fb_private_reply_to_comment(
            comment_id="105116472071659_123456",
            message="আসসালামু আলাইকুম! আমাদের আইডি কার্ডের দাম ১০০ পিস ৩০০০ টাকা।",
            page_token=self.token,
            page_id=self.page_id
        )
        self.assertTrue(success)
        mock_post.assert_called()
        call_url = mock_post.call_args[0][0]
        self.assertIn("/me/messages", call_url)

    @patch("app.channels.facebook.send_fb_private_reply_to_comment")
    @patch("app.channels.facebook.reply_to_fb_comment")
    @patch("app.channels.facebook.process_customer_message")
    def test_03_webhook_comment_event_triggers_both_replies(self, mock_ai, mock_public_reply, mock_private_reply):
        """Incoming feed comment webhook generates AI responses and calls public and private reply functions."""
        mock_ai.side_effect = [
            {"reply_text": "ধন্যবাদ ভাইয়া! ইনবক্স চেক করুন 🥰"},
            {"reply_text": "আসসালামু আলাইকুম! আমাদের কাছে প্রিমিয়াম আইডি কার্ড প্রিন্টিং সেবা রয়েছে।"}
        ]
        mock_public_reply.return_value = True
        mock_private_reply.return_value = True

        payload = {
            "object": "page",
            "entry": [{
                "id": self.page_id,
                "changes": [{
                    "field": "feed",
                    "value": {
                        "item": "comment",
                        "verb": "add",
                        "comment_id": "105116472071659_778899",
                        "post_id": "105116472071659_112233",
                        "from": {
                            "id": "5197770284",
                            "name": "Mahmudul Hasan"
                        },
                        "message": "দাম কত?"
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(payload))

        self.assertTrue(mock_public_reply.called)
        self.assertTrue(mock_private_reply.called)

        # Verify comment logged to database
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM comment_logs WHERE comment_id = '105116472071659_778899'")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["user_name"], "Mahmudul Hasan")
            self.assertEqual(row["comment_text"], "দাম কত?")
        finally:
            conn.close()

    @patch("app.channels.facebook.reply_to_fb_comment")
    def test_04_own_page_comments_ignored_preventing_loop(self, mock_reply):
        """Comments from the page itself (user_id == page_id) are ignored."""
        payload = {
            "object": "page",
            "entry": [{
                "id": self.page_id,
                "changes": [{
                    "field": "feed",
                    "value": {
                        "item": "comment",
                        "verb": "add",
                        "comment_id": "105116472071659_own_comment",
                        "post_id": "105116472071659_112233",
                        "from": {
                            "id": self.page_id, # Same as page_id
                            "name": "RS Graphics"
                        },
                        "message": "Page reply text"
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(payload))
        self.assertFalse(mock_reply.called)

if __name__ == "__main__":
    unittest.main()
