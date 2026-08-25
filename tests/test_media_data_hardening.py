"""
Phase 5.1 Automated Test Suite: Media Data Correction & Hardening
Tests:
1. cover_features cannot use id_card_features file
2. Inactive cover media cannot dispatch voice
3. Missing media file cannot dispatch
4. Only one active canonical record per media_key
5. Correction intent selects correction video
6. Submission intent selects submission video
7. Special offer voice blocked below 80
8. Valid active media dispatch remains functional
"""

import unittest
from app.database import (
    init_db, ensure_default_saved_media, get_saved_media,
    get_saved_media_by_key, create_saved_media, delete_saved_media,
    get_db_connection
)
from app.ai_agent.media_router import (
    MediaRouter, MediaIntent, CANONICAL_MEDIA_KEYS,
    is_file_physically_available
)
from app.ai_agent.response_validator import ResponseValidator


class TestMediaDataHardening(unittest.TestCase):

    def setUp(self):
        init_db()
        ensure_default_saved_media()
        self.ws_id = 1

    def test_01_cover_features_does_not_share_id_card_file(self):
        """TEST 1: cover_features cannot use id_card_features file."""
        card_media = get_saved_media_by_key("id_card_features", workspace_id=self.ws_id)
        self.assertIsNotNone(card_media)

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM saved_media WHERE media_key = 'cover_features' AND workspace_id = 1")
        cover_row = c.fetchone()
        conn.close()

        self.assertIsNotNone(cover_row)
        cover_file = str(cover_row["file_url"] or "")
        card_file = str(card_media["file_url"] or "")

        # Strict check: Cover features file MUST NOT match card features file
        self.assertNotEqual(cover_file, card_file)
        self.assertNotIn("id_card_features_voice_note", cover_file)
        print("[PASSED] Test 01: cover_features does not share id_card_features file.")

    def test_02_inactive_cover_media_cannot_dispatch(self):
        """TEST 2: Inactive cover media cannot dispatch voice note."""
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT is_active FROM saved_media WHERE media_key = 'cover_features' AND workspace_id = 1")
        row = c.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(int(row["is_active"]), 0, "cover_features must be inactive until uploaded")

        # Routing check
        res = MediaRouter.route_media("কভারের বৈশিষ্ট্য বলুন", workspace_id=self.ws_id)
        self.assertEqual(res["intent"], MediaIntent.COVER_FEATURES)
        self.assertEqual(res["voice_url"], "", "Inactive cover voice MUST NOT be dispatched")
        print("[PASSED] Test 02: Inactive cover media does not dispatch.")

    def test_03_missing_physical_file_cannot_dispatch(self):
        """TEST 3: Missing media file cannot dispatch."""
        fake_id = create_saved_media(
            title="Missing File Test Video",
            media_type="video",
            file_url="/static/uploads/nonexistent/missing_file_00000.mp4",
            workspace_id=1,
            media_key="test_missing_key",
            intent="TEST_MISSING_INTENT"
        )
        try:
            self.assertFalse(is_file_physically_available("/static/uploads/nonexistent/missing_file_00000.mp4"))
        finally:
            delete_saved_media(fake_id)

        print("[PASSED] Test 03: Missing physical file cannot dispatch.")

    def test_04_only_one_active_canonical_record_per_media_key(self):
        """TEST 4: Only one active canonical record per media_key in workspace."""
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            SELECT media_key, COUNT(*) as cnt
            FROM saved_media
            WHERE workspace_id = 1 AND is_active = 1
            GROUP BY media_key
            HAVING cnt > 1
        """)
        dup_active = c.fetchall()
        conn.close()

        self.assertEqual(len(dup_active), 0, f"Found conflicting multiple active records for media keys: {dup_active}")
        print("[PASSED] Test 04: Exactly one active record per media_key verified.")

    def test_05_correction_intent_selects_correction_video(self):
        """TEST 5: Correction intent selects correction video."""
        res = MediaRouter.route_media("Submit করার পরে ভুল তথ্য সংশোধন করব কিভাবে?", workspace_id=self.ws_id)
        self.assertEqual(res["intent"], MediaIntent.GOOGLE_FORM_CORRECTION_HELP)
        self.assertIn("google_form_edit_correction_guide.mp4", res["video_url"])
        print("[PASSED] Test 05: Correction intent selects correction video.")

    def test_06_submission_intent_selects_submission_video(self):
        """TEST 6: Submission intent selects submission video."""
        res = MediaRouter.route_media("গুগল ফর্মে তথ্য কিভাবে দিব এবং ছবি আপলোড করব?", workspace_id=self.ws_id)
        self.assertEqual(res["intent"], MediaIntent.GOOGLE_FORM_SUBMISSION_HELP)
        self.assertIn("google_form_submission_guide.mp4", res["video_url"])
        print("[PASSED] Test 06: Submission intent selects submission video.")

    def test_07_special_offer_voice_blocked_below_80(self):
        """TEST 7: Special offer voice blocked below 80 pcs by ResponseValidator."""
        special_voice = "/static/uploads/voice/PTT-20260119-WA0105.mp3"

        # Below 80 (e.g. 50 pcs)
        draft_50 = {
            "reply_text": "জি স্যার, স্যাম্পল পাঠানো হলো।",
            "voice_url": special_voice,
            "matched_images": []
        }
        val_50 = ResponseValidator.validate_and_sanitize(
            draft_response=draft_50,
            customer_message="৫০টা আইডি কার্ড লাগবে",
            workspace_id=self.ws_id
        )
        self.assertEqual(val_50["voice_url"], "")
        self.assertIn("SPECIAL_VOICE_STRIPPED_UNDER_80", val_50["validation_flags"])

        # 80+ pcs (e.g. 100 pcs)
        draft_100 = {
            "reply_text": "জি স্যার, স্যাম্পল পাঠানো হলো।",
            "voice_url": special_voice,
            "matched_images": []
        }
        val_100 = ResponseValidator.validate_and_sanitize(
            draft_response=draft_100,
            customer_message="১০০টা আইডি কার্ড লাগবে",
            workspace_id=self.ws_id
        )
        self.assertEqual(val_100["voice_url"], special_voice)
        print("[PASSED] Test 07: Special offer voice blocked under 80 & permitted for 80+.")

    def test_08_valid_active_media_dispatch_functional(self):
        """TEST 8: Valid active media dispatch remains fully functional."""
        # 1. Submission Video
        r1 = MediaRouter.route_media("তথ্য আপলোড করব কিভাবে?", workspace_id=self.ws_id)
        self.assertTrue(bool(r1["video_url"]))

        # 2. Correction Video
        r2 = MediaRouter.route_media("তথ্য ভুল হলে এডিট করার নিয়ম", workspace_id=self.ws_id)
        self.assertTrue(bool(r2["video_url"]))

        # 3. Card Quality Voice
        r3 = MediaRouter.route_media("আইডি কার্ডের কোয়ালিটি কেমন?", workspace_id=self.ws_id)
        self.assertTrue(bool(r3["voice_url"]))

        # 4. Ribbon Quality Voice
        r4 = MediaRouter.route_media("ফিতা এর কোয়ালিটি কেমন হবে?", workspace_id=self.ws_id)
        self.assertTrue(bool(r4["voice_url"]))

        print("[PASSED] Test 08: All active canonical media items are functional.")


if __name__ == "__main__":
    unittest.main()
