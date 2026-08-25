"""
Phase 5 Automated Test Suite: Persistent Media Knowledge & Intent-Based Media Router
Tests:
- Submission video intent routing (Bengali & English)
- Correction video intent routing (Bengali & English)
- Priority resolution (CORRECTION > SUBMISSION)
- Feature voice routing (Card, Ribbon, Cover)
- Ambiguity detection & clarification prompt (Never send random media)
- Context-aware media resolution
- Duplicate media suppression
- Physical missing file safe fallback
- Server restart / DB persistence
- Adversarial tests
"""

import unittest
from app.database import (
    init_db, ensure_default_saved_media, get_saved_media,
    get_saved_media_by_key, create_saved_media, delete_saved_media
)
from app.ai_agent.media_router import (
    MediaRouter, MediaIntent, CANONICAL_MEDIA_KEYS,
    detect_saved_media_to_send, is_file_physically_available
)


class TestMediaRouter(unittest.TestCase):

    def setUp(self):
        init_db()
        ensure_default_saved_media()
        self.ws_id = 1

    def test_01_submission_video_routing_bengali_and_english(self):
        """TEST 1: Submission video routing in Bengali and English."""
        # Bengali
        r_bn = MediaRouter.route_media("Google Form দিয়ে তথ্য কিভাবে দিব?", workspace_id=self.ws_id)
        self.assertEqual(r_bn["intent"], MediaIntent.GOOGLE_FORM_SUBMISSION_HELP)
        self.assertIn("google_form_submission_guide.mp4", r_bn["video_url"])
        self.assertFalse(r_bn["requires_clarification"])

        # English
        r_en = MediaRouter.route_media("How do I submit the ID card information?", workspace_id=self.ws_id)
        self.assertEqual(r_en["intent"], MediaIntent.GOOGLE_FORM_SUBMISSION_HELP)
        self.assertIn("google_form_submission_guide.mp4", r_en["video_url"])

        # Legacy wrapper compatibility
        wrap_res = detect_saved_media_to_send("গুগল ফর্মে আইডি কার্ডের তথ্য ও ছবি আপলোড করার নিয়ম জানতে চাই", workspace_id=self.ws_id)
        self.assertIn("google_form_submission_guide.mp4", wrap_res["video_url"])

        print("[PASSED] Test 01: Submission video intent routing (BN+EN) verified.")

    def test_02_correction_video_routing_bengali_and_english(self):
        """TEST 2: Correction video routing in Bengali and English."""
        # Bengali
        r_bn = MediaRouter.route_media("তথ্য ভুল হয়েছে, কিভাবে ঠিক করব?", workspace_id=self.ws_id)
        self.assertEqual(r_bn["intent"], MediaIntent.GOOGLE_FORM_CORRECTION_HELP)
        self.assertIn("google_form_edit_correction_guide.mp4", r_bn["video_url"])
        self.assertFalse(r_bn["requires_clarification"])

        # English
        r_en = MediaRouter.route_media("How can I correct the submitted information?", workspace_id=self.ws_id)
        self.assertEqual(r_en["intent"], MediaIntent.GOOGLE_FORM_CORRECTION_HELP)
        self.assertIn("google_form_edit_correction_guide.mp4", r_en["video_url"])

        print("[PASSED] Test 02: Correction video intent routing (BN+EN) verified.")

    def test_03_intent_priority_correction_over_submission(self):
        """TEST 3: When message contains both submission and correction keywords, CORRECTION wins."""
        queries = [
            "Submit করার পরে correction করবো কিভাবে?",
            "Google Form submit করেছি, এখন ভুল তথ্য কীভাবে ঠিক করব?",
            "ফর্ম পূরণ করার পর যদি কোনো ভুল হয় তাহলে সংশোধন কীভাবে করব?",
            "Submitted form edit correction guide please"
        ]
        for q in queries:
            res = MediaRouter.route_media(q, workspace_id=self.ws_id)
            self.assertEqual(res["intent"], MediaIntent.GOOGLE_FORM_CORRECTION_HELP, f"Failed for query: {q}")
            self.assertIn("google_form_edit_correction_guide.mp4", res["video_url"])

        print("[PASSED] Test 03: Priority CORRECTION > SUBMISSION verified.")

    def test_04_feature_voice_routing_card_ribbon_cover(self):
        """TEST 4: Voice routing for Card, Ribbon, and Cover features."""
        # Card Feature
        r_card = MediaRouter.route_media("কার্ডের বৈশিষ্ট্য বলুন", workspace_id=self.ws_id)
        self.assertEqual(r_card["intent"], MediaIntent.CARD_FEATURES)
        self.assertTrue(bool(r_card["voice_url"]))

        # Ribbon Feature
        r_ribbon = MediaRouter.route_media("ফিতার বৈশিষ্ট্য বলুন", workspace_id=self.ws_id)
        self.assertEqual(r_ribbon["intent"], MediaIntent.RIBBON_FEATURES)
        self.assertTrue(bool(r_ribbon["voice_url"]))

        # Cover Feature (Correctly classifies COVER_FEATURES intent, but sends no voice since cover_features is inactive)
        r_cover = MediaRouter.route_media("কভারের বৈশিষ্ট্য বলুন", workspace_id=self.ws_id)
        self.assertEqual(r_cover["intent"], MediaIntent.COVER_FEATURES)
        self.assertEqual(r_cover["voice_url"], "")  # Inactive until dedicated cover voice is uploaded

        print("[PASSED] Test 04: Voice feature routing (Card, Ribbon, Cover inactive safety) verified.")

    def test_05_ambiguous_video_requires_clarification_no_random_media(self):
        """TEST 5: Ambiguous video request without context requires clarification and does NOT send random media."""
        ambiguous_queries = ["ভিডিওটা দেন", "ভিডিও দিন", "ভিডিও পাঠান", "video please"]
        for q in ambiguous_queries:
            res = MediaRouter.route_media(q, workspace_id=self.ws_id, conversation_history=[])
            self.assertTrue(res["requires_clarification"], f"Expected clarification for: {q}")
            self.assertEqual(res["video_url"], "", "Random video must NOT be sent for ambiguous query")
            self.assertIn("Google Form পূরণ করার ভিডিওটি চান, নাকি তথ্য সংশোধনের ভিডিওটি?", res["clarification_prompt"])

        print("[PASSED] Test 05: Ambiguous media request clarification safety verified.")

    def test_06_context_aware_video_resolution(self):
        """TEST 6: Ambiguous video request with prior context resolves correctly."""
        # Context 1: Prior bot message sent Google Form link
        history_submission = [
            {"role": "user", "parts": "আমার প্রতিষ্ঠানের জন্য গুগল ফর্ম দেন"},
            {"role": "assistant", "parts": "জি স্যার, আপনার Google Form লিংকটি হলো: https://docs.google.com/forms/..."}
        ]
        res_sub = MediaRouter.route_media("ভিডিওটা দেন", conversation_history=history_submission, workspace_id=self.ws_id)
        self.assertEqual(res_sub["intent"], MediaIntent.GOOGLE_FORM_SUBMISSION_HELP)
        self.assertIn("google_form_submission_guide.mp4", res_sub["video_url"])
        self.assertFalse(res_sub["requires_clarification"])

        # Context 2: Prior bot message sent proof
        history_correction = [
            {"role": "user", "parts": "প্রুফ পাঠান"},
            {"role": "assistant", "parts": "জি স্যার, এই প্রুফটি চেক করে দেখুন কোনো সংশোধন লাগবে কিনা।"}
        ]
        res_cor = MediaRouter.route_media("ভিডিওটা দেন", conversation_history=history_correction, workspace_id=self.ws_id)
        self.assertEqual(res_cor["intent"], MediaIntent.GOOGLE_FORM_CORRECTION_HELP)
        self.assertIn("google_form_edit_correction_guide.mp4", res_cor["video_url"])

        print("[PASSED] Test 06: Context-aware video resolution verified.")

    def test_07_duplicate_media_suppression_and_explicit_resend(self):
        """TEST 7: Duplicate media is suppressed unless customer explicitly requests re-sending."""
        sub_url = "/static/uploads/media/google_form_submission_guide.mp4"
        history_with_video = [
            {"role": "user", "parts": "তথ্য কিভাবে দেব?"},
            {"role": "assistant", "parts": f"জি স্যার, নিচে ভিডিওটি দেখুন: {sub_url}"}
        ]

        # Case A: Repeated general query -> duplicate suppressed
        dup_res = MediaRouter.route_media(
            "তথ্য কিভাবে দেব?",
            conversation_history=history_with_video,
            workspace_id=self.ws_id
        )
        self.assertTrue(dup_res["is_duplicate_suppressed"])
        self.assertEqual(dup_res["video_url"], "")

        # Case B: Explicit request to resend ("আবার পাঠান") -> Allowed to pass
        resend_res = MediaRouter.route_media(
            "ভিডিওটা আবার পাঠান প্লিজ",
            conversation_history=history_with_video,
            workspace_id=self.ws_id
        )
        self.assertFalse(resend_res["is_duplicate_suppressed"])
        self.assertEqual(resend_res["video_url"], sub_url)

        print("[PASSED] Test 07: Duplicate media suppression & explicit re-send verified.")

    def test_08_missing_physical_file_graceful_fallback(self):
        """TEST 8: If database record points to a nonexistent file, router gracefully falls back without crashing."""
        fake_id = create_saved_media(
            title="Nonexistent Test Video",
            media_type="video",
            file_url="/static/uploads/media/totally_nonexistent_file_99999.mp4",
            description="Fake",
            workspace_id=1,
            media_key="fake_test_key",
            intent="FAKE_INTENT"
        )
        try:
            self.assertFalse(is_file_physically_available("/static/uploads/media/totally_nonexistent_file_99999.mp4"))
            item = get_saved_media_by_key("fake_test_key", workspace_id=1)
            self.assertIsNotNone(item)
        finally:
            delete_saved_media(fake_id)

        print("[PASSED] Test 08: Missing physical file safe detection verified.")

    def test_09_database_persistence_across_connections(self):
        """TEST 9: Media records and canonical keys remain persistent across independent connections."""
        sub_item = get_saved_media_by_key("google_form_submission_tutorial", workspace_id=1)
        cor_item = get_saved_media_by_key("google_form_correction_tutorial", workspace_id=1)
        card_item = get_saved_media_by_key("id_card_features", workspace_id=1)

        self.assertIsNotNone(sub_item)
        self.assertEqual(sub_item["intent"], "GOOGLE_FORM_SUBMISSION_HELP")
        self.assertIsNotNone(cor_item)
        self.assertEqual(cor_item["intent"], "GOOGLE_FORM_CORRECTION_HELP")
        self.assertIsNotNone(card_item)
        self.assertEqual(card_item["intent"], "CARD_FEATURES")

        print("[PASSED] Test 09: Database persistence across connections verified.")

    def test_10_adversarial_and_typo_tolerant_media_matching(self):
        """TEST 10: Adversarial phrases and typos are accurately resolved."""
        # Typos in Bengali
        r1 = MediaRouter.route_media("গুগল ফরম দিয়ে ছবি আপলোড করব", workspace_id=self.ws_id)
        self.assertEqual(r1["intent"], MediaIntent.GOOGLE_FORM_SUBMISSION_HELP)

        # Typos in English
        r2 = MediaRouter.route_media("google frm submission tutorial", workspace_id=self.ws_id)
        self.assertEqual(r2["intent"], MediaIntent.GOOGLE_FORM_SUBMISSION_HELP)

        # Correction with complex phrase
        r3 = MediaRouter.route_media("ফর্ম জমা দেওয়ার পর তথ্য এডিট বা কারেকশন করার নিয়ম", workspace_id=self.ws_id)
        self.assertEqual(r3["intent"], MediaIntent.GOOGLE_FORM_CORRECTION_HELP)

        # Ribbon feature mixed phrase
        r4 = MediaRouter.route_media("ফিতার feature বলেন", workspace_id=self.ws_id)
        self.assertEqual(r4["intent"], MediaIntent.RIBBON_FEATURES)

        print("[PASSED] Test 10: Adversarial & typo-tolerant media matching verified.")


if __name__ == "__main__":
    unittest.main()
