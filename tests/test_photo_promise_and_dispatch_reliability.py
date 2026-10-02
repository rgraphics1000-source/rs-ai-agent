import unittest
import asyncio
from unittest.mock import patch, MagicMock

from app.ai_agent.gemini_brain import (
    has_customer_consented_or_requested_photos,
    detect_sample_photos_to_send,
    evaluate_id_card_workflow,
    process_customer_message,
    get_package_sample_images,
    get_id_card_sample_images
)
from app.channels.debouncer import PendingBatch

class TestPhotoPromiseAndDispatchReliability(unittest.IsolatedAsyncioTestCase):

    def test_01_colloquial_photo_requests_recognized(self):
        """Verify various colloquial Bengali photo requests grant consent."""
        queries = [
            "একটু ছবি দেন তো",
            "ছবিগুলা দেন",
            "ছবিগুলো দিন",
            "ছবি দেওয়া যাবে?",
            "ডিজাইন দেখান",
            "কার্ডের ডিজাইন দেখান",
            "প্যাকেজের রেট কত ছবি দেন",
            "দাম সহ প্যাকেজের ছবি পাঠান",
            "প্যাকেজ গুলোর ছবি দিন"
        ]
        for q in queries:
            self.assertTrue(
                has_customer_consented_or_requested_photos(q),
                f"Expected True for query: '{q}'"
            )

    def test_02_affirmative_response_after_bot_photo_offer(self):
        """Single-word affirmative customer replies properly resolve against prior bot photo offer."""
        history = [
            {"sender": "user", "content": "৫০ পিস কার্ড বানাবো"},
            {"sender": "bot", "content": "জি স্যার, ৫০ পিস অর্ডারে আমাদের রেগুলার রেট প্রযোজ্য হবে। আপনি কি আমাদের রেডি প্যাকেজের ছবি ও রেট দেখতে চাচ্ছেন?"}
        ]
        affirmative_words = ["জি", "হ্যাঁ", "হুম", "অবশ্যই", "পাঠান", "দেখান", "দিন", "দেন", "ok", "yes"]
        for word in affirmative_words:
            self.assertTrue(
                has_customer_consented_or_requested_photos(word, conversation_history=history),
                f"Expected True for affirmative word '{word}' after bot photo offer"
            )

    def test_03_bot_promising_images_triggers_photo_dispatch_on_text_turn(self):
        """
        When bot reply contains 'অবশ্যই দিচ্ছি' or 'পাঠিয়ে দিচ্ছি', detect_sample_photos_to_send
        MUST deliver photos even on a text turn (not just voice turn).
        """
        history = [
            {"sender": "user", "content": "প্যাকেজের ছবি দেন"},
            {"sender": "bot", "content": "জি স্যার অবশ্যই দিচ্ছি।"}
        ]
        photos = detect_sample_photos_to_send(
            user_msg="প্যাকেজের ছবি দেন",
            conversation_history=history,
            bot_reply="জি স্যার অবশ্যই দিচ্ছি।",
            workspace_id=1
        )
        self.assertGreater(len(photos), 0, "detect_sample_photos_to_send must dispatch photos when bot promises 'অবশ্যই দিচ্ছি'!")

    def test_04_deduplication_fallback_when_customer_consents(self):
        """
        When a customer agrees or asks for photos, even if all photos were marked seen in history,
        fallback ensures unseen_images falls back to selected_images instead of being empty.
        """
        all_pkg_imgs = get_package_sample_images(workspace_id=1)
        # Simulate all images already sent in history
        history = [
            {"sender": "bot", "content": "ছবিগুলো পাঠাবো কি?", "image_url": all_pkg_imgs[0]},
            {"sender": "bot", "content": "স্যাম্পল", "image_url": all_pkg_imgs[1]}
        ]
        photos = detect_sample_photos_to_send(
            user_msg="হ্যাঁ পাঠান",
            conversation_history=history,
            bot_reply="জি স্যার অবশ্যই দিচ্ছি।",
            workspace_id=1
        )
        self.assertGreater(len(photos), 0, "Deduplication must fall back to images when customer explicitly consented!")

    async def test_05_whatsapp_channel_delivers_images_on_bot_promise_text_message(self):
        """
        WhatsApp batch worker must NOT block image delivery when bot says 'জি স্যার অবশ্যই দিচ্ছি।'
        on a text message.
        """
        from app.channels.whatsapp import process_whatsapp_batch

        batch = PendingBatch(
            channel="whatsapp",
            workspace_id=1,
            sender_id="8801700000002",
            customer_name="Test Customer 2",
            initial_version=1
        )
        batch.messages.append({"id": "wa_msg_1", "text": "প্যাকেজের ছবি দেন"})

        fake_ai_result = {
            "reply_text": "জি স্যার অবশ্যই দিচ্ছি।",
            "media_sequence": [{"type": "images", "urls": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]}],
            "matched_images": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]
        }

        with patch("app.channels.whatsapp.process_customer_message", return_value=fake_ai_result), \
             patch("app.channels.whatsapp.send_whatsapp_message", return_value=True), \
             patch("app.channels.whatsapp.send_whatsapp_image_detailed", return_value={"success": True, "message_id": "test_msg_id"}) as mock_wa_img, \
             patch("app.channels.whatsapp.record_conversation_message"):
            await process_whatsapp_batch(batch)

        self.assertGreater(mock_wa_img.call_count, 0, "WhatsApp worker must deliver photos when bot promised 'অবশ্যই দিচ্ছি'!")

    async def test_06_facebook_channel_delivers_images_on_bot_promise_text_message(self):
        """
        Facebook batch worker must NOT block image delivery when bot says 'জি স্যার অবশ্যই দিচ্ছি।'
        on a text message.
        """
        from app.channels.facebook import process_facebook_batch

        batch = PendingBatch(
            channel="facebook",
            workspace_id=1,
            sender_id="fb_user_456",
            customer_name="Test FB Customer",
            initial_version=1
        )
        batch.messages.append({"id": "fb_msg_2", "text": "একটু ছবি দেন তো"})

        fake_ai_result = {
            "reply_text": "জি স্যার অবশ্যই দিচ্ছি।",
            "media_sequence": [{"type": "images", "urls": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]}],
            "matched_images": ["/static/uploads/package/IMG-20260114-WA0057.jpg"]
        }

        with patch("app.channels.facebook.process_customer_message", return_value=fake_ai_result), \
             patch("app.channels.facebook.send_fb_text_message", return_value=True), \
             patch("app.channels.facebook.send_fb_media_message_detailed", return_value={"success": True, "message_id": "fb_msg_id"}) as mock_fb_img, \
             patch("app.channels.facebook.record_conversation_message"):
            await process_facebook_batch(batch)

        self.assertGreater(mock_fb_img.call_count, 0, "Facebook worker must deliver photos when bot promised 'অবশ্যই দিচ্ছি'!")

    async def test_07_pure_price_query_does_not_promise_or_send_photos(self):
        """
        Customer asking only for price ('আইডি কার্ডের দাম কত?') must receive price info,
        must NOT receive photos, and reply_text must NOT contain false promise 'অবশ্যই দিচ্ছি'.
        """
        res = await process_customer_message(
            message_text="আইডি কার্ডের দাম কত?",
            customer_name="Rafiq",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["matched_images"], [], "Pure price query must have empty matched_images")
        self.assertNotIn("অবশ্যই দিচ্ছি", res["reply_text"], "Must not falsely say 'অবশ্যই দিচ্ছি' when no photos attached")
        self.assertNotIn("নিচে ছবি দেওয়া হলো", res["reply_text"])

    def test_08_package_with_price_query_properly_dispatches_workflow(self):
        """
        Customer saying 'প্যাকেজের রেট কত ছবি দেন' is asking for package photos with price,
        and must trigger ready_package_dispatch with images.
        """
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজের রেট কত ছবি দেন",
            customer_name="Shuvo",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "ready_package_dispatch")
        self.assertGreater(len(res["matched_images"]), 0)

    def test_09_ribbon_price_query_returns_ribbon_price_without_images(self):
        """
        Customer asking 'ফিতা কতো কর' or 'ফিতা কত করে' must receive ribbon price (28/25 Tk),
        must NOT receive package photos, and matched_images must be empty.
        """
        for q in ["ফিতা কতো কর", "ফিতা কত করে", "ফিতার দাম কত", "ফিতা কতো"]:
            res = evaluate_id_card_workflow(
                message_text=q,
                customer_name="Customer",
                workspace_id=1
            )
            self.assertIsNotNone(res, f"Workflow must handle ribbon query '{q}'")
            self.assertEqual(res["response_source"], "ribbon_price_inquiry")
            self.assertEqual(res["matched_images"], [])
            self.assertIn("২৮ টাকা", res["reply_text"])
            self.assertIn("২৫ টাকা", res["reply_text"])

    def test_10_age_dekhi_triggers_ready_package_dispatch_after_bot_offer(self):
        """
        Customer replying 'আগে দেখি' after bot offered ready packages grants consent
        and dispatches all 7 ready packages.
        """
        history = [
            {"sender": "bot", "content": "জি স্যার, ২০০ পিসের ক্ষেত্রে আমাদের প্রিমিয়াম ৭ নম্বর প্যাকেজটি (মেটাল কভারসহ) সর্বোচ্চ ছাড়ের পরও সর্বনিম্ন ৮২ টাকা পর্যন্ত রাখা সম্ভব। আমি কি তাহলে আমাদের রেডি প্যাকেজগুলোর ছবি ও বিস্তারিত পাঠাবো স্যার?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="আগে দেখি",
            conversation_history=history,
            customer_name="Hafiz",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "ready_package_dispatch")
        self.assertEqual(len(res["matched_images"]), 7)

    def test_11_gemini_elaborate_promise_phrase_recognized(self):
        """
        When bot reply is 'জি স্যার, অবশ্যই। আমাদের কার্ড, ফিতা এবং কভারের আকর্ষণীয় রেডি প্যাকেজগুলোর ছবি ও বিস্তারিত নিচে দেওয়া হলো।',
        detect_sample_photos_to_send must dispatch photos when consented, and drop when price query.
        """
        elaborate_reply = "জি স্যার, অবশ্যই। আমাদের কার্ড, ফিতা এবং কভারের আকর্ষণীয় রেডি প্যাকেজগুলোর ছবি ও বিস্তারিত নিচে দেওয়া হলো।"
        # Consented case
        photos = detect_sample_photos_to_send("আগে দেখি", bot_reply=elaborate_reply, workspace_id=1)
        self.assertEqual(len(photos), 7)
        # Price query case
        photos_price = detect_sample_photos_to_send("ফিতা কতো কর", bot_reply=elaborate_reply, workspace_id=1)
        self.assertEqual(photos_price, [])

    def test_12_keyring_query_does_not_trigger_package_7_quote(self):
        """
        When bot prompted for package selection ('আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।'),
        and customer asks 'চাবির রিং ও বানান নাকি?', the bot must NOT misinterpret this as Package 7 selection
        or bargaining inquiry. It must accurately answer about customized keyrings.
        """
        history = [
            {"sender": "bot", "content": "আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।"}
        ]
        res = evaluate_id_card_workflow(
            message_text="চাবির রিং ও বানান নাকি?",
            conversation_history=history,
            customer_name="Customer",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "custom_keyring_inquiry")
        self.assertNotIn("৭ নম্বর প্যাকেজ", res["reply_text"])
        self.assertNotIn("৯১ টাকা", res["reply_text"])
        self.assertIn("চাবির রিং", res["reply_text"])

    def test_13_delivery_query_does_not_trigger_package_7_quote(self):
        """
        Customer asking 'ডেলিভারি চার্জ কত?' after package prompt must receive delivery fee details,
        NOT Package 7 quote.
        """
        history = [
            {"sender": "bot", "content": "আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।"}
        ]
        res = evaluate_id_card_workflow(
            message_text="ডেলিভারি চার্জ কত?",
            conversation_history=history,
            customer_name="Customer",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "delivery_charge_inquiry")
        self.assertNotIn("৭ নম্বর প্যাকেজ", res["reply_text"])
        self.assertIn("৮০ টাকা", res["reply_text"])
        self.assertIn("১৩০ টাকা", res["reply_text"])

    def test_14_production_timeline_query_does_not_trigger_package_7_quote(self):
        """
        Customer asking 'কতদিন সময় লাগবে?' after package prompt must receive timeline details,
        NOT Package 7 quote.
        """
        history = [
            {"sender": "bot", "content": "আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।"}
        ]
        res = evaluate_id_card_workflow(
            message_text="কতদিন সময় লাগবে?",
            conversation_history=history,
            customer_name="Customer",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "production_timeline_inquiry")
        self.assertNotIn("৭ নম্বর প্যাকেজ", res["reply_text"])
        self.assertIn("৫ থেকে ৬ দিন", res["reply_text"])


if __name__ == "__main__":
    unittest.main()

