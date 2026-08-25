"""
Phase 3 Authoritative Pricing & Discount Engine for RS Graphics AI Agent.

Single authoritative business rules for:
1. Final Quantity Tiers:
   - 30-49 pcs: Small Order Tier (Regular Price + 10 Tk / piece, No Discount)
   - 50-79 pcs: Regular Tier (Fixed Regular Price, No Discount)
   - 80+ pcs (80, 81, 90, 99, 100, 200, 300+): Bulk Tier (Regular Price initially, Special Offer Voice, Step-by-step negotiation)
   * Note: 80-99 is NOT a separate tier. 80+ starts the Bulk Tier.
   - < 30 pcs: MOQ Rejected (< 30 pcs)

2. Package Regular Prices & Allowed Maximum Discounts:
   - Package 1 (Card + 1.5cm Ribbon + Soft Cover): 70 Tk (Max Discount: 5 Tk -> Min: 65 Tk)
   - Package 2 (Card + Ribbon + DX Cover Combo): 70 Tk (Max Discount: 5 Tk -> Min: 65 Tk)
   - Package 3 (Card + Ribbon + Soft Cover Combo): 73 Tk (Max Discount: 5 Tk -> Min: 68 Tk)
   - Package 4 (Card + 2cm Ribbon + DX Cover Combo): 73 Tk (Max Discount: 5 Tk -> Min: 68 Tk)
   - Package 5 (Card + 2cm Ribbon + T-994V Cover Combo): 83 Tk (Max Discount: 5 Tk -> Min: 78 Tk)
   - Package 6 (Card + 2cm Ribbon + REAP Cover Combo): 83 Tk (Max Discount: 5 Tk -> Min: 78 Tk)
   - Package 7 (Metal Frame / Luxury Full Combo): 91 Tk (Max Discount: 9 Tk -> Min: 82 Tk)

3. Discount Rules:
   - Never give discount upfront.
   - No discount on 30-49 and 50-79 tiers.
   - Step-by-step negotiation on 80+ tier within max allowed limits.
   - Below minimum allowed price requires owner approval.

4. Delivery & COD Charges:
   - Inside Dhaka: 80 Tk base (+20 Tk/kg over 1kg)
   - Outside Dhaka: 130 Tk base (+20 Tk/kg over 1kg)
   - COD Charge: 10 Tk per 1,000 Tk invoice value
   - Advance: Mandatory
"""

from enum import Enum
from typing import Dict, Any, Optional, Tuple


class QuantityTier(str, Enum):
    UNDER_MOQ = "UNDER_MOQ"      # < 30 pcs
    SMALL_ORDER = "SMALL_ORDER"  # 30 - 49 pcs (+10 Tk/piece, No discount)
    REGULAR = "REGULAR"          # 50 - 79 pcs (Regular Price, No discount)
    BULK = "BULK"                # 80+ pcs (100+ / Bulk Tier: 80, 81, 90, 99, 100, 200, 300+ pcs)


# -------------------------------------------------------------
# Canonical Package Catalog (Baseline 100+ / Bulk Regular Rates)
# -------------------------------------------------------------
PACKAGE_CATALOG: Dict[str, Dict[str, Any]] = {
    "1": {
        "id": "1",
        "name": "Package 1",
        "name_bn": "প্যাকেজ ১",
        "details_bn": "আইডি কার্ড + ১.৫ সেমি ফিতা + সফট কভার",
        "regular_price": 70.0,
        "max_discount": 5.0,
        "min_price": 65.0,
    },
    "2": {
        "id": "2",
        "name": "Package 2",
        "name_bn": "প্যাকেজ ২",
        "details_bn": "আইডি কার্ড + ফিতা + ডিএক্স কভার কম্বো",
        "regular_price": 70.0,
        "max_discount": 5.0,
        "min_price": 65.0,
    },
    "3": {
        "id": "3",
        "name": "Package 3",
        "name_bn": "প্যাকেজ ৩",
        "details_bn": "আইডি কার্ড + ফিতা + সফট কভার কম্বো",
        "regular_price": 73.0,
        "max_discount": 5.0,
        "min_price": 68.0,
    },
    "4": {
        "id": "4",
        "name": "Package 4",
        "name_bn": "প্যাকেজ ৪",
        "details_bn": "আইডি কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো",
        "regular_price": 73.0,
        "max_discount": 5.0,
        "min_price": 68.0,
    },
    "5": {
        "id": "5",
        "name": "Package 5",
        "name_bn": "প্যাকেজ ৫",
        "details_bn": "আইডি কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো",
        "regular_price": 83.0,
        "max_discount": 5.0,
        "min_price": 78.0,
    },
    "6": {
        "id": "6",
        "name": "Package 6",
        "name_bn": "প্যাকেজ ৬",
        "details_bn": "আইডি কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো",
        "regular_price": 83.0,
        "max_discount": 5.0,
        "min_price": 78.0,
    },
    "7": {
        "id": "7",
        "name": "Package 7",
        "name_bn": "প্যাকেজ ৭",
        "details_bn": "মেটাল ফ্রেম / লাক্সারি ফুল কম্বো",
        "regular_price": 91.0,
        "max_discount": 9.0,
        "min_price": 82.0,
    },
}

# Single item rates (100+ pcs)
SINGLE_ITEM_CATALOG: Dict[str, float] = {
    "id_card": 35.0,
    "ribbon_1_5cm": 25.0,
    "ribbon_2cm": 28.0,
    "soft_cover_t014v": 10.0,
    "dx_cover": 12.0,
    "soft_cover_t065v": 14.0,
    "cover_q993": 16.0,
    "hard_cover_t738v": 20.0,
    "hard_cover_t994v": 20.0,
    "hard_cover_reap": 20.0,
    "metal_cover": 30.0,
}


def normalize_package_id(raw_id: Any) -> Optional[str]:
    """Normalizes Bengali and English package identifiers to canonical string '1'..'7'."""
    if raw_id is None:
        return None
    s = str(raw_id).strip()
    mapping = {
        "১": "1", "1": "1", "package 1": "1", "প্যাকেজ ১": "1", "প্যাকেজ 1": "1",
        "২": "2", "2": "2", "package 2": "2", "প্যাকেজ ২": "2", "প্যাকেজ 2": "2",
        "৩": "3", "3": "3", "package 3": "3", "প্যাকেজ ৩": "3", "প্যাকেজ 3": "3",
        "৪": "4", "4": "4", "package 4": "4", "প্যাকেজ ৪": "4", "প্যাকেজ 4": "4",
        "৫": "5", "5": "5", "package 5": "5", "প্যাকেজ ৫": "5", "প্যাকেজ 5": "5",
        "৬": "6", "6": "6", "package 6": "6", "প্যাকেজ ৬": "6", "প্যাকেজ 6": "6",
        "৭": "7", "7": "7", "package 7": "7", "প্যাকেজ ৭": "7", "প্যাকেজ 7": "7",
    }
    return mapping.get(s.lower(), s if s in PACKAGE_CATALOG else None)


def get_quantity_tier(quantity: int) -> QuantityTier:
    """
    Authoritative Quantity Tier Classifier:
    - < 30 pcs: UNDER_MOQ
    - 30 to 49 pcs: SMALL_ORDER (+10 Tk / piece)
    - 50 to 79 pcs: REGULAR (Fixed Regular Price)
    - 80+ pcs: BULK (100+ / Bulk Tier: 80, 81, 90, 99, 100, 200, 300+ pcs)

    IMPORTANT: 80-99 is NOT a separate tier. 80+ is strictly in the BULK tier.
    """
    if quantity < 30:
        return QuantityTier.UNDER_MOQ
    elif 30 <= quantity <= 49:
        return QuantityTier.SMALL_ORDER
    elif 50 <= quantity <= 79:
        return QuantityTier.REGULAR
    else:
        # quantity >= 80 (80, 81, 90, 99, 100, 200, 300+)
        return QuantityTier.BULK


def calculate_package_price(
    package_id: Any,
    quantity: int,
    applied_discount: float = 0.0
) -> Dict[str, Any]:
    """
    Calculates precise unit price, discount limits, and subtotal for a package order.
    """
    norm_id = normalize_package_id(package_id) or "7"
    pkg = PACKAGE_CATALOG.get(norm_id, PACKAGE_CATALOG["7"])
    tier = get_quantity_tier(quantity)

    regular_price = pkg["regular_price"]
    surcharge = 10.0 if tier == QuantityTier.SMALL_ORDER else 0.0
    upfront_unit_price = regular_price + surcharge

    if tier in (QuantityTier.UNDER_MOQ, QuantityTier.SMALL_ORDER, QuantityTier.REGULAR):
        max_allowed_discount = 0.0
        min_unit_price = upfront_unit_price
        is_discount_allowed = False
        special_offer_voice_eligible = False
    else:
        # BULK Tier (80+ pieces)
        max_allowed_discount = pkg["max_discount"]
        min_unit_price = pkg["min_price"]
        is_discount_allowed = True
        special_offer_voice_eligible = True

    # Clamp discount to strictly allowed bounds
    effective_discount = min(max(0.0, float(applied_discount)), max_allowed_discount)
    effective_unit_price = upfront_unit_price - effective_discount
    total_price = effective_unit_price * quantity

    return {
        "package_id": norm_id,
        "package_name": pkg["name_bn"],
        "quantity": quantity,
        "tier": tier,
        "regular_price": regular_price,
        "surcharge_per_unit": surcharge,
        "upfront_unit_price": upfront_unit_price,
        "max_allowed_discount": max_allowed_discount,
        "min_allowed_unit_price": min_unit_price,
        "applied_discount": effective_discount,
        "effective_unit_price": effective_unit_price,
        "total_amount": total_price,
        "is_discount_allowed": is_discount_allowed,
        "special_offer_voice_eligible": special_offer_voice_eligible,
        "moq_passed": tier != QuantityTier.UNDER_MOQ,
    }


def negotiate_step(
    package_id: Any,
    quantity: int,
    current_discount: float = 0.0,
    customer_demanded_price: Optional[float] = None
) -> Dict[str, Any]:
    """
    Authoritative step-by-step negotiation calculator.
    Enforces that discounts are ONLY given on 80+ pcs and never exceed maximum allowed caps.
    """
    tier = get_quantity_tier(quantity)
    norm_id = normalize_package_id(package_id) or "7"
    pkg = PACKAGE_CATALOG.get(norm_id, PACKAGE_CATALOG["7"])

    if tier == QuantityTier.UNDER_MOQ:
        return {
            "status": "moq_rejected",
            "reply_text": "দুঃখিত স্যার, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।",
            "offered_unit_price": None,
            "offered_discount": 0.0,
            "requires_owner_approval": False,
        }

    if tier in (QuantityTier.SMALL_ORDER, QuantityTier.REGULAR):
        surcharge_text = " (যেহেতু ১০০ এর কম, তাই প্রতি সেটে ১০ টাকা অতিরিক্ত)" if tier == QuantityTier.SMALL_ORDER else ""
        return {
            "status": "discount_refused_tier_limit",
            "reply_text": f"দুঃখিত স্যার, {quantity} পিস অর্ডারের ক্ষেত্রে আমাদের এই রেটটি ফিক্সড রেগুলার রেট{surcharge_text}। ১০০+ বাল্ক অর্ডারের ক্ষেত্রে স্পেশাল ডিসকাউন্ট পলিসি প্রযোজ্য হয়।",
            "offered_unit_price": pkg["regular_price"] + (10.0 if tier == QuantityTier.SMALL_ORDER else 0.0),
            "offered_discount": 0.0,
            "requires_owner_approval": False,
        }

    # BULK Tier (80+ pieces)
    max_disc = pkg["max_discount"]
    min_allowed_price = pkg["min_price"]
    base_price = pkg["regular_price"]

    # If customer explicitly demands an impossibly low price (e.g. demanding 75 Tk on Package 7)
    if customer_demanded_price is not None and customer_demanded_price < min_allowed_price:
        return {
            "status": "exceeds_max_discount_owner_required",
            "reply_text": f"স্যার, আমাদের নির্ধারিত সর্বোচ্চ Discount দেওয়ার পরেও {pkg['name_bn']}-এর মূল্য প্রতি সেট {int(min_allowed_price)} টাকার নিচে দেওয়া সম্ভব হচ্ছে না। এর চেয়ে কমাতে হলে Owner স্যারের অনুমতি প্রয়োজন হবে।",
            "offered_unit_price": min_allowed_price,
            "offered_discount": max_disc,
            "requires_owner_approval": True,
        }

    # Step-by-step negotiation progression
    # Step 1: ~1/3 of max discount
    # Step 2: ~2/3 of max discount
    # Step 3: Full max discount
    if norm_id == "7":  # Max 9 Tk discount (91 -> 88 -> 85 -> 82)
        steps = [3.0, 6.0, 9.0]
    else:  # Max 5 Tk discount (e.g. 70 -> 68 -> 66 -> 65)
        steps = [2.0, 4.0, 5.0]

    next_discount = max_disc
    for s in steps:
        if s > current_discount:
            next_discount = s
            break

    # If customer requested a specific acceptable price within bounds
    if customer_demanded_price is not None and customer_demanded_price >= min_allowed_price:
        needed_disc = base_price - customer_demanded_price
        if needed_disc <= next_discount:
            next_discount = needed_disc
        else:
            # Grant next progressive step
            pass

    offered_price = base_price - next_discount
    if next_discount >= max_disc:
        reply = f"জি স্যার, আপনার {quantity} পিস অর্ডারের জন্য আমরা সর্বোচ্চ সম্মান দেখিয়ে প্রতি সেট {int(offered_price)} টাকা রেটে করে দিতে পারব।"
    else:
        reply = f"জি স্যার, আপনার {quantity} পিস অর্ডারের জন্য আমরা বিশেষ বিবেচনায় প্রতি সেট {int(offered_price)} টাকা করে রাখতে পারব।"

    return {
        "status": "discount_offered",
        "reply_text": reply,
        "offered_unit_price": offered_price,
        "offered_discount": next_discount,
        "requires_owner_approval": False,
    }


def calculate_delivery_and_cod(
    subtotal: float,
    is_inside_dhaka: bool = True,
    weight_kg: float = 1.0
) -> Dict[str, Any]:
    """
    Calculates delivery fee and COD charges:
    - Inside Dhaka: 80 Tk base (first 1kg) + 20 Tk/kg extra
    - Outside Dhaka: 130 Tk base (first 1kg) + 20 Tk/kg extra
    - COD Charge: 10 Tk per 1,000 Tk invoice value
    - Advance: Mandatory
    """
    extra_kg = max(0.0, weight_kg - 1.0)
    extra_weight_charge = int(extra_kg) * 20.0

    if is_inside_dhaka:
        base_delivery = 80.0
    else:
        base_delivery = 130.0

    total_delivery = base_delivery + extra_weight_charge
    cod_charge = (int(subtotal) // 1000) * 10.0
    grand_total = subtotal + total_delivery + cod_charge

    return {
        "subtotal": subtotal,
        "is_inside_dhaka": is_inside_dhaka,
        "base_delivery": base_delivery,
        "extra_weight_charge": extra_weight_charge,
        "total_delivery": total_delivery,
        "cod_charge": cod_charge,
        "grand_total": grand_total,
        "advance_required": True,
    }
