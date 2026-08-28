import unittest
from app.ai_agent.gemini_brain import (
    evaluate_id_card_workflow,
    detect_sample_photos_to_send,
    get_package_sample_images,
    PACKAGE_SPECIFIC_IMAGES,
    PACKAGE_SPECIFIC_DETAILS,
)

class PackageHierarchyAndBudgetRulesTests(unittest.TestCase):

    def test_01_all_packages_ordered_correctly(self):
        """Verify get_package_sample_images returns packages in 1 to 7 serial order."""
        images = get_package_sample_images(workspace_id=1)
        self.assertEqual(len(images), 7)
        self.assertEqual(images[0], "/static/uploads/package/IMG-20260113-WA0003.jpg")  # Package 1 (70 Tk)
        self.assertEqual(images[1], "/static/uploads/package/IMG-20260113-WA0002.jpg")  # Package 2 (70 Tk)
        self.assertEqual(images[2], "/static/uploads/package/IMG-20260117-WA0023.jpg")  # Package 3 (73 Tk)
        self.assertEqual(images[3], "/static/uploads/package/IMG-20260121-WA0081.jpg")  # Package 4 (73 Tk)
        self.assertEqual(images[4], "/static/uploads/package/IMG-20260118-WA0045.jpg")  # Package 5 (83 Tk)
        self.assertEqual(images[5], "/static/uploads/package/IMG-20260113-WA0006.jpg")  # Package 6 (83 Tk)
        self.assertEqual(images[6], "/static/uploads/package/IMG-20260114-WA0057.jpg")  # Package 7 (91 Tk - Top Premium)

    def test_02_most_premium_quality_returns_package_7(self):
        """Customer asking for most premium package gets Package 07."""
        queries = [
            "সবচেয়ে প্রিমিয়াম প্যাকেজের ছবি দাও",
            "সবচেয়ে ভালো মানের প্যাকেজ কোনটা?",
            "টপ কোয়ালিটির প্যাকেজ দেখান",
            "সেরা প্যাকেজ দেখতে চাই",
            "সবচেয়ে দামি প্যাকেজ কোনটা?",
        ]
        for q in queries:
            res = evaluate_id_card_workflow(q, customer_name="Nabil", workspace_id=1)
            self.assertIsNotNone(res, f"Failed for query: {q}")
            self.assertEqual(res["response_source"], "premium_package_07_dispatch", f"Failed for query: {q}")
            self.assertEqual(len(res["matched_images"]), 1)
            self.assertEqual(res["matched_images"][0], "/static/uploads/package/IMG-20260114-WA0057.jpg")
            self.assertIn("প্যাকেজ ০৭", res["reply_text"])
            self.assertIn("৯১ টাকা", res["reply_text"])

    def test_03_lowest_budget_returns_package_1(self):
        """Customer asking with lowest budget gets Package 01."""
        queries = [
            "যার বাজেট একবারে কম তার জন্য কোন প্যাকেজ?",
            "আমাদের বাজেট কম, সবচেয়ে কম দামের প্যাকেজ দেন",
            "বাজেট একবারেই কম",
            "সবচেয়ে কম খরচের প্যাকেজ কোনটা?",
            "কম বাজেটের প্যাকেজ দেখতে চাই",
            "লো বাজেট প্যাকেজ দেখান",
        ]
        for q in queries:
            res = evaluate_id_card_workflow(q, customer_name="Karim", workspace_id=1)
            self.assertIsNotNone(res, f"Failed for query: {q}")
            self.assertEqual(res["response_source"], "budget_package_01_dispatch", f"Failed for query: {q}")
            self.assertEqual(len(res["matched_images"]), 1)
            self.assertEqual(res["matched_images"][0], "/static/uploads/package/IMG-20260113-WA0003.jpg")
            self.assertIn("প্যাকেজ ০১", res["reply_text"])
            self.assertIn("৭০ টাকা", res["reply_text"])

    def test_04_individual_packages_dispatch(self):
        """Verify each package from 1 to 7 returns its exact photo."""
        expected = {
            1: ("/static/uploads/package/IMG-20260113-WA0003.jpg", "৭০ টাকা"),
            2: ("/static/uploads/package/IMG-20260113-WA0002.jpg", "৭০ টাকা"),
            3: ("/static/uploads/package/IMG-20260117-WA0023.jpg", "৭৩ টাকা"),
            4: ("/static/uploads/package/IMG-20260121-WA0081.jpg", "৭৩ টাকা"),
            5: ("/static/uploads/package/IMG-20260118-WA0045.jpg", "৮৩ টাকা"),
            6: ("/static/uploads/package/IMG-20260113-WA0006.jpg", "৮৩ টাকা"),
            7: ("/static/uploads/package/IMG-20260114-WA0057.jpg", "৯১ টাকা"),
        }
        for pkg_no, (exp_img, exp_price) in expected.items():
            res = evaluate_id_card_workflow(f"প্যাকেজ {pkg_no} দেখান", customer_name="Rahim", workspace_id=1)
            self.assertIsNotNone(res)
            self.assertEqual(res["response_source"], f"specific_package_0{pkg_no}_dispatch")
            self.assertEqual(res["matched_images"][0], exp_img)
            self.assertIn(exp_price, res["reply_text"])

    def test_05_detect_sample_photos_to_send_ordering(self):
        """Verify detect_sample_photos_to_send uses correct serial ordering."""
        pkg_imgs = detect_sample_photos_to_send("প্যাকেজের ছবি দেখতে চাই", workspace_id=1)
        self.assertEqual(len(pkg_imgs), 7)
        self.assertEqual(pkg_imgs[0], "/static/uploads/package/IMG-20260113-WA0003.jpg")
        self.assertEqual(pkg_imgs[6], "/static/uploads/package/IMG-20260114-WA0057.jpg")

if __name__ == "__main__":
    unittest.main()
