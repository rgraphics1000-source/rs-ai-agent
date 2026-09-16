import unittest
import asyncio
from unittest.mock import patch, MagicMock

from app.ai_agent.gemini_brain import (
    has_customer_consented_or_requested_photos,
    detect_sample_photos_to_send,
    evaluate_id_card_workflow,
    process_customer_message,
    get_package_sample_images
)

class TestPhotoConsentGuard(unittest.IsolatedAsyncioTestCase):

    def test_01_no_consent_on_price_inquiry(self):
        """Customer asking for price without photo keywords must NEVER be treated as consenting to photos."""
        price_queries = [
            "আইডি কার্ডের দাম কত?",
            "দাম কত করে?",
            "খরচ কত পড়বে?",
            "রেট কত?",
            "কোনটার দাম কত?",
            "প্যাকেজের দাম কত",
            "কার্ডের দাম কত",
            "ফিতার দাম কত",
            "কভারের দাম কত"
        ]
        for q in price_queries:
            self.assertFalse(
                has_customer_consented_or_requested_photos(q),
                f"Expected False for price query: '{q}'"
            )

    def test_02_no_consent_on_quantity_statement(self):
        """Customer mentioning order quantity has NOT consented to receive photos yet."""
        qty_queries = [
            "আমি ৫০ পিস বানাবো",
            "১০০ পিস আইডি কার্ড লাগবে",
            "৩০ টা হবে?",
            "৮০ পিস",
            "200 pcs",
            "১৫ টা"
        ]
        for q in qty_queries:
            self.assertFalse(
                has_customer_consented_or_requested_photos(q),
                f"Expected False for quantity query: '{q}'"
            )

    def test_03_no_consent_on_refusal_or_stop(self):
        """Customer refusal phrases strictly return False even if photo words are mentioned."""
        refusal_queries = [
            "না",
            "লাগবে না",
            "ছবি লাগবে না",
            "আর ছবি লাগবে না",
            "স্যাম্পল লাগবে না",
            "দরকার নেই",
            "দরকার নাই",
            "না থাক",
            "ফটো লাগবে না",
            "চাই না",
            "নেব না",
            "stop",
            "no"
        ]
        for q in refusal_queries:
            self.assertFalse(
                has_customer_consented_or_requested_photos(q),
                f"Expected False for refusal query: '{q}'"
            )

    def test_04_no_consent_on_address_or_quality(self):
        """General questions about shop address, location or quality do not grant photo consent."""
        general_queries = [
            "আপনাদের ঠিকানা কি?",
            "লোকেশন কোথায়?",
            "দোকান কোথায় আপনাদের?",
            "কোয়ালিটি কেমন হবে?",
            "মান কেমন?",
            "কেমন আছেন?",
            "আসসালামু আলাইকুম",
            "Hi",
            "Hello"
        ]
        for q in general_queries:
            self.assertFalse(
                has_customer_consented_or_requested_photos(q),
                f"Expected False for general query: '{q}'"
            )

    def test_05_explicit_request_grants_photo_consent(self):
        """Customer explicitly asking to see photos/samples grants consent."""
        explicit_queries = [
            "ছবি দেখতে চাই",
            "ছবি দেখান",
            "ছবি পাঠান",
            "ছবি দিন",
            "ছবি দেন",
            "স্যাম্পল দেখান",
            "স্যাম্পল পাঠান",
            "স্যাম্পল দিন",
            "স্যাম্পল দেন",
            "স্যাম্পল দেখতে চাই",
            "পিক দেন",
            "পিক দেখান",
            "ফটো পাঠান",
            "ফটো দেন",
            "কাজের স্যাম্পল দেখতে চাই",
            "কাজের ছবি দিন",
            "কার্ডের ছবি দেখান",
            "ফিতার স্যাম্পল পাঠান",
            "কভারের ছবি দিন",
            "শুধু কার্ডের ছবি",
            "রেডি প্যাকেজের ছবি দিন",
            "প্যাকেজ ৩ দেখান",
            "সবচেয়ে প্রিমিয়াম প্যাকেজের ছবি দাও",
            "টপ কোয়ালিটির প্যাকেজ দেখান",
            "সেরা প্যাকেজ দেখতে চাই",
            "কম বাজেটের প্যাকেজ দেখতে চাই",
            "লো বাজেট প্যাকেজ দেখান"
        ]
        for q in explicit_queries:
            self.assertTrue(
                has_customer_consented_or_requested_photos(q),
                f"Expected True for explicit request query: '{q}'"
            )

    def test_06_agreement_after_bot_photo_offer_grants_consent(self):
        """Customer saying yes/send after bot offered photos grants consent."""
        bot_history = [
            {"sender": "user", "content": "১০০ পিস বানাবো"},
            {"sender": "bot", "content": "জি স্যার, ১০০ পিস অর্ডারে রেগুলার পাইকারি রেট প্রযোজ্য হবে। আমি কি আমাদের কার্ড, ফিতা ও কভারের স্যাম্পল ছবিগুলো পাঠাবো স্যার?"}
        ]
        agreement_words = [
            "হ্যাঁ",
            "জি",
            "হুম",
            "পাঠান",
            "দেখান",
            "দিন",
            "দেন",
            "আচ্ছা দিন",
            "আচ্ছা পাঠান",
            "পাঠিয়ে দিন",
            "পাঠিয়ে দেন",
            "yes",
            "sure",
            "ok",
            "সেন্ড করুন"
        ]
        for w in agreement_words:
            self.assertTrue(
                has_customer_consented_or_requested_photos(w, conversation_history=bot_history),
                f"Expected True for agreement word '{w}' after bot photo offer"
            )

    def test_07_agreement_after_non_photo_question_does_not_grant_consent(self):
        """Saying 'হ্যাঁ' when bot asked for institution name or phone number does NOT grant photo consent."""
        non_photo_history = [
            {"sender": "user", "content": "আইডি কার্ড বানাবো"},
            {"sender": "bot", "content": "জি স্যার, আপনার প্রতিষ্ঠানের নাম কি জানাবেন প্লিজ?"}
        ]
        self.assertFalse(
            has_customer_consented_or_requested_photos("হ্যাঁ", conversation_history=non_photo_history)
        )
        self.assertFalse(
            has_customer_consented_or_requested_photos("জি", conversation_history=non_photo_history)
        )

    def test_08_detect_sample_photos_blocks_bot_hallucination_without_consent(self):
        """
        Even if Gemini bot_reply says 'নিচে ছবি দেওয়া হলো', detect_sample_photos_to_send MUST
        return [] if the customer only asked for price or quantity without requesting photos.
        """
        res = detect_sample_photos_to_send(
            user_msg="আইডি কার্ডের দাম কত?",
            conversation_history=[
                {"sender": "user", "content": "আইডি কার্ডের দাম কত?"}
            ],
            bot_reply="জি স্যার, নিচে আমাদের স্যাম্পল ছবিগুলো দেওয়া হলো:",
            workspace_id=1
        )
        self.assertEqual(res, [], "Must return empty list when customer only asked for price!")

        res_qty = detect_sample_photos_to_send(
            user_msg="৫০ পিস বানাবো",
            conversation_history=[
                {"sender": "user", "content": "৫০ পিস বানাবো"}
            ],
            bot_reply="জি স্যার, নিচে ছবিগুলো দেওয়া হলো।",
            workspace_id=1
        )
        self.assertEqual(res_qty, [], "Must return empty list when customer only stated quantity!")

    async def test_09_process_customer_message_enforces_photo_consent(self):
        """process_customer_message returns empty matched_images when customer did not consent."""
        res = await process_customer_message(
            message_text="আইডি কার্ডের দাম কত?",
            customer_name="Kamal",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["matched_images"], [], "Must not attach images on price inquiry without consent")
        self.assertNotIn("নিচে ছবি দেওয়া হলো", res["reply_text"])
        self.assertNotIn("নিচে আমাদের স্যাম্পল ছবিগুলো দেওয়া হলো", res["reply_text"])

    async def test_10_process_customer_message_dispatches_when_consented(self):
        """process_customer_message dispatches images when customer explicitly asks for samples."""
        res = await process_customer_message(
            message_text="স্যাম্পল দেখতে চাই",
            customer_name="Kamal",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertGreater(len(res["matched_images"]), 0, "Must attach images when customer explicitly asked for samples")

    async def test_11_whatsapp_channel_guard_drops_unconsented_images(self):
        """WhatsApp process_whatsapp_batch strictly blocks images if user did not request or consent to photos."""
        from app.channels.debouncer import PendingBatch
        from app.channels.whatsapp import process_whatsapp_batch

        batch = PendingBatch(
            channel="whatsapp",
            workspace_id=1,
            sender_id="8801700000001",
            customer_name="Test Customer",
            initial_version=1
        )
        batch.messages.append({"id": "msg1", "text": "দাম কত?"})

        fake_ai_result = {
            "reply_text": "আমাদের প্রতিটি কার্ডের মূল্য ৩৫ টাকা।",
            "media_sequence": [{"type": "images", "urls": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]}],
            "matched_images": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]
        }

        with patch("app.channels.whatsapp.process_customer_message", return_value=fake_ai_result), \
             patch("app.channels.whatsapp.send_whatsapp_message", return_value=True), \
             patch("app.channels.whatsapp.send_whatsapp_image_detailed") as mock_send_img, \
             patch("app.channels.whatsapp.record_conversation_message"):
            await process_whatsapp_batch(batch)

        # Image sending function must NEVER be called because customer only said "দাম কত?"
        self.assertEqual(mock_send_img.call_count, 0, "WhatsApp worker must not dispatch images without customer consent!")

    async def test_12_facebook_channel_guard_drops_unconsented_images(self):
        """Facebook process_facebook_batch strictly blocks images if user did not request or consent to photos."""
        from app.channels.debouncer import PendingBatch
        from app.channels.facebook import process_facebook_batch

        batch = PendingBatch(
            channel="facebook",
            workspace_id=1,
            sender_id="fb_user_123",
            customer_name="Test Customer",
            initial_version=1
        )
        batch.messages.append({"id": "fb_msg1", "text": "আইডি কার্ডের খরচ কত?"})

        fake_ai_result = {
            "reply_text": "আমাদের কার্ডের মূল্য ৩৫ টাকা।",
            "media_sequence": [{"type": "images", "urls": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]}],
            "matched_images": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]
        }

        with patch("app.channels.facebook.process_customer_message", return_value=fake_ai_result), \
             patch("app.channels.facebook.send_fb_text_message", return_value=True), \
             patch("app.channels.facebook.send_fb_media_message_detailed") as mock_fb_img, \
             patch("app.channels.facebook.record_conversation_message"):
            await process_facebook_batch(batch)

        # Facebook media sending must NEVER be called because customer only asked for price
        self.assertEqual(mock_fb_img.call_count, 0, "Facebook worker must not dispatch images without customer consent!")

if __name__ == "__main__":
    unittest.main()
