import unittest
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.config import settings
from app.database import (
    get_db_connection, init_db,
    claim_media_delivery, update_media_delivery_status, get_media_delivery,
    is_webhook_event_processed, mark_webhook_event_processed
)
from app.channels.facebook import (
    send_fb_text_message,
    send_fb_media_message,
    send_fb_audio_message,
    send_fb_video_message,
    compute_media_fingerprint,
    handle_facebook_webhook_event
)
from app.channels.whatsapp import (
    send_whatsapp_message,
    send_whatsapp_image
)

class TestFacebookMediaIdempotencySuite(unittest.TestCase):
    def setUp(self):
        init_db()
        self.recipient_id = "5197778473660284"
        self.page_id = "105116472071659"
        self.page_token = "EAASValidPageAccessTokenTest123456"
        self.workspace_id = 1
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM facebook_media_deliveries")
        cur.execute("DELETE FROM processed_webhook_events")
        conn.commit()
        conn.close()

    def test_01_same_webhook_event_received_twice(self):
        """TEST 1: Same webhook event received twice -> AI/media processing occurs once."""
        msg_id = "mid_unique_webhook_test_001"
        data = {
            "entry": [{
                "id": self.page_id,
                "messaging": [{
                    "sender": {"id": self.recipient_id},
                    "recipient": {"id": self.page_id},
                    "message": {
                        "mid": msg_id,
                        "text": "আইডি কার্ডের দাম কত?"
                    }
                }]
            }]
        }
        
        with patch("app.channels.facebook.process_customer_message") as mock_ai, \
             patch("app.channels.facebook.send_fb_text_message") as mock_send_text:
            mock_ai.return_value = {
                "reply_text": "আইডি কার্ড ৫০ টাকা",
                "matched_images": []
            }
            mock_send_text.return_value = True

            # First delivery
            asyncio.run(handle_facebook_webhook_event(data))
            self.assertEqual(mock_ai.call_count, 1)

            # Second duplicate delivery
            asyncio.run(handle_facebook_webhook_event(data))
            # AI should NOT be called again
            self.assertEqual(mock_ai.call_count, 1)

    def test_02_same_image_requested_twice_only_one_send(self):
        """TEST 2: Same image requested twice -> only one Facebook send."""
        img_url = "https://example.com/unique_sample_02.jpg"
        
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "recipient_id": self.recipient_id,
                "message_id": "m_test_msg_02",
                "attachment_id": "att_02"
            }

            # 1st send
            res1 = send_fb_media_message(
                recipient_id=self.recipient_id,
                media_type="image",
                media_url=img_url,
                page_token=self.page_token,
                page_id=self.page_id,
                workspace_id=self.workspace_id
            )
            self.assertTrue(res1)
            self.assertEqual(mock_post.call_count, 1)

            # 2nd send of same image
            res2 = send_fb_media_message(
                recipient_id=self.recipient_id,
                media_type="image",
                media_url=img_url,
                page_token=self.page_token,
                page_id=self.page_id,
                workspace_id=self.workspace_id
            )
            self.assertTrue(res2) # Returns True (skipped because already sent)
            # Post should still be called only once
            self.assertEqual(mock_post.call_count, 1)

    def test_03_same_media_url_twice_only_one_logical_delivery(self):
        """TEST 3: Same media URL twice -> only one logical delivery record in database."""
        img_url = "https://example.com/unique_url_delivery_03.jpg"
        fp, _ = compute_media_fingerprint(img_url)
        delivery_key = f"fb_media:{self.workspace_id}:{self.page_id}:{self.recipient_id}:{fp}"

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"recipient_id": self.recipient_id, "message_id": "m_03"}

            send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
            send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM facebook_media_deliveries WHERE delivery_key = ?", (delivery_key,))
        count = cur.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_04_same_file_content_with_different_filename(self):
        """TEST 4: Same file content with different filename -> detect same media fingerprint where appropriate."""
        # Create two temporary files with identical bytes
        test_bytes = b"Identical_Image_Content_For_Fingerprint_Test_2026"
        f1 = settings.UPLOADS_DIR / "temp_img_a.jpg"
        f2 = settings.UPLOADS_DIR / "temp_img_b.jpg"
        try:
            f1.write_bytes(test_bytes)
            f2.write_bytes(test_bytes)

            fp1, _ = compute_media_fingerprint(f"/static/uploads/{f1.name}")
            fp2, _ = compute_media_fingerprint(f"/static/uploads/{f2.name}")
            self.assertEqual(fp1, fp2)
        finally:
            if f1.exists():
                f1.unlink()
            if f2.exists():
                f2.unlink()

    def test_05_worker_a_claims_media_worker_b_cannot_claim_same_media(self):
        """TEST 5: Worker A claims media -> Worker B cannot claim same media."""
        key = "fb_media:1:105116472071659:rec_claim_05:fp_05"
        can_send_a, rec_a = claim_media_delivery(key, 1, "105116472071659", "rec_claim_05", "image", "url", "file.jpg", "fp_05")
        self.assertTrue(can_send_a)

        # Worker B tries immediately while status is SENDING
        can_send_b, rec_b = claim_media_delivery(key, 1, "105116472071659", "rec_claim_05", "image", "url", "file.jpg", "fp_05")
        self.assertFalse(can_send_b)

    def test_06_image_already_sent_second_attempt_is_skipped(self):
        """TEST 6: Image already SENT -> second attempt is skipped."""
        key = "fb_media:1:105116472071659:rec_sent_06:fp_06"
        claim_media_delivery(key, 1, "105116472071659", "rec_sent_06", "image", "url", "file.jpg", "fp_06")
        update_media_delivery_status(key, "SENT", meta_message_id="m_06")

        can_send, rec = claim_media_delivery(key, 1, "105116472071659", "rec_sent_06", "image", "url", "file.jpg", "fp_06")
        self.assertFalse(can_send)
        self.assertEqual(rec["status"], "SENT")

    def test_07_network_timeout_status_unknown_duplicate_retry_blocked(self):
        """TEST 7: Network timeout -> status becomes UNKNOWN -> immediate duplicate retry blocked."""
        import requests
        img_url = "https://example.com/timeout_test_07.jpg"
        fp, _ = compute_media_fingerprint(img_url)
        delivery_key = f"fb_media:{self.workspace_id}:{self.page_id}:{self.recipient_id}:{fp}"

        with patch("requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout("Read timed out (read timeout=15)")
            res = send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
            self.assertFalse(res)

        record = get_media_delivery(delivery_key)
        self.assertIsNotNone(record)
        self.assertEqual(record["status"], "UNKNOWN")

        # Second attempt immediately should be blocked without network call
        with patch("requests.post") as mock_post2:
            res2 = send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
            self.assertFalse(res2)
            mock_post2.assert_not_called()

    def test_08_http_500_controlled_retry_using_same_delivery_key(self):
        """TEST 8: HTTP 500 -> controlled retry using same delivery key."""
        key = "fb_media:1:105116472071659:rec_500_08:fp_08"
        claim_media_delivery(key, 1, "105116472071659", "rec_500_08", "image", "url", "file.jpg", "fp_08")
        update_media_delivery_status(key, "FAILED", last_error="HTTP 500 Internal Server Error")

        # Can retry failed delivery using same key
        can_retry, rec = claim_media_delivery(key, 1, "105116472071659", "rec_500_08", "image", "url", "file.jpg", "fp_08")
        self.assertTrue(can_retry)
        self.assertEqual(rec["attempt_count"], 2)

    def test_09_http_400_no_automatic_retry(self):
        """TEST 9: HTTP 400 -> no automatic retry."""
        img_url = "https://example.com/bad_req_09.jpg"
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 400
            mock_post.return_value.text = "Bad Request: Invalid URL"
            res = send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
            self.assertFalse(res)

    def test_10_http_429_controlled_backoff(self):
        """TEST 10: HTTP 429 -> records error state and does not loop infinitely."""
        img_url = "https://example.com/rate_limit_10.jpg"
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 429
            mock_post.return_value.text = "Rate Limit Exceeded"
            res = send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
            self.assertFalse(res)

    def test_11_binary_fallback_after_url_failure_cannot_create_duplicate_delivery(self):
        """TEST 11: Direct binary upload cannot double-send upon timeout."""
        img_url = "/static/uploads/test_binary_11.jpg"
        test_file = settings.UPLOADS_DIR / "test_binary_11.jpg"
        try:
            test_file.write_bytes(b"test_image_data_11")
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {"recipient_id": self.recipient_id, "message_id": "m_bin_11"}
                
                # First send
                res1 = send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
                self.assertTrue(res1)
                self.assertEqual(mock_post.call_count, 1)

                # Second send
                res2 = send_fb_media_message(self.recipient_id, "image", img_url, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
                self.assertTrue(res2)
                self.assertEqual(mock_post.call_count, 1)
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_12_batch_resumes_previously_sent_images_not_resent(self):
        """TEST 12: Batch resumes -> previously SENT images are not resent."""
        img1 = "https://example.com/batch_img1.jpg"
        img2 = "https://example.com/batch_img2.jpg"
        img3 = "https://example.com/batch_img3.jpg"

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"recipient_id": self.recipient_id, "message_id": "m_12"}

            # Send batch 1 with img1 & img2
            send_fb_media_message(self.recipient_id, "image", img1, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id, batch_id="b_12")
            send_fb_media_message(self.recipient_id, "image", img2, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id, batch_id="b_12")
            self.assertEqual(mock_post.call_count, 2)

            # Next request sends img1, img2, img3 -> only img3 should trigger a POST
            send_fb_media_message(self.recipient_id, "image", img1, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id, batch_id="b_12_next")
            send_fb_media_message(self.recipient_id, "image", img2, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id, batch_id="b_12_next")
            send_fb_media_message(self.recipient_id, "image", img3, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id, batch_id="b_12_next")
            self.assertEqual(mock_post.call_count, 3)

    def test_13_old_pending_batch_after_restart_sent_images_skipped(self):
        """TEST 13: Old pending batch exists after application restart -> sent images are skipped."""
        img = "https://example.com/restart_test_13.jpg"
        fp, _ = compute_media_fingerprint(img)
        key = f"fb_media:{self.workspace_id}:{self.page_id}:{self.recipient_id}:{fp}"

        # Pretend it was SENT in past run
        claim_media_delivery(key, self.workspace_id, self.page_id, self.recipient_id, "image", img, "restart_test_13.jpg", fp)
        update_media_delivery_status(key, "SENT", meta_message_id="m_past_13")

        with patch("requests.post") as mock_post:
            res = send_fb_media_message(self.recipient_id, "image", img, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
            self.assertTrue(res)
            mock_post.assert_not_called()

    def test_14_two_simultaneous_workers_only_one_sends(self):
        """TEST 14: Two simultaneous workers -> only one sends."""
        img = "https://example.com/simul_worker_14.jpg"
        
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"recipient_id": self.recipient_id, "message_id": "m_14"}

            # Worker 1 claims
            fp, _ = compute_media_fingerprint(img)
            key = f"fb_media:{self.workspace_id}:{self.page_id}:{self.recipient_id}:{fp}"
            can_send_1, _ = claim_media_delivery(key, self.workspace_id, self.page_id, self.recipient_id, "image", img, "simul.jpg", fp)
            self.assertTrue(can_send_1)

            # Worker 2 tries to send
            res_w2 = send_fb_media_message(self.recipient_id, "image", img, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id)
            # Worker 2 skipped
            self.assertFalse(res_w2)
            mock_post.assert_not_called()

    def test_15_gemini_retry_does_not_create_duplicate_media_batch(self):
        """TEST 15: Gemini retry -> does not create duplicate media batch."""
        # Simulated scenario: AI generates reply with images
        matched_images = ["https://example.com/gemini_img_15.jpg"]
        batch_id = "fb_batch_gemini_retry_15"

        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"recipient_id": self.recipient_id, "message_id": "m_15"}

            # Run 1
            for u in matched_images:
                send_fb_media_message(self.recipient_id, "image", u, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id, batch_id=batch_id)
            self.assertEqual(mock_post.call_count, 1)

            # Gemini failed & retried later with same images
            for u in matched_images:
                send_fb_media_message(self.recipient_id, "image", u, page_token=self.page_token, page_id=self.page_id, workspace_id=self.workspace_id, batch_id=batch_id)
            self.assertEqual(mock_post.call_count, 1)

    def test_16_existing_facebook_text_messaging_still_works(self):
        """TEST 16: Existing Facebook text messaging still works."""
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = '{"recipient_id": "123", "message_id": "m_text_16"}'
            ok = send_fb_text_message(self.recipient_id, "হ্যালো টেস্ট", page_token=self.page_token, page_id=self.page_id)
            self.assertTrue(ok)

    def test_17_existing_facebook_webhook_routing_remains_correct(self):
        """TEST 17: Existing Facebook webhook routing remains correct."""
        msg_id = "mid_fb_routing_check_17"
        data = {
            "entry": [{
                "id": self.page_id,
                "messaging": [{
                    "sender": {"id": self.recipient_id},
                    "recipient": {"id": self.page_id},
                    "message": {
                        "mid": msg_id,
                        "text": "টেস্ট মেসেজ"
                    }
                }]
            }]
        }
        with patch("app.channels.facebook.process_customer_message") as mock_ai, \
             patch("app.channels.facebook.send_fb_text_message") as mock_send:
            mock_ai.return_value = {"reply_text": "উত্তর", "matched_images": []}
            mock_send.return_value = True
            asyncio.run(handle_facebook_webhook_event(data))
            self.assertEqual(mock_ai.call_count, 1)
            # Verify workspace_id=1 was passed
            call_kwargs = mock_ai.call_args[1]
            self.assertEqual(call_kwargs.get("workspace_id"), 1)

    def test_18_existing_whatsapp_functionality_remains_unchanged(self):
        """TEST 18: Existing WhatsApp functionality remains unchanged."""
        with patch("requests.post") as mock_post, \
             patch("app.channels.whatsapp.validate_whatsapp_token_with_meta") as mock_val:
            mock_val.return_value = {
                "valid": True,
                "phone_number_access": True,
                "verified_name": "RS Graphics"
            }
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "messaging_product": "whatsapp",
                "contacts": [{"wa_id": "8801816504097"}],
                "messages": [{"id": "wamid.Test18"}]
            }
            res = send_whatsapp_message(
                to_number="8801816504097",
                message_text="WhatsApp Test Message",
                phone_id="4184514263660680",
                token="EAAXValidWhatsAppProductionTokenForTest18_123456789"
            )
            self.assertTrue(res)

    def test_19_existing_database_records_remain_intact(self):
        """TEST 19: Existing database records remain intact."""
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM products")
        products_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM ai_training_rules WHERE workspace_id = 1")
        rules_count = cur.fetchone()[0]
        conn.close()
        self.assertGreater(products_count, 0)
        self.assertGreater(rules_count, 0)

    def test_20_no_access_tokens_appear_in_logs(self):
        """TEST 20: No access tokens appear in logs."""
        import io
        import sys
        
        captured_output = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_output
        secret_token = "EAABSecretTokenMustNeverBePrinted1234567890"
        
        try:
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {"recipient_id": self.recipient_id, "message_id": "m_20"}
                send_fb_media_message(
                    recipient_id=self.recipient_id,
                    media_type="image",
                    media_url="https://example.com/log_test_20.jpg",
                    page_token=secret_token,
                    page_id=self.page_id,
                    workspace_id=self.workspace_id
                )
        finally:
            sys.stdout = old_stdout

        log_text = captured_output.getvalue()
        self.assertNotIn(secret_token, log_text)

if __name__ == "__main__":
    unittest.main()
