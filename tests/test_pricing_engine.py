"""
Phase 3 Automated Test Suite: Authoritative Pricing Engine & Quantity Tiers
Tests:
- 79 -> REGULAR Tier
- 80 -> BULK Tier
- 81 -> BULK Tier
- 90 -> BULK Tier
- 99 -> BULK Tier
- 100 -> BULK Tier
- Verification that 80-99 is NOT a separate tier
- Package 7 (91 Tk base, max 9 Tk discount, min 82 Tk)
- Package 1-6 (max 5 Tk discount)
- Small order tier 30-49 (+10 Tk surcharge, no discount)
- Regular tier 50-79 (no discount)
- Upfront quote is always regular rate (no upfront discount)
- Delivery & COD calculations
"""

import unittest
from app.ai_agent.pricing_engine import (
    QuantityTier, get_quantity_tier, calculate_package_price,
    negotiate_step, calculate_delivery_and_cod, normalize_package_id,
    PACKAGE_CATALOG
)


class TestPricingEngine(unittest.TestCase):

    def test_01_boundary_and_tier_classification(self):
        """Test exact quantity boundaries and tier classification."""
        # < 30 pcs -> UNDER_MOQ
        self.assertEqual(get_quantity_tier(1), QuantityTier.UNDER_MOQ)
        self.assertEqual(get_quantity_tier(20), QuantityTier.UNDER_MOQ)
        self.assertEqual(get_quantity_tier(29), QuantityTier.UNDER_MOQ)

        # 30-49 pcs -> SMALL_ORDER
        self.assertEqual(get_quantity_tier(30), QuantityTier.SMALL_ORDER)
        self.assertEqual(get_quantity_tier(40), QuantityTier.SMALL_ORDER)
        self.assertEqual(get_quantity_tier(49), QuantityTier.SMALL_ORDER)

        # 50-79 pcs -> REGULAR
        self.assertEqual(get_quantity_tier(50), QuantityTier.REGULAR)
        self.assertEqual(get_quantity_tier(60), QuantityTier.REGULAR)
        self.assertEqual(get_quantity_tier(75), QuantityTier.REGULAR)
        self.assertEqual(get_quantity_tier(79), QuantityTier.REGULAR)

        # 80+ pcs -> BULK Tier (80, 81, 90, 99, 100, 200, 300+)
        self.assertEqual(get_quantity_tier(80), QuantityTier.BULK)
        self.assertEqual(get_quantity_tier(81), QuantityTier.BULK)
        self.assertEqual(get_quantity_tier(90), QuantityTier.BULK)
        self.assertEqual(get_quantity_tier(99), QuantityTier.BULK)
        self.assertEqual(get_quantity_tier(100), QuantityTier.BULK)
        self.assertEqual(get_quantity_tier(250), QuantityTier.BULK)
        self.assertEqual(get_quantity_tier(500), QuantityTier.BULK)

        print("[PASSED] Test 01: Tier classifications (79=REGULAR, 80..100+=BULK) verified.")

    def test_02_no_separate_80_99_tier_guarantee(self):
        """Guarantee that 80-99 is NOT a distinct tier enum and shares identical BULK classification with 100+."""
        tier_80 = get_quantity_tier(80)
        tier_81 = get_quantity_tier(81)
        tier_90 = get_quantity_tier(90)
        tier_99 = get_quantity_tier(99)
        tier_100 = get_quantity_tier(100)

        self.assertEqual(tier_80, QuantityTier.BULK)
        self.assertEqual(tier_81, QuantityTier.BULK)
        self.assertEqual(tier_90, QuantityTier.BULK)
        self.assertEqual(tier_99, QuantityTier.BULK)
        self.assertEqual(tier_100, QuantityTier.BULK)

        # All 4 valid tiers only
        all_tiers = list(QuantityTier)
        self.assertEqual(len(all_tiers), 4)
        self.assertIn(QuantityTier.UNDER_MOQ, all_tiers)
        self.assertIn(QuantityTier.SMALL_ORDER, all_tiers)
        self.assertIn(QuantityTier.REGULAR, all_tiers)
        self.assertIn(QuantityTier.BULK, all_tiers)

        print("[PASSED] Test 02: Zero separate 80-99 tier confirmed.")

    def test_03_small_order_tier_30_49_surcharge_and_no_discount(self):
        """Test 30-49 pcs gets +10 Tk surcharge and 0 discount."""
        for q in [30, 35, 45, 49]:
            # Package 1 (70 Tk regular -> 80 Tk upfront)
            p1 = calculate_package_price(package_id="1", quantity=q)
            self.assertEqual(p1["upfront_unit_price"], 80.0)
            self.assertEqual(p1["surcharge_per_unit"], 10.0)
            self.assertEqual(p1["max_allowed_discount"], 0.0)
            self.assertFalse(p1["is_discount_allowed"])
            self.assertFalse(p1["special_offer_voice_eligible"])

            # Package 7 (91 Tk regular -> 101 Tk upfront)
            p7 = calculate_package_price(package_id="7", quantity=q)
            self.assertEqual(p7["upfront_unit_price"], 101.0)
            self.assertEqual(p7["surcharge_per_unit"], 10.0)
            self.assertEqual(p7["max_allowed_discount"], 0.0)
            self.assertFalse(p7["is_discount_allowed"])

        # Negotiation attempt on 30-49 must be refused
        neg = negotiate_step(package_id="7", quantity=40)
        self.assertEqual(neg["status"], "discount_refused_tier_limit")
        self.assertEqual(neg["offered_discount"], 0.0)

        print("[PASSED] Test 03: Small Order Tier 30-49 surcharge & discount refusal verified.")

    def test_04_regular_tier_50_79_fixed_regular_price_no_discount(self):
        """Test 50-79 pcs gets fixed regular price and 0 discount."""
        for q in [50, 60, 70, 79]:
            p1 = calculate_package_price(package_id="1", quantity=q)
            self.assertEqual(p1["upfront_unit_price"], 70.0)
            self.assertEqual(p1["surcharge_per_unit"], 0.0)
            self.assertEqual(p1["max_allowed_discount"], 0.0)
            self.assertFalse(p1["is_discount_allowed"])
            self.assertFalse(p1["special_offer_voice_eligible"])

            p7 = calculate_package_price(package_id="7", quantity=q)
            self.assertEqual(p7["upfront_unit_price"], 91.0)
            self.assertEqual(p7["surcharge_per_unit"], 0.0)
            self.assertEqual(p7["max_allowed_discount"], 0.0)
            self.assertFalse(p7["is_discount_allowed"])

        # Negotiation on 79 pcs must be refused
        neg = negotiate_step(package_id="7", quantity=79)
        self.assertEqual(neg["status"], "discount_refused_tier_limit")
        self.assertEqual(neg["offered_discount"], 0.0)

        print("[PASSED] Test 04: Regular Tier 50-79 fixed price and 0 discount verified.")

    def test_05_bulk_tier_80_plus_upfront_quote_is_regular_price(self):
        """Test Bulk Tier (80, 81, 90, 99, 100+) upfront quote is ALWAYS regular price first."""
        for q in [80, 81, 90, 99, 100, 200]:
            p7 = calculate_package_price(package_id="7", quantity=q, applied_discount=0.0)
            self.assertEqual(p7["upfront_unit_price"], 91.0)
            self.assertEqual(p7["effective_unit_price"], 91.0)
            self.assertEqual(p7["max_allowed_discount"], 9.0)
            self.assertEqual(p7["min_allowed_unit_price"], 82.0)
            self.assertTrue(p7["is_discount_allowed"])
            self.assertTrue(p7["special_offer_voice_eligible"])

            p1 = calculate_package_price(package_id="1", quantity=q, applied_discount=0.0)
            self.assertEqual(p1["upfront_unit_price"], 70.0)
            self.assertEqual(p1["max_allowed_discount"], 5.0)
            self.assertEqual(p1["min_allowed_unit_price"], 65.0)
            self.assertTrue(p1["is_discount_allowed"])

        print("[PASSED] Test 05: Bulk Tier upfront regular rate quote verified.")

    def test_06_package_7_step_by_step_negotiation_and_floor_limit(self):
        """Test Package 7 negotiation: 91 -> 88 -> 85 -> 82 (Max 9 Tk discount). Below 82 requires owner approval."""
        qty = 80 # Bulk Tier

        # Step 1: First negotiation attempt (current_discount = 0)
        s1 = negotiate_step(package_id="7", quantity=qty, current_discount=0.0)
        self.assertEqual(s1["status"], "discount_offered")
        self.assertEqual(s1["offered_unit_price"], 88.0) # 91 - 3
        self.assertEqual(s1["offered_discount"], 3.0)
        self.assertFalse(s1["requires_owner_approval"])

        # Step 2: Second negotiation attempt (current_discount = 3)
        s2 = negotiate_step(package_id="7", quantity=qty, current_discount=3.0)
        self.assertEqual(s2["status"], "discount_offered")
        self.assertEqual(s2["offered_unit_price"], 85.0) # 91 - 6
        self.assertEqual(s2["offered_discount"], 6.0)
        self.assertFalse(s2["requires_owner_approval"])

        # Step 3: Third negotiation attempt (current_discount = 6)
        s3 = negotiate_step(package_id="7", quantity=qty, current_discount=6.0)
        self.assertEqual(s3["status"], "discount_offered")
        self.assertEqual(s3["offered_unit_price"], 82.0) # 91 - 9 (Floor)
        self.assertEqual(s3["offered_discount"], 9.0)
        self.assertFalse(s3["requires_owner_approval"])

        # Step 4: Customer demands 80 Tk (or 75 Tk) - below minimum allowed floor 82 Tk
        s4 = negotiate_step(package_id="7", quantity=qty, current_discount=9.0, customer_demanded_price=80.0)
        self.assertEqual(s4["status"], "exceeds_max_discount_owner_required")
        self.assertEqual(s4["offered_unit_price"], 82.0)
        self.assertEqual(s4["offered_discount"], 9.0)
        self.assertTrue(s4["requires_owner_approval"])
        self.assertIn("Owner স্যারের অনুমতি প্রয়োজন", s4["reply_text"])

        print("[PASSED] Test 06: Package 7 step-by-step negotiation & floor limit 82 Tk verified.")

    def test_07_package_1_to_6_discount_cap_at_5_taka(self):
        """Test Packages 1 to 6 max discount is capped at 5 Taka."""
        for pkg_id, base_p, min_p in [
            ("1", 70.0, 65.0),
            ("2", 70.0, 65.0),
            ("3", 73.0, 68.0),
            ("4", 73.0, 68.0),
            ("5", 83.0, 78.0),
            ("6", 83.0, 78.0),
        ]:
            # Step 1 negotiation
            neg1 = negotiate_step(package_id=pkg_id, quantity=100, current_discount=0.0)
            self.assertEqual(neg1["offered_discount"], 2.0)
            self.assertEqual(neg1["offered_unit_price"], base_p - 2.0)

            # Max discount attempt
            neg_max = negotiate_step(package_id=pkg_id, quantity=100, current_discount=4.0)
            self.assertEqual(neg_max["offered_discount"], 5.0)
            self.assertEqual(neg_max["offered_unit_price"], min_p)

            # Demanding below min_p (e.g. base_p - 10)
            neg_excess = negotiate_step(package_id=pkg_id, quantity=100, current_discount=5.0, customer_demanded_price=base_p - 10.0)
            self.assertEqual(neg_excess["status"], "exceeds_max_discount_owner_required")
            self.assertEqual(neg_excess["offered_unit_price"], min_p)
            self.assertTrue(neg_excess["requires_owner_approval"])

        print("[PASSED] Test 07: Packages 1-6 max discount 5 Tk cap verified.")

    def test_08_delivery_and_cod_calculation(self):
        """Test Delivery and COD calculation rules."""
        # 1. Inside Dhaka, 1kg, 5,000 Tk subtotal
        # Delivery = 80 Tk, COD = (5000 // 1000) * 10 = 50 Tk -> Grand Total = 5,130 Tk
        d1 = calculate_delivery_and_cod(subtotal=5000.0, is_inside_dhaka=True, weight_kg=1.0)
        self.assertEqual(d1["base_delivery"], 80.0)
        self.assertEqual(d1["total_delivery"], 80.0)
        self.assertEqual(d1["cod_charge"], 50.0)
        self.assertEqual(d1["grand_total"], 5130.0)
        self.assertTrue(d1["advance_required"])

        # 2. Outside Dhaka, 3kg, 8,200 Tk subtotal
        # Delivery = 130 + (2 * 20) = 170 Tk, COD = 8 * 10 = 80 Tk -> Grand Total = 8,450 Tk
        d2 = calculate_delivery_and_cod(subtotal=8200.0, is_inside_dhaka=False, weight_kg=3.0)
        self.assertEqual(d2["base_delivery"], 130.0)
        self.assertEqual(d2["extra_weight_charge"], 40.0)
        self.assertEqual(d2["total_delivery"], 170.0)
        self.assertEqual(d2["cod_charge"], 80.0)
        self.assertEqual(d2["grand_total"], 8450.0)

        print("[PASSED] Test 08: Delivery & COD fee math verified.")

    def test_09_package_id_normalization(self):
        """Test normalization of various Bengali and English package labels."""
        self.assertEqual(normalize_package_id("1"), "1")
        self.assertEqual(normalize_package_id("১"), "1")
        self.assertEqual(normalize_package_id("প্যাকেজ ১"), "1")
        self.assertEqual(normalize_package_id("package 7"), "7")
        self.assertEqual(normalize_package_id("প্যাকেজ ৭"), "7")
        self.assertEqual(normalize_package_id("৭"), "7")
        print("[PASSED] Test 09: Package ID normalization verified.")


if __name__ == "__main__":
    unittest.main()
