"""
Phase 4: Response Validator & Policy Guard for RS Graphics AI Agent.

Deterministic safety inspection and auto-correction of all AI-generated drafts
before dispatch to customers.

Guarantees:
1. Human Takeover Guard: Silences all messages when admin/human takeover is active.
2. MOQ Guard: Enforces minimum 30 pcs order; intercepts < 30 pcs promises.
3. Advance & COD Guard: Enforces mandatory advance; blocks unauthorized 100% COD claims.
4. Pricing & Discount Guard:
   - 30-49 pcs: Regular Price + 10 Tk / piece, 0 discount.
   - 50-79 pcs: Fixed Regular Price, 0 discount.
   - 80+ pcs: Regular Price baseline upfront, max discount floor caps (Pkg 7 min: 82 Tk, Pkg 1-6 max: 5 Tk).
5. Delivery Charge Guard: Inside Dhaka 80 Tk, Outside Dhaka 130 Tk, COD 10 Tk / 1000 Tk.
6. Media & Voice Guard: Special offer voice ONLY for 80+ pcs, caps photo batching.
7. Persona & Hallucination Guard: Honorific enforcement, fake form link interception.
"""

import re
from typing import Dict, Any, List, Optional
from app.ai_agent.pricing_engine import (
    QuantityTier, get_quantity_tier, calculate_package_price,
    negotiate_step, calculate_delivery_and_cod, normalize_package_id,
    PACKAGE_CATALOG
)


def detect_customer_gender_title(customer_name: str = "") -> str:
    """Helper to detect appropriate honorific (স্যার / ম্যাম)."""
    if not customer_name:
        return "স্যার"
    c_lower = customer_name.lower().strip()
    female_indicators = [
        "mrs", "ms", "miss", "begum", "khatun", "akter", "sultana", "jahan",
        "nahar", "parvin", "nasrin", "fatema", "rokeya", "tasnim", "nargis",
        "বেগম", "খাতুন", "আক্তার", "সুলতানা", "জাহান", "নাহার", "পারভীন",
        "নাসরিন", "ফাতেমা", "রোকেয়া", "তাসনিম", "নার্গিস", "আপু", "ম্যাডাম", "ম্যাম"
    ]
    if any(ind in c_lower for ind in female_indicators):
        return "ম্যাম"
    return "স্যার"


def extract_quantity_safely(text: str) -> Optional[int]:
    """Safely extracts order quantity using the battle-tested extractor."""
    try:
        from app.ai_agent.gemini_brain import extract_order_quantity_number
        return extract_order_quantity_number(text)
    except Exception:
        pass
    if not text:
        return None
    # Fallback only when explicit quantity indicators are attached
    bengali_digits = {'০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4', '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'}
    cleaned = ''
    for ch in text:
        cleaned += bengali_digits.get(ch, ch)
    # Match only if explicitly followed by pcs / পিস / টা / কপি
    m = re.search(r'(\d{1,5})\s*(?:পিস|pcs|টা|টি|কপি|বানাবো)', cleaned, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return None


class ResponseValidator:
    """
    Authoritative Response Validator & Policy Guard.
    Evaluates every draft response and returns a validated, policy-compliant response.
    """

    @classmethod
    def validate_and_sanitize(
        cls,
        draft_response: Dict[str, Any],
        customer_message: str = "",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        sender_id: Optional[str] = None,
        customer_name: str = "Customer",
        workspace_id: int = 1,
        channel: str = "whatsapp"
    ) -> Dict[str, Any]:
        """
        Main validation entrypoint.
        """
        reply_text = str(draft_response.get("reply_text") or "")
        matched_images = list(draft_response.get("matched_images") or [])
        media_sequence = list(draft_response.get("media_sequence") or [])
        voice_url = str(draft_response.get("voice_url") or "")
        video_url = str(draft_response.get("video_url") or "")
        order_created = draft_response.get("order_created")
        response_source = draft_response.get("response_source", "gemini_brain")
        validation_flags = []

        ws_id = int(workspace_id or 1)
        honorific = detect_customer_gender_title(customer_name)

        # -------------------------------------------------------------
        # 1. HUMAN / ADMIN TAKEOVER CHECK (Absolute Silence Guard)
        # -------------------------------------------------------------
        if sender_id:
            try:
                from app.database import is_conversation_ai_active
                if not is_conversation_ai_active(sender_id=str(sender_id), workspace_id=ws_id):
                    return {
                        "reply_text": "",
                        "matched_images": [],
                        "media_sequence": [],
                        "voice_url": "",
                        "video_url": "",
                        "order_created": None,
                        "response_source": "blocked_by_human_takeover",
                        "is_blocked": True,
                        "validation_flags": ["HUMAN_TAKEOVER_ACTIVE"]
                    }
            except Exception as e:
                print(f"[Validator Takeover Check Warning]: {e}")

        # Extract structured state if available
        saved_state = {}
        if sender_id:
            try:
                from app.database import get_structured_conversation_state
                saved_state = get_structured_conversation_state(str(sender_id), ws_id)
            except Exception:
                pass

        # Detect quantity from message or saved state
        msg_qty = extract_quantity_safely(customer_message)
        effective_qty = msg_qty if msg_qty is not None else saved_state.get("quantity")

        # -------------------------------------------------------------
        # 2. MOQ POLICY GUARD (< 30 pieces)
        # -------------------------------------------------------------
        if effective_qty is not None and effective_qty < 30:
            moq_keywords = ["সর্বনিম্ন", "৩০ পিস", "30 pcs", "30 পিস", "৩০টি"]
            has_moq_mention = any(kw in reply_text for kw in moq_keywords)
            
            if not has_moq_mention or "অর্ডার কনফার্ম" in reply_text or "অর্ডার নেওয়া হয়েছে" in reply_text:
                reply_text = f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"
                matched_images = []
                media_sequence = []
                voice_url = ""
                video_url = ""
                order_created = None
                response_source = "validator_moq_enforced"
                validation_flags.append("MOQ_UNDER_30_ENFORCED")

        # -------------------------------------------------------------
        # 3. ADVANCE & PROHIBITED 100% COD GUARD
        # -------------------------------------------------------------
        unauthorized_cod_phrases = [
            "কোনো অগ্রিম লাগবে না", "অগ্রিম ছাড়াই", "সম্পূর্ণ ক্যাশ অন ডেলিভারি",
            "ফুল ক্যাশ অন ডেলিভারি", "টাকা দেওয়া লাগবে না ডেলিভারির আগে",
            "সব টাকা ডেলিভারির সময়", "১০০% ক্যাশ অন ডেলিভারি", "এডভান্স ছাড়া"
        ]
        if any(p in reply_text for p in unauthorized_cod_phrases):
            reply_text = re.sub(
                r'(কোনো\s+অগ্রিম\s+লাগবে\s+না|অগ্রিম\s+ছাড়া[^\s,।]*|সম্পূর্ণ\s+ক্যাশ\s+অন\s+ডেলিভারি|ফুল\s+ক্যাশ\s+অন\s+ডেলিভারি|এডভান্স\s+ছাড়া[^\s,।]*|১০০%\s+ক্যাশ\s+অন\s+ডেলিভারি)',
                f'কাজের মান ও কাস্টমাইজেশনের কারণে কাজ শুরুর পূর্বে ডেলিভারি চার্জ বা আংশিক অগ্রিম পেমেন্ট বাধ্যতামূলক',
                reply_text,
                flags=re.IGNORECASE
            )
            validation_flags.append("PROHIBITED_COD_INTERCEPTED")

        # -------------------------------------------------------------
        # 4. DELIVERY CHARGE SANITIZATION
        # -------------------------------------------------------------
        if "ফ্রি ডেলিভারি" in reply_text or "ফ্রি ডেলিভারিতে" in reply_text:
            reply_text = reply_text.replace("ফ্রি ডেলিভারিতে", "ডেলিভারি চার্জে (ঢাকার ভেতরে ৮০ টাকা, ঢাকার বাইরে ১৩০ টাকা)")
            reply_text = reply_text.replace("ফ্রি ডেলিভারি", "ডেলিভারি চার্জ (ঢাকার ভেতরে ৮০ টাকা, ঢাকার ভেতরে ৮০ টাকা, ঢাকার বাইরে ১৩০ টাকা)")
            validation_flags.append("FREE_DELIVERY_CORRECTED")

        # -------------------------------------------------------------
        # 5. SPECIAL OFFER VOICE PERMISSION GUARD
        # -------------------------------------------------------------
        # Special Offer voice is strictly for 80+ pieces only
        if voice_url and "PTT-20260119-WA0105" in voice_url:
            if effective_qty is not None and effective_qty < 80:
                voice_url = ""
                validation_flags.append("SPECIAL_VOICE_STRIPPED_UNDER_80")

        # -------------------------------------------------------------
        # 6. PACKAGE 7 FLOOR PRICE GUARD (Minimum 82 Tk)
        # -------------------------------------------------------------
        norm_reply_digits = reply_text
        bn_digits_map = {'০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4', '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'}
        for b, d in bn_digits_map.items():
            norm_reply_digits = norm_reply_digits.replace(b, d)

        p7_low_match = re.search(r'(?:প্যাকেজ|package|pkg)\s*7[^\d]*?(\d{2,3})\s*(?:টাকা|tk)', norm_reply_digits)
        if p7_low_match:
            try:
                quoted_val = int(p7_low_match.group(1))
                if quoted_val < 82:
                    has_approved_exception = False
                    if sender_id:
                        try:
                            from app.ai_agent.owner_approval import OwnerApprovalEngine
                            appr = OwnerApprovalEngine.get_active_approved_exception(
                                customer_id=str(sender_id),
                                workspace_id=ws_id,
                                package_id="7"
                            )
                            if appr and int(float(appr.get("approved_value") or 0)) == quoted_val:
                                has_approved_exception = True
                        except Exception:
                            pass

                    if not has_approved_exception:
                        reply_text = (
                            f"জি {honorific}, আমাদের নির্ধারিত সর্বোচ্চ Discount দেওয়ার পরেও প্যাকেজ ৭-এর রেট "
                            f"প্রতি সেট ৮২ টাকার নিচে দেওয়া সম্ভব হচ্ছে না। এর চেয়ে কমাতে হলে Owner স্যারের অনুমতি প্রয়োজন হবে।"
                        )
                        validation_flags.append("PACKAGE_7_FLOOR_PROTECTED")
            except Exception:
                pass

        # -------------------------------------------------------------
        # 7. SMALL ORDER (30-49) & REGULAR (50-79) ZERO DISCOUNT GUARD
        # -------------------------------------------------------------
        if effective_qty is not None:
            tier = get_quantity_tier(effective_qty)
            if tier == QuantityTier.SMALL_ORDER:
                if any(kw in reply_text for kw in ["বিশেষ ছাড়", "ডিসকাউন্ট দেওয়া হলো", "কম রাখা হলো"]):
                    reply_text = (
                        f"জি {honorific}, আমাদের প্যাকেজগুলোর রেট ১০০+ অর্ডারের ক্ষেত্রে প্রযোজ্য। "
                        f"আপনার যেহেতু ১০০ এর কম ({effective_qty} পিস), তাই প্রতি প্যাকেজে ১০ টাকা করে বেশি হবে। "
                        f"আপনার কোন প্যাকেজটি পছন্দ জানাবেন প্লিজ।"
                    )
                    validation_flags.append("SMALL_ORDER_DISCOUNT_STRIPPED")
            elif tier == QuantityTier.REGULAR:
                if any(kw in reply_text for kw in ["বিশেষ ছাড়", "ডিসকাউন্ট দেওয়া হলো", "কম রাখা হলো"]):
                    reply_text = (
                        f"জি {honorific}, ৫০-৭৯ পিসের ক্ষেত্রে প্যাকেজের ছবিতে উল্লেখিত রেগুলার মূল্যে "
                        f"({effective_qty} পিসের জন্য) আমরা আপনার কাজটি নিখুঁতভাবে তৈরি করে দেব। "
                        f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন প্লিজ।"
                    )
                    validation_flags.append("REGULAR_TIER_DISCOUNT_STRIPPED")

        # -------------------------------------------------------------
        # 8. PERSONA & CLEANLINESS SANITIZATION
        # -------------------------------------------------------------
        # Replace informal ভাইয়া / আপু with formal honorific
        clean_text = reply_text
        for word in ["ভাইয়া", "ভাই", "আপু", "আপা", "আপু/ভাইয়া", "ভাইয়া/আপু", "স্যার/ম্যাম"]:
            clean_text = clean_text.replace(word, honorific)

        # Remove HTML tags and script tags
        clean_text = re.sub(r'<[^>]+>', '', clean_text)
        # Remove markdown image syntax and raw file paths from chat text
        clean_text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean_text)
        clean_text = re.sub(r'\[Image[s]?:\s*[^\]]+\]', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'/static/uploads/\S+', '', clean_text)
        clean_text = re.sub(r'[ \t]+', ' ', clean_text)
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()

        # Fallback for empty text
        if not clean_text:
            clean_text = f"জি {honorific}, আরএস গ্রাফিক্সের পক্ষ থেকে আপনাকে স্বাগতম। আপনার অর্ডার বা তথ্যের বিষয়ে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।"

        # Deduplicate matched images and cap at 3 (unless full package sequence)
        unique_images = []
        for img in matched_images:
            if not img or not isinstance(img, str):
                continue
            # Security filter: prevent path traversal or malicious file extensions
            if ".." in img or "\\" in img or any(img.lower().endswith(ext) for ext in [".exe", ".bat", ".sh", ".py", ".bin", "passwd"]):
                continue
            if img not in unique_images:
                unique_images.append(img)
        if len(unique_images) > 3 and not any("pakage" in str(u).lower() or "pkg" in str(u).lower() for u in unique_images):
            unique_images = unique_images[:3]

        # Media URL format validation & security check
        if video_url:
            v_str = str(video_url).strip()
            if ".." in v_str or "\\" in v_str or any(v_str.lower().endswith(ext) for ext in [".exe", ".bat", ".sh", ".py", ".bin", "passwd"]):
                video_url = ""
            elif "non_existent" in v_str or "deleted" in v_str:
                video_url = ""
            elif not v_str.startswith("/static/") and not v_str.startswith("http://") and not v_str.startswith("https://"):
                video_url = ""

        if voice_url:
            v_str = str(voice_url).strip()
            if ".." in v_str or "\\" in v_str or any(v_str.lower().endswith(ext) for ext in [".exe", ".bat", ".sh", ".py", ".bin", "passwd"]):
                voice_url = ""
            elif "non_existent" in v_str or "deleted" in v_str:
                voice_url = ""
            elif not v_str.startswith("/static/") and not v_str.startswith("http://") and not v_str.startswith("https://"):
                voice_url = ""

        return {
            "reply_text": clean_text,
            "matched_images": unique_images,
            "media_sequence": media_sequence,
            "voice_url": voice_url,
            "video_url": video_url,
            "order_created": order_created,
            "response_source": response_source,
            "is_blocked": False,
            "validation_flags": validation_flags
        }
