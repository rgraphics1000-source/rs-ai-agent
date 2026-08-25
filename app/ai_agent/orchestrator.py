"""
Phase 9 & 9.3: Central Intelligent Conversation Engine & Master Orchestrator for RS Graphics AI Agent.

Architecture & Invariants:
1. STRICT SINGLE RESPONSE OWNER: Exactly 1 response decision & 1 outbound payload per inbound customer batch.
2. CURRENT INTENT > STALE PENDING STATE: A customer saying 'ভালো আছেন?' or 'আপনি কে?' is never hijacked by a previous quantity prompt.
3. STRUCTURED INTENT HIERARCHY: Prioritized semantic classification with explicit confidence and tool selection.
4. ZERO-GUESS & OWNER PRIVACY: Unknown queries escalate to human team; Nadim is the only authoritative agent name.
5. PROMPT & INSTRUCTION LEAKAGE IMMUNITY: Developer notes or prompt instructions are strictly barred from customer delivery.
6. DETERMINISTIC BUSINESS ENGINES: Pricing, MOQ, discount caps, delivery fees, and order states are strictly deterministic.
"""

import re
import time
from enum import Enum
from typing import Dict, Any, List, Optional

from app.ai_agent.conversation_state import (
    SalesStage, get_structured_conversation_state, update_conversation_state,
    record_question_asked, record_fact_confirmed, record_media_dispatched,
    is_question_already_answered, is_media_already_sent, get_conversation_memory
)
from app.ai_agent.pricing_engine import (
    QuantityTier, get_quantity_tier, calculate_package_price,
    negotiate_step, calculate_delivery_and_cod, normalize_package_id,
    PACKAGE_CATALOG
)
from app.ai_agent.media_router import (
    MediaRouter, MediaIntent, CANONICAL_MEDIA_KEYS
)
from app.ai_agent.response_validator import (
    ResponseValidator, detect_customer_gender_title
)
from app.ai_agent.knowledge_engine import KnowledgeEngine, AGENT_NAME_BN
from app.database import is_conversation_ai_active, get_db_connection, create_team_escalation


class CustomerIntent(str, Enum):
    GREETING = "GREETING"
    SOCIAL_PLEASANTRY = "SOCIAL_PLEASANTRY"
    QUALITY_INQUIRY = "QUALITY_INQUIRY"
    QUANTITY_INQUIRY = "QUANTITY_INQUIRY"
    QUANTITY_PROVIDED = "QUANTITY_PROVIDED"
    PRODUCT_INQUIRY = "PRODUCT_INQUIRY"
    PACKAGE_INQUIRY = "PACKAGE_INQUIRY"
    PACKAGE_SELECTION = "PACKAGE_SELECTION"
    PRICE_INQUIRY = "PRICE_INQUIRY"
    PER_PIECE_PRICE = "PER_PIECE_PRICE"
    SPECIFIC_ITEM_PRICE = "SPECIFIC_ITEM_PRICE"
    NEGOTIATION = "NEGOTIATION"
    DISCOUNT_REQUEST = "DISCOUNT_REQUEST"
    DELIVERY_INQUIRY = "DELIVERY_INQUIRY"
    DELIVERY_TIME_INQUIRY = "DELIVERY_TIME_INQUIRY"
    PAYMENT_INQUIRY = "PAYMENT_INQUIRY"
    ADVANCE_INQUIRY = "ADVANCE_INQUIRY"
    COD_INQUIRY = "COD_INQUIRY"
    PHOTO_SERVICE = "PHOTO_SERVICE"
    PHOTO_SUBMISSION = "PHOTO_SUBMISSION"
    SAMPLE_REQUEST = "SAMPLE_REQUEST"
    SAMPLE_CONFIRMATION = "SAMPLE_CONFIRMATION"
    RESAMPLE_REQUEST = "RESAMPLE_REQUEST"
    MEDIA_REQUEST = "MEDIA_REQUEST"
    GOOGLE_FORM_HELP = "GOOGLE_FORM_HELP"
    GOOGLE_FORM_CORRECTION_HELP = "GOOGLE_FORM_CORRECTION_HELP"
    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"
    ORDER_MODIFICATION = "ORDER_MODIFICATION"
    ORDER_CANCELLATION = "ORDER_CANCELLATION"
    HUMAN_REQUEST = "HUMAN_REQUEST"
    OWNER_REQUEST = "OWNER_REQUEST"
    AGENT_IDENTITY_INQUIRY = "AGENT_IDENTITY_INQUIRY"
    COMPLAINT = "COMPLAINT"
    TOPIC_CHANGE = "TOPIC_CHANGE"
    MOQ_REJECTED = "MOQ_REJECTED"
    UNKNOWN = "UNKNOWN"


# Priority ranking for authoritative semantic intent resolution
INTENT_PRIORITY_ORDER = [
    CustomerIntent.AGENT_IDENTITY_INQUIRY,
    CustomerIntent.OWNER_REQUEST,
    CustomerIntent.SOCIAL_PLEASANTRY,
    CustomerIntent.GREETING,
    CustomerIntent.GOOGLE_FORM_CORRECTION_HELP,
    CustomerIntent.MEDIA_REQUEST,
    CustomerIntent.PHOTO_SERVICE,
    CustomerIntent.ADVANCE_INQUIRY,
    CustomerIntent.COD_INQUIRY,
    CustomerIntent.DELIVERY_INQUIRY,
    CustomerIntent.DELIVERY_TIME_INQUIRY,
    CustomerIntent.QUALITY_INQUIRY,
    CustomerIntent.NEGOTIATION,
    CustomerIntent.DISCOUNT_REQUEST,
    CustomerIntent.SPECIFIC_ITEM_PRICE,
    CustomerIntent.PER_PIECE_PRICE,
    CustomerIntent.PRICE_INQUIRY,
    CustomerIntent.RESAMPLE_REQUEST,
    CustomerIntent.SAMPLE_REQUEST,
    CustomerIntent.TOPIC_CHANGE,
    CustomerIntent.MOQ_REJECTED,
    CustomerIntent.QUANTITY_PROVIDED,
    CustomerIntent.SAMPLE_CONFIRMATION,
    CustomerIntent.PACKAGE_SELECTION,
    CustomerIntent.PRODUCT_INQUIRY,
    CustomerIntent.UNKNOWN
]


class MasterOrchestrator:
    """
    Central Intelligent Decision Pipeline coordinating all business engines,
    data persistence, and language synthesis pipelines.
    """

    @classmethod
    def detect_intents_and_entities(
        cls,
        message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        conversation_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Extracts structured contextual intent and entities from customer message.
        Follows semantic prioritization: Current Customer Intent > Stale Pending State.
        """
        raw_msg = (message or "").strip()
        norm_msg = raw_msg.lower()

        # Bengali digit normalizer
        bn_digits = {'০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4', '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'}
        digits_norm_msg = norm_msg
        for b, d in bn_digits.items():
            digits_norm_msg = digits_norm_msg.replace(b, d)

        detected_intents: List[CustomerIntent] = []
        entities: Dict[str, Any] = {
            "quantity": None,
            "package_id": None,
            "demanded_price": None,
            "location": None,
            "topic": "id_card",
            "is_negotiating": False,
            "is_affirmative": False,
            "is_resample_request": False,
            "is_specific_item": False,
            "item_name": ""
        }

        # -------------------------------------------------------------
        # 1. ENTITY EXTRACTION
        # -------------------------------------------------------------
        # Specific item pricing (protect item model numbers like T-014 from quantity parsing)
        if any(k in norm_msg for k in ["t-014", "t014", "dx", "t-065", "t065", "t-994", "t994", "reap", "মেটাল কভার", "শুধু কার্ড", "শুধু ফিতা", "শুধু কভার"]):
            entities["is_specific_item"] = True

        if not entities["is_specific_item"]:
            try:
                from app.ai_agent.gemini_brain import extract_order_quantity_number
                extracted_q = extract_order_quantity_number(raw_msg)
                if extracted_q:
                    entities["quantity"] = extracted_q
            except Exception:
                pass

            # Robust local regex fallback for quantity (strictly avoiding prices like '৭৫ টাকা')
            if entities["quantity"] is None:
                clean_for_qty = re.sub(r't-?\d+[a-z]?', '', digits_norm_msg, flags=re.IGNORECASE)
                clean_for_qty = re.sub(r'\b\d+\s*(?:টাকা|টাকায়|টাকাতে|tk|taka|৳)', '', clean_for_qty, flags=re.IGNORECASE)
                m_q = re.search(r'(\d+)\s*(?:টা|টি|পিস|কার্ড|কপি|id\s*cards?|cards?|pieces?|pcs?|items?)', clean_for_qty)
                if not m_q:
                    m_q = re.search(r'(?:প্যাকেজ|package|pkg)\s*[১-৭1-7]\s*(\d+)', clean_for_qty)
                if not m_q and not any(k in norm_msg for k in ["টাকা", "টাকায়", "টাকাতে", "tk", "taka", "৳", "রেট", "মূল্য", "price", "cost"]):
                    m_q = re.search(r'\b(\d{2,4})\b', clean_for_qty)
                if m_q:
                    try:
                        entities["quantity"] = int(m_q.group(1))
                    except Exception:
                        pass

        # Quantity from existing conversation state as context
        if entities["quantity"] is None and conversation_state:
            entities["quantity"] = conversation_state.get("quantity")

        pkg_match = re.search(r'(?:প্যাকেজ|package|pkg)\s*([১-৭1-7])', norm_msg)
        if pkg_match:
            entities["package_id"] = normalize_package_id(pkg_match.group(1))
        elif conversation_state and conversation_state.get("package_id"):
            entities["package_id"] = conversation_state.get("package_id")

        dem_match = re.search(r'(\d{2,4})\s*(?:টাকা|টাকায়|টাকাতে|tk|taka|৳)\s*(?:করে\s*)?(?:রাখ|দেন|দিবেন|হবে|নেব|রাখবেন|করেন|কইরেন|হবেনা)?', digits_norm_msg)
        if dem_match:
            try:
                p_val = float(dem_match.group(1))
                if p_val not in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]:
                    if any(kw in norm_msg for kw in ["রাখ", "দেন", "দিবেন", "হবে", "নেব", "রাখবেন", "করেন", "কইরেন", "সম্মতি", "অনুমতি", "কমান", "ছাড়", "যাবে"]):
                        entities["demanded_price"] = p_val
                        entities["is_negotiating"] = True
            except Exception:
                pass

        if any(kw in norm_msg for kw in ["ঢাকা", "ঢাকার ভেতরে", "মিরপুর", "ধানমন্ডি", "উত্তরা", "গুলশান", "inside dhaka"]):
            entities["location"] = "inside_dhaka"
        elif any(kw in norm_msg for kw in ["ঢাকার বাইরে", "চট্টগ্রাম", "সিলেট", "রাজশাহী", "খুলনা", "বরিশাল", "রংপুর", "outside dhaka", "গ্রাম"]):
            entities["location"] = "outside_dhaka"

        is_query = any(q in norm_msg for q in ["কত", "দাম", "রেট", "কী", "কি", "কেমন", "কবে", "কোথায়", "কেন", "price", "cost", "koto", "dam"])
        affirmative_words = ["জি", "হ্যাঁ", "হুম", "hm", "yes", "jee", "ji", "আচ্ছা", "ঠিক আছে", "ok", "sure", "haa", "ha"]
        if not is_query and (norm_msg in affirmative_words or any(norm_msg == w or (len(norm_msg.split()) <= 3 and (norm_msg.startswith(w + " ") or norm_msg.endswith(" " + w))) for w in affirmative_words)):
            entities["is_affirmative"] = True

        if any(kw in norm_msg for kw in ["আবার পাঠান", "পুনরায় পাঠান", "আগের ছবিটা আবার", "ছবি আবার দিন", "আবার দেখান", "আবার ছবি"]):
            entities["is_resample_request"] = True

        # -------------------------------------------------------------
        # 2. CONTEXTUAL REASONING FROM HISTORY
        # -------------------------------------------------------------
        last_bot_msg = ""
        pending_question = conversation_state.get("pending_question") if conversation_state else ""
        if conversation_history:
            for h in reversed(conversation_history):
                r = str(h.get("sender") or h.get("sender_role") or h.get("role") or "").lower()
                if r in ("bot", "assistant", "ai"):
                    last_bot_msg = str(h.get("text") or h.get("content") or "").lower()
                    break

        # -------------------------------------------------------------
        # 3. SEMANTIC INTENT CLASSIFICATION
        # -------------------------------------------------------------
        # A. Agent Identity Inquiry (Bangla + Banglish)
        agent_identity_words = [
            "তোমার নাম", "আপনার নাম", "who are you", "what is your name", "who is this",
            "কার সাথে কথা", "কার সাথে কথা বলছি", "আপনি কে", "তুমি কে", "কে কথা বলছেন",
            "কে বলছেন", "apni ke", "apni k", "tumi ke", "apnar nam ki", "tomar nam ki", "ke bolchen"
        ]
        if any(kw in norm_msg for kw in agent_identity_words) or re.search(r'\b(?:আপনি|তুমি)\s*কে\b', norm_msg):
            detected_intents.append(CustomerIntent.AGENT_IDENTITY_INQUIRY)

        # B. Owner Identity Inquiry
        owner_words = [
            "owner এর নাম", "owner-এর নাম", "মালিকের নাম", "ওনারের নাম", "বসের নাম",
            "owner কে", "মালিক কে", "ওনার কে", "who is the owner", "owner name",
            "বসের সাথে", "কথা বলব", "স্যার এর সাথে", "রাশেদ", "rashed"
        ]
        if any(kw in norm_msg for kw in owner_words) or re.search(r'(?:owner|ওনার|মালিক|বস)[-\s]*(?:এর)?\s*(?:নাম|কে)', norm_msg):
            detected_intents.append(CustomerIntent.OWNER_REQUEST)

        # C. Social Pleasantry (Bangla + Banglish)
        pleasantry_phrases = [
            "কেমন আছেন", "কেমন আছ", "কেমন আছো", "কি খবর", "কী খবর", "ভালো আছেন",
            "ভাল আছেন", "ভালো আছো", "ভালো আছ", "কেমন চলছে", "how are you",
            "আপনি ভালো", "ভালো তো", "সুস্থ আছেন", "মজায় আছেন",
            "bhalo achen", "kemon achen", "ki khobor", "bhalo asen", "kemon asen", "valo achen"
        ]
        if any(kw in norm_msg for kw in pleasantry_phrases):
            detected_intents.append(CustomerIntent.SOCIAL_PLEASANTRY)

        # D. Greeting (Bangla + Banglish)
        if any(kw in norm_msg for kw in ["সালাম", "salam", "assalam", "হাই", "হ্যালো", "hello", "hi", "hey"]):
            detected_intents.append(CustomerIntent.GREETING)

        # E. Google Form Correction Help / Media Request
        if any(kw in norm_msg for kw in ["তথ্য সংশোধন", "সংশোধনের নিয়ম", "সংশোধন করার নিয়ম", "সংশোধন করার ভিডিও", "সংশোধনের ভিডিও", "ফর্ম ভিডিও", "ভিডিও দেন", "ভিডিও দিন", "কীভাবে পূরণ", "ভিডিও", "সংশোধন"]):
            detected_intents.append(CustomerIntent.GOOGLE_FORM_CORRECTION_HELP)
            detected_intents.append(CustomerIntent.MEDIA_REQUEST)

        # F. Photo Taking Service Policy
        if any(kw in norm_msg for kw in [
            "ছবি কি আপনারা তুলে", "ছবি কি আপনারা তোলেন", "ছবি কি আপনারা তুলে দেন", "ছবি তুলে দেন", "ছবি কি তুলে দেন",
            "ছবি তোলার ব্যবস্থা", "ফটোগ্রাফার", "ছবি কি তুলবেন", "ছবি তুলে দেবেন", "ছবি তুলে দিবেন", "ছবি কি তোলেন", "ছবি তোলেন"
        ]) or ("ছবি" in norm_msg and any(kw in norm_msg for kw in ["তুলে দেন", "তুলে দিবেন", "তুলে দেবেন", "তোলার ব্যবস্থা", "তুলে নেন", "তোলেন কি"])):
            detected_intents.append(CustomerIntent.PHOTO_SERVICE)
            entities["topic"] = "photo_service"

        # G. Specific Item Pricing
        if entities["is_specific_item"]:
            detected_intents.append(CustomerIntent.SPECIFIC_ITEM_PRICE)

        # H. Price Inquiry vs Per Piece Rate
        price_keywords = [
            "প্রতি পিস কত", "প্রতি পিস কত টাকা", "প্রতি পিস কত রাখা যাবে", "দাম কত", "রেট কত",
            "কত টাকা", "খরচ কত", "মূল্য কত", "কত পড়বে", "কত পরবে", "হিসাব কত", "price", "cost",
            "প্যাকেজের দাম", "প্যাকেজের রেট", "প্যাকেজ কত", "প্যাকেজ মূল্য", "প্যাকেজগুলোর দাম",
            "per piece koto", "dam koto", "rate koto", "koto tk"
        ]
        if any(kw in norm_msg for kw in price_keywords) or pkg_match:
            if any(kw in norm_msg for kw in ["প্রতি পিস", "per piece", "এক পিস", "প্রতিটি"]):
                detected_intents.append(CustomerIntent.PER_PIECE_PRICE)
            else:
                detected_intents.append(CustomerIntent.PRICE_INQUIRY)
        elif entities["package_id"] and any(kw in norm_msg for kw in ["এটা কত", "দাম কত", "রেট কত", "কত", "মূল্য"]):
            detected_intents.append(CustomerIntent.PRICE_INQUIRY)

        # I. Negotiation / Discount Request
        _neg_regex = re.search(
            r'কম\s*(?:রাখা|করা|হওয়া|হবে|রাখবেন|দেওয়া|যাবে|যায়|করবেন|করেন|কইরেন|রাখেন|হবেনা|রাখা যাবে না)'
            r'|একটু\s*কম|কিছু\s*কম|কমায়\s*দেন|কম\s*দেন|কম\s*রাখেন'
            r'|ডিসকাউন্ট|ছাড়\s*(?:দেন|হবে|দিবেন)?|বেশি\s*রাখছেন|সম্মান\s*করবেন'
            r'|অনুমতি\s*দিয়েছে|সম্মতি\s*আছে',
            norm_msg
        )
        if entities["is_negotiating"] or _neg_regex or any(kw in norm_msg for kw in [
            "কম রাখা যায় না", "কম রাখবেন", "কম হবে না", "কম করা যাবে না", "কম রাখা যাবে না",
            "কম হবে?", "কম রাখা যাবে", "কম রাখা যাবে কি", "কম রাখবেন কি", "কিছু কম", "একটু কম",
            "ডিসকাউন্ট দেন", "ডিসকাউন্ট", "ছাড় দেন", "ছাড় হবে", "কিছু কম রাখেন", "কিছু কম হবে",
            "সম্মান করবেন", "একটু কম রাখেন", "বেশি রাখছেন", "কমায় দেন", "অনুমতি দিয়েছে", "সম্মতি আছে"
        ]):
            detected_intents.append(CustomerIntent.NEGOTIATION)
            entities["is_negotiating"] = True

        # J. Delivery Fee / Delivery Time
        if any(kw in norm_msg for kw in ["ডেলিভারি চার্জ", "কুরিয়ার চার্জ", "ডেলিভারি", "কুরিয়ার", "delivery", "delivery charge"]):
            detected_intents.append(CustomerIntent.DELIVERY_INQUIRY)
        if any(kw in norm_msg for kw in ["কবে পাব", "কয়দিন লাগবে", "কতদিন লাগবে", "ডেলিভারি সময়", "কত সময় লাগবে", "সময় কত"]):
            detected_intents.append(CustomerIntent.DELIVERY_TIME_INQUIRY)

        # K. Advance / COD Policy
        if any(kw in norm_msg for kw in ["অগ্রিম", "এডভান্স", "advance", "ক্যাশ অন ডেলিভারি", "cod", "পেমেন্ট", "বিকাশ"]):
            detected_intents.append(CustomerIntent.ADVANCE_INQUIRY)

        # L. Quality Inquiry
        quality_phrases = [
            "কোয়ালিটি কেমন", "কোয়ালিটি কেমন হবে", "মান কেমন", "কোয়ালিটি সম্পর্কে",
            "কোয়ালিটি জানতে চাই", "কার্ড ও ফিতার কোয়ালিটি", "কোয়ালিটি", "quality kemon"
        ]
        quality_not = ["প্যাকেজ", "দাম কত", "কত করে", "খরচ কত"]
        if any(kw in norm_msg for kw in quality_phrases) and not any(kw in norm_msg for kw in quality_not):
            detected_intents.append(CustomerIntent.QUALITY_INQUIRY)

        # M. Sample & Resample Requests
        if entities["is_resample_request"]:
            detected_intents.append(CustomerIntent.RESAMPLE_REQUEST)
        if any(kw in norm_msg for kw in ["স্যাম্পল", "ছবি পাঠান", "ছবি দেন", "নমুনা পাঠান", "প্যাকেজের ছবি", "প্যাকেজ দেখতে চাই", "স্যাম্পল দেখতে চাই"]):
            detected_intents.append(CustomerIntent.SAMPLE_REQUEST)

        # N. Non-ID Products / Topic Change
        non_id_products = ["ব্যানার", "মগ", "টি-শার্ট", "টি শার্ট", "ভিজিটিং কার্ড", "ক্যালেন্ডার", "সিল", "পোস্টার", "লিফলেট", "রশিদ", "ডোনেশন", "বই", "প্যাড", "ফ্লাইয়ার"]
        if "মসজিদ" in norm_msg and any(kw in norm_msg for kw in ["বানাবো না", "বানাব না", "লাগবে না", "লাগবে", "জন্য"]):
            detected_intents.append(CustomerIntent.TOPIC_CHANGE)
            entities["topic"] = "mosque_requirement"
        elif any(p in norm_msg for p in non_id_products) and not any(kw in norm_msg for kw in ["আইডি কার্ড", "id card"]):
            detected_intents.append(CustomerIntent.TOPIC_CHANGE)
            entities["topic"] = "non_id_product_inquiry"

        # O. MOQ Rejection
        if entities["quantity"] is not None and entities["quantity"] < 30 and not entities["is_specific_item"]:
            detected_intents.append(CustomerIntent.MOQ_REJECTED)

        # P. Quantity Provided (Explicit quantity in current message without higher intent override)
        # Check if quantity was explicitly stated in current message text
        current_msg_has_qty = False
        try:
            from app.ai_agent.gemini_brain import extract_order_quantity_number
            if extract_order_quantity_number(raw_msg):
                current_msg_has_qty = True
        except Exception:
            pass
        if current_msg_has_qty and entities["quantity"] is not None and entities["quantity"] >= 30 and not entities["is_specific_item"]:
            if not any(i in detected_intents for i in (CustomerIntent.PRICE_INQUIRY, CustomerIntent.NEGOTIATION, CustomerIntent.DELIVERY_INQUIRY, CustomerIntent.GREETING, CustomerIntent.SAMPLE_REQUEST)):
                detected_intents.append(CustomerIntent.QUANTITY_PROVIDED)

        # Q. Contextual Affirmation (Only consumed if no higher-priority direct intent was expressed)
        if entities["is_affirmative"] and not any(i in detected_intents for i in (CustomerIntent.AGENT_IDENTITY_INQUIRY, CustomerIntent.OWNER_REQUEST, CustomerIntent.SOCIAL_PLEASANTRY, CustomerIntent.PRICE_INQUIRY, CustomerIntent.DELIVERY_INQUIRY)):
            if pending_question == "SAMPLE_PERMISSION_PROMPT" or "স্যাম্পল পাঠাবো কি" in last_bot_msg or "স্যাম্পলগুলো পাঠাবো কি" in last_bot_msg:
                detected_intents.append(CustomerIntent.SAMPLE_CONFIRMATION)
            elif pending_question == "PACKAGE_SELECTION_PROMPT" or "প্যাকেজটি পছন্দ" in last_bot_msg:
                detected_intents.append(CustomerIntent.PACKAGE_SELECTION)
            elif pending_question == "QUANTITY_PROMPT" or "কত পিস" in last_bot_msg:
                detected_intents.append(CustomerIntent.QUANTITY_INQUIRY)
            else:
                detected_intents.append(CustomerIntent.SAMPLE_CONFIRMATION)

        # R. General ID Card Product Interest
        if any(kw in norm_msg for kw in ["আইডি কার্ড", "id card", "কার্ড বানাবো", "কার্ড বানাতে", "কার্ড করতে চাই", "কার্ডের কাজ", "কার্ড লাগবে", "কার্ড তৈরি"]):
            if entities["quantity"] is None and not entities["package_id"] and not any(i in detected_intents for i in (CustomerIntent.PRICE_INQUIRY, CustomerIntent.GREETING, CustomerIntent.TOPIC_CHANGE, CustomerIntent.SOCIAL_PLEASANTRY)):
                detected_intents.append(CustomerIntent.PRODUCT_INQUIRY)

        # Deduplicate preserving strict priority order
        dedup_intents: List[CustomerIntent] = []
        for it in INTENT_PRIORITY_ORDER:
            if it in detected_intents and it not in dedup_intents:
                dedup_intents.append(it)

        # Append any unranked intents
        for it in detected_intents:
            if it not in dedup_intents:
                dedup_intents.append(it)

        if not dedup_intents:
            dedup_intents.append(CustomerIntent.UNKNOWN)

        primary_intent = dedup_intents[0]

        requires_state_continuation = primary_intent in (
            CustomerIntent.SAMPLE_CONFIRMATION,
            CustomerIntent.PACKAGE_SELECTION,
            CustomerIntent.QUANTITY_PROVIDED
        )
        requires_knowledge_lookup = primary_intent in (
            CustomerIntent.UNKNOWN,
            CustomerIntent.TOPIC_CHANGE,
            CustomerIntent.QUALITY_INQUIRY
        )

        return {
            "primary_intent": primary_intent,
            "intents": dedup_intents,
            "confidence": 0.98 if primary_intent != CustomerIntent.UNKNOWN else 0.40,
            "entities": entities,
            "requires_state_continuation": requires_state_continuation,
            "requires_knowledge_lookup": requires_knowledge_lookup
        }

    @classmethod
    def execute_decision(
        cls,
        customer_message: str,
        sender_id: Optional[str] = None,
        customer_name: str = "Customer",
        workspace_id: int = 1,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        channel: str = "facebook",
        image_bytes: bytes = None,
        image_mime: str = "image/jpeg",
        image_list: list = None,
        audio_bytes: bytes = None,
        audio_mime: str = "audio/mp4",
        generate_voice_reply: bool = False,
        page_id: str = None
    ) -> Dict[str, Any]:
        """
        Executes central decision orchestration across authoritative tools and returns validated payload.
        Guarantees EXACTLY ONE authoritative response decision per customer message.
        """
        ws_id = int(workspace_id or 1)
        honorific = detect_customer_gender_title(customer_name)
        s_id = str(sender_id or "web_user").strip()

        try:
            # 0. FALL THROUGH TO GEMINI IF WORKSPACE != 1
            if ws_id != 1:
                return {
                    "reply_text": "",
                    "matched_images": [],
                    "media_sequence": [],
                    "voice_url": "",
                    "video_url": "",
                    "order_created": None,
                    "response_source": "gemini_fallthrough",
                    "ai_reply_allowed": True,
                    "orchestrator_log": {
                        "primary_intent": CustomerIntent.UNKNOWN,
                        "intents": [],
                        "entities": {},
                        "selected_tools": ["gemini_brain_delegate"],
                        "requires_owner_approval": False
                    }
                }

            # -------------------------------------------------------------
            # STEP 1: HUMAN / ADMIN TAKEOVER CHECK (Absolute Silence Guard)
            # -------------------------------------------------------------
            if sender_id and not is_conversation_ai_active(sender_id=s_id, workspace_id=ws_id):
                return {
                    "reply_text": "",
                    "matched_images": [],
                    "media_sequence": [],
                    "voice_url": "",
                    "video_url": "",
                    "order_created": None,
                    "is_blocked": True,
                    "block_reason": "admin_takeover_active",
                    "ai_reply_allowed": False,
                    "response_source": "admin_takeover_silence",
                    "orchestrator_log": {
                        "primary_intent": CustomerIntent.UNKNOWN,
                        "intents": [],
                        "entities": {},
                        "selected_tools": ["admin_takeover_silence"],
                        "requires_owner_approval": False
                    }
                }

            # -------------------------------------------------------------
            # STEP 1.5: MULTIMODAL DELEGATION (Images / Voice Notes)
            # -------------------------------------------------------------
            if image_bytes or audio_bytes or (image_list and len(image_list) > 0):
                return {
                    "reply_text": "",
                    "matched_images": [],
                    "media_sequence": [],
                    "voice_url": "",
                    "video_url": "",
                    "order_created": None,
                    "response_source": "multimodal_delegate",
                    "ai_reply_allowed": True,
                    "orchestrator_log": {
                        "primary_intent": CustomerIntent.UNKNOWN,
                        "intents": [],
                        "entities": {},
                        "selected_tools": ["gemini_multimodal_delegate"],
                        "requires_owner_approval": False
                    }
                }

            # -------------------------------------------------------------
            # STEP 2: CONVERSATION MEMORY & PERSISTED STATE
            # -------------------------------------------------------------
            conversation_state = get_structured_conversation_state(s_id, ws_id)
            samples_already_sent = is_media_already_sent(s_id, "samples", ws_id)
            memory_dict = get_conversation_memory(s_id, ws_id)

            # -------------------------------------------------------------
            # STEP 3: INTENT & TOPIC UNDERSTANDING
            # -------------------------------------------------------------
            intent_data = cls.detect_intents_and_entities(
                message=customer_message,
                conversation_history=conversation_history,
                conversation_state=conversation_state
            )
            primary_intent = intent_data["primary_intent"]
            all_intents = intent_data["intents"]
            entities = intent_data["entities"]
            effective_qty = entities.get("quantity")

            selected_tools = []
            requires_owner_approval = False
            response_source = "orchestrator"
            draft_reply = ""
            matched_images = []
            media_sequence = []
            voice_url = ""
            video_url = ""

            # -------------------------------------------------------------
            # STEP 3.5: GOOGLE FORM WORKFLOW (Highest Priority for Form Inquiries)
            # -------------------------------------------------------------
            if not (CustomerIntent.GOOGLE_FORM_CORRECTION_HELP in all_intents or CustomerIntent.MEDIA_REQUEST in all_intents):
                try:
                    from app.ai_agent.gemini_brain import resolve_google_form_workflow
                    gf_res = resolve_google_form_workflow(
                        user_message=customer_message,
                        conversation_history=conversation_history,
                        customer_phone=s_id,
                        customer_name=customer_name,
                        workspace_id=ws_id
                    )
                    if gf_res and gf_res.get("reply"):
                        draft_reply = gf_res["reply"]
                        voice_url = gf_res.get("voice_url", "")
                        video_url = gf_res.get("video_url", "")
                        response_source = "deterministic_google_form"
                        selected_tools.append("google_form_workflow")

                        return {
                            "reply_text": draft_reply,
                            "matched_images": [],
                            "media_sequence": [],
                            "voice_url": voice_url,
                            "video_url": video_url,
                            "order_created": None,
                            "response_source": response_source,
                            "ai_reply_allowed": True,
                            "google_form_workflow": gf_res,
                            "orchestrator_log": {
                                "primary_intent": primary_intent,
                                "intents": all_intents,
                                "entities": entities,
                                "selected_tools": selected_tools,
                                "requires_owner_approval": False,
                                "response_source": response_source
                            }
                        }
                except Exception as gf_err:
                    print(f"[Orchestrator Google Form Workflow Error]: {gf_err}")

            # -------------------------------------------------------------
            # STEP 4: AUTHORITATIVE INTENT DISPATCH PIPELINE
            # -------------------------------------------------------------
            # A. AGENT IDENTITY INQUIRY ("আপনি কে", "তোমার নাম কী")
            if primary_intent == CustomerIntent.AGENT_IDENTITY_INQUIRY:
                selected_tools.append("knowledge_engine")
                draft_reply = f"জি {honorific}, আমার নাম নাদিম, আমি RS Graphics-এর পক্ষ থেকে আপনাকে সহযোগিতা করছি। আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ?"
                response_source = "agent_identity_inquiry"

            # B. OWNER IDENTITY / PRIVACY ("Owner এর নাম কী", "মালিক কে")
            elif primary_intent == CustomerIntent.OWNER_REQUEST:
                selected_tools.append("knowledge_engine")
                if s_id:
                    create_team_escalation(
                        sender_id=str(s_id),
                        customer_message=customer_message,
                        detected_unknown_topic="owner_identity_inquiry",
                        workspace_id=ws_id,
                        source_channel=channel
                    )
                # Specific mention of Rashed Bhai
                raw_msg_lower = (customer_message or "").strip().lower()
                if any(p in raw_msg_lower for p in ["রাশেদ ভাই", "রাশেদ কোথায়", "rashed bhai", "রাশেদুল ইসলাম", "রাশেদ কে"]):
                    draft_reply = f"জি {honorific}, রাশেদ স্যার আমাদের ওনার স্যার। আপনার বিষয়টি ওনার স্যারকে জানিয়ে দিচ্ছি।"
                    response_source = "owner_mention_rule_13"
                else:
                    draft_reply = f"জি {honorific}, Owner স্যারের নামের তথ্যটি এই মুহূর্তে আমার কাছে সংরক্ষিত নেই। বিষয়টি আমাদের টিমকে জানাচ্ছি। আমাদের টিম আপনাকে জানাবে।"
                    response_source = "owner_identity_escalation"

            # C. SOCIAL PLEASANTRY ("ভালো আছেন?", "কেমন আছেন?")
            elif primary_intent == CustomerIntent.SOCIAL_PLEASANTRY:
                selected_tools.append("conversation_engine")
                norm_msg = (customer_message or "").strip().lower()
                has_salam = any(kw in norm_msg for kw in ["সালাম", "salam", "assalam"])
                if has_salam:
                    draft_reply = f"ওয়ালাইকুমুস সালাম {honorific}! আলহামদুলিল্লাহ, ভালো আছি। আপনি কেমন আছেন? আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।"
                else:
                    draft_reply = f"আলহামদুলিল্লাহ {honorific}, ভালো আছি। আপনি কেমন আছেন? আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।"
                response_source = "social_pleasantry_response"

            # D. GOOGLE FORM HELP / MEDIA VIDEO REQUEST
            elif CustomerIntent.GOOGLE_FORM_CORRECTION_HELP in all_intents or CustomerIntent.MEDIA_REQUEST in all_intents:
                selected_tools.append("media_router")
                m_res = MediaRouter.route_media(
                    message=customer_message,
                    workspace_id=ws_id,
                    conversation_state=conversation_state
                )
                video_url = m_res.get("video_url") or "/static/uploads/media/google_form_edit_correction_guide.mp4"
                draft_reply = f"জি {honorific}, গুগল ফর্মে তথ্য সাবমিট করার পর ভুল হলে তা সংশোধন করার নিয়মের ভিডিও গাইড নিচে দেওয়া হলো:"
                response_source = "media_router_video_dispatch"

            # E. PHOTO TAKING SERVICE POLICY
            elif primary_intent == CustomerIntent.PHOTO_SERVICE:
                selected_tools.append("knowledge_engine")
                draft_reply = (
                    f"জি {honorific}, আমরা ছবি তোলার সার্ভিস প্রদান করি না। ছবি ও তথ্য আপনাকেই তুলে দিতে হবে। "
                    f"আমরা সম্পূর্ণ কাজ তৈরি করে, প্রিমিয়াম প্রিন্ট ও ডেলিভারি সম্পন্ন করে দেব।"
                )
                response_source = "photo_service_policy"

            # F. TOPIC CHANGE / OTHER PRODUCTS
            elif primary_intent == CustomerIntent.TOPIC_CHANGE:
                selected_tools.append("knowledge_engine")
                if entities.get("topic") == "mosque_requirement":
                    draft_reply = f"জি {honorific}, আপনার মসজিদের কী ধরণের কাজ প্রয়োজন জানাবেন প্লিজ (যেমন: আইডি কার্ড, ডোনেশন রশিদ, ব্যানার বা সিল)? আমরা আপনার প্রয়োজন অনুযায়ী সহায়তা করতে পারব।"
                    response_source = "topic_switch_clarification"
                else:
                    k_res = KnowledgeEngine.retrieve_relevant_knowledge(customer_message, workspace_id=ws_id)
                    if k_res.get("has_authoritative_answer") and k_res.get("direct_answers"):
                        r_rule = k_res["direct_answers"][0]
                        draft_reply = f"জি {honorific}, {r_rule.get('response_or_rule', '')}"
                        response_source = "training_rule_answer"
                    else:
                        unk = KnowledgeEngine.handle_unknown_inquiry(
                            customer_message=customer_message,
                            sender_id=s_id,
                            detected_topic=entities.get("topic") or "other_product",
                            workspace_id=ws_id,
                            customer_name=customer_name,
                            channel=channel
                        )
                        draft_reply = unk["reply_text"]
                        response_source = "no_guess_team_escalation"

            # G. MOQ POLICY REJECTION (< 30 pcs)
            elif primary_intent == CustomerIntent.MOQ_REJECTED or (effective_qty is not None and effective_qty < 30 and not entities.get("is_specific_item")):
                selected_tools.append("pricing_engine")
                draft_reply = f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"
                response_source = "moq_rejected_policy"

            # H. SAMPLE DELIVERY & RESAMPLE
            elif primary_intent in (CustomerIntent.SAMPLE_REQUEST, CustomerIntent.SAMPLE_CONFIRMATION, CustomerIntent.RESAMPLE_REQUEST):
                selected_tools.append("media_router")
                if samples_already_sent and not entities.get("is_resample_request"):
                    draft_reply = f"জি {honorific}, পূর্বের পাঠানো স্যাম্পল ও প্যাকেজগুলো দেখে আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন প্লিজ, অথবা আপনার আর কোনো কিছু জানার থাকলে বলুন {honorific}।"
                    response_source = "samples_already_sent_acknowledged"
                else:
                    from app.ai_agent.gemini_brain import detect_sample_photos_to_send, generate_sample_delivery_sequence, get_package_sample_images
                    seq = generate_sample_delivery_sequence(workspace_id=ws_id)
                    matched_imgs = detect_sample_photos_to_send(customer_message, conversation_history, "স্যাম্পলগুলো নিচে পাঠানো হলো", workspace_id=ws_id)
                    if not matched_imgs:
                        matched_imgs = get_package_sample_images(workspace_id=ws_id)

                    try:
                        record_media_dispatched(s_id, "samples", matched_imgs, ws_id)
                        record_question_asked(s_id, "PACKAGE_SELECTION_PROMPT", ws_id)
                    except Exception:
                        pass
                    draft_reply = f"জি {honorific}, অবশ্যই দিচ্ছি।"
                    matched_images = matched_imgs
                    media_sequence = seq
                    response_source = "sample_dispatch_pipeline"

            # I. QUALITY INQUIRY VOICE DISPATCH
            elif primary_intent == CustomerIntent.QUALITY_INQUIRY:
                selected_tools.append("knowledge_engine")
                draft_reply = f"জি {honorific}, আমাদের কার্ড ও ফিতার কোয়ালিটি ও বৈশিষ্ট্য কেমন হবে সে সম্পর্কে বিস্তারিত জানতে নিচের ভয়েস বার্তাটি শুনুন:"
                voice_url = "/static/uploads/media/id_card_and_fita_quality.aac"
                response_source = "id_card_quality_voice_dispatch"

            # J. PURE GREETING ("আসসালামু আলাইকুম", "Hi", "Hello")
            elif primary_intent == CustomerIntent.GREETING:
                norm_msg = (customer_message or "").strip().lower()
                has_product_ref = any(kw in norm_msg for kw in ["আইডি কার্ড", "id card", "কার্ড", "ফিতা", "কভার", "প্যাকেজ", "বানাবো", "বানাতে", "লাগবে"])
                if has_product_ref and effective_qty is not None and effective_qty >= 30:
                    draft_reply = f"ওয়ালাইকুমুস সালাম {honorific}! আরএস গ্রাফিক্সে আপনাকে স্বাগতম। আপনার {effective_qty} পিস আইডি কার্ডের অর্ডারের জন্য কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ?"
                elif has_product_ref:
                    draft_reply = f"ওয়ালাইকুমুস সালাম {honorific}! আরএস গ্রাফিক্সে আপনাকে স্বাগতম। আপনি কত পিস আইডি কার্ড বানাতে চান জানাবেন প্লিজ?"
                else:
                    draft_reply = f"ওয়ালাইকুমুস সালাম {honorific}! আরএস গ্রাফিক্সে আপনাকে স্বাগতম। আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।"
                response_source = "standard_greeting"

            # K. QUANTITY PROVIDED
            elif primary_intent == CustomerIntent.QUANTITY_PROVIDED:
                selected_tools.append("pricing_engine")
                try:
                    update_conversation_state(s_id, {"quantity": effective_qty, "current_sales_stage": SalesStage.QUANTITY_IDENTIFIED}, reason="quantity_acknowledged", workspace_id=ws_id)
                    record_fact_confirmed(s_id, "quantity", effective_qty, ws_id)
                except Exception:
                    pass

                tier = get_quantity_tier(effective_qty) if effective_qty else None
                if not samples_already_sent:
                    if tier == QuantityTier.SMALL_ORDER:
                        draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (৩০-৪৯ পিস টিয়ারে) প্যাকেজ রেট প্রতি সেট ৮০ টাকা থেকে ১০১ টাকা (80 Tk - 101 Tk) (প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য)। আমাদের স্যাম্পলগুলো পাঠাবো কি?"
                    else:
                        draft_reply = f"জি {honorific}, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"
                    record_question_asked(s_id, "SAMPLE_PERMISSION_PROMPT", ws_id)
                    response_source = "sample_permission_prompt"
                else:
                    draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের তথ্য পেয়েছি। কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                    response_source = "quantity_acknowledged_package_prompt"

            # L. SPECIFIC ITEM PRICING
            elif primary_intent == CustomerIntent.SPECIFIC_ITEM_PRICE:
                selected_tools.append("pricing_engine")
                norm_msg = customer_message.lower()
                if "t-014" in norm_msg or "t014" in norm_msg:
                    if "কভার" in norm_msg or "cover" in norm_msg:
                        draft_reply = f"জি {honorific}, T-014 কভার ১০০+ পিস অর্ডারে প্রতি পিস ১০ টাকা (10 Tk)। ৫০-৭৯ পিসে ১২ টাকা এবং ৩০-৪৯ পিসে ১৫ টাকা।"
                    else:
                        draft_reply = f"জি {honorific}, T-014 ফিতা ১০০+ পিস অর্ডারে প্রতি পিস ১৫ টাকা (রেগুলার রেট)। ৩০-৪৯ পিসে প্রতি পিস ২৫ টাকা এবং ৫০-৭৯ পিসে প্রতি পিস ২০ টাকা।"
                elif "dx" in norm_msg:
                    draft_reply = f"জি {honorific}, DX কভার ১০০+ পিস অর্ডারে প্রতি পিস ১২ টাকা (12 Tk)। ৫০-৭৯ পিসে ১৫ টাকা এবং ৩০-৪৯ পিসে ১৮ টাকা।"
                elif "মেটাল কভার" in norm_msg or "metal cover" in norm_msg:
                    draft_reply = f"জি {honorific}, মেটাল কভার ১০০+ পিস অর্ডারে প্রতি পিস ৩৫ টাকা। ৫০-৭৯ পিসে প্রতি পিস ৪০ টাকা এবং ৩০-৪৯ পিসে প্রতি পিস ৪৫ টাকা।"
                elif "শুধু ফিতা" in norm_msg:
                    draft_reply = f"জি {honorific}, শুধু ফিতা (ডিজিটাল প্রিন্ট) ১০০+ পিস অর্ডারে প্রতি পিস ১৫ টাকা। ৩০-৪৯ পিসে ২৫ টাকা এবং ৫০-৭৯ পিসে ২০ টাকা।"
                elif "শুধু কার্ড" in norm_msg:
                    draft_reply = f"জি {honorific}, শুধু আইডি কার্ড (UV প্রিন্ট) ১০০+ পিস অর্ডারে প্রতি পিস ১৫ টাকা। ৩০-৪৯ পিসে ২৫ টাকা এবং ৫০-৭৯ পিসে ২০ টাকা।"
                elif "শুধু কভার" in norm_msg:
                    draft_reply = f"জি {honorific}, শুধু নরমাল কভার ১০০+ পিস অর্ডারে প্রতি পিস ৮ টাকা। ৫০-৭৯ পিসে ১০ টাকা এবং ৩০-৪৯ পিসে ১২ টাকা।"
                else:
                    draft_reply = f"জি {honorific}, আমাদের শুধু কার্ড ১৫ টাকা, ডিজিটাল ফিতা ১৫ টাকা এবং মেটাল কভার ৩৫ টাকা (১০০+ পিস অর্ডারের রেগুলার রেট)। আপনার কত পিস প্রয়োজন জানাবেন প্লিজ।"
                response_source = "specific_item_pricing"

            # M. PER PIECE PRICE INQUIRY
            elif primary_intent == CustomerIntent.PER_PIECE_PRICE:
                selected_tools.append("pricing_engine")
                p_num = entities.get("package_id")
                if p_num and effective_qty is not None and effective_qty >= 30:
                    tier = get_quantity_tier(effective_qty)
                    p_info = calculate_package_price(package_id=p_num, quantity=effective_qty)
                    p_price = int(p_info["effective_unit_price"])

                    if tier == QuantityTier.BULK:
                        draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজ {p_num}-এর রেগুলার রেট প্রতি সেট {p_price} টাকা।"
                    elif tier == QuantityTier.REGULAR:
                        draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজ {p_num}-এর ফিক্সড রেট প্রতি সেট {p_price} টাকা।"
                    else:
                        draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (৩০-৪৯ পিস টিয়ারে) প্যাকেজ {p_num}-এর রেট প্রতি সেট {p_price} টাকা (প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য)।"
                    response_source = "per_piece_known_quantity"
                elif effective_qty is not None and effective_qty >= 30:
                    pkg_lines = []
                    for pid in range(1, 8):
                        p_info = calculate_package_price(package_id=pid, quantity=effective_qty)
                        u_p = int(p_info['effective_unit_price'])
                        bn_p = str(u_p).replace('0','০').replace('1','১').replace('2','২').replace('3','৩').replace('4','৪').replace('5','৫').replace('6','৬').replace('7','৭').replace('8','৮').replace('9','৯')
                        bn_pid = str(pid).replace('1','১').replace('2','২').replace('3','৩').replace('4','৪').replace('5','৫').replace('6','৬').replace('7','৭')
                        pkg_lines.append(f"• প্যাকেজ {bn_pid}: {bn_p} টাকা ({u_p} Tk)")
                    breakdown_str = "\n".join(pkg_lines)
                    draft_reply = (
                        f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজগুলোর রেট নিচে দেওয়া হলো:\n"
                        f"{breakdown_str}\n"
                        f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন প্লিজ {honorific}।"
                    )
                    response_source = "per_piece_known_quantity"
                else:
                    if entities.get("package_id"):
                        p_num = entities.get("package_id")
                        p_info = calculate_package_price(package_id=p_num, quantity=100)
                        p_price = int(p_info["effective_unit_price"])
                        draft_reply = f"জি {honorific}, প্যাকেজ {p_num}-এর রেগুলার রেট হলো প্রতি সেট {p_price} টাকা (সর্বনিম্ন ৩০ পিস)। আপনার কত পিস প্রয়োজন জানাবেন প্লিজ {honorific}?"
                    else:
                        draft_reply = (
                            f"জি {honorific}, আমাদের আইডি কার্ডের প্যাকেজ রেট প্রতি সেট ৭০ টাকা থেকে ৯১ টাকা (70 Tk - 91 Tk) পর্যন্ত "
                            f"(সর্বনিম্ন ৩০ পিস)। আপনার কত পিস প্রয়োজন জানালে আপনার জন্য প্রযোজ্য সঠিক রেট বলতে পারব {honorific}।"
                        )
                    response_source = "per_piece_unknown_quantity"

            # N. GENERAL PRICE INQUIRY / PACKAGE BREAKDOWN
            elif primary_intent == CustomerIntent.PRICE_INQUIRY:
                selected_tools.append("pricing_engine")
                p_num = entities.get("package_id")
                if p_num:
                    p_info = calculate_package_price(package_id=p_num, quantity=effective_qty or 100)
                    p_price = int(p_info["effective_unit_price"])
                    if effective_qty is not None and effective_qty >= 30:
                        tier = get_quantity_tier(effective_qty)
                        if tier == QuantityTier.BULK:
                            draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজ {p_num}-এর রেগুলার রেট প্রতি সেট {p_price} টাকা।"
                        elif tier == QuantityTier.REGULAR:
                            draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজ {p_num}-এর ফিক্সড রেট প্রতি সেট {p_price} টাকা।"
                        else:
                            draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (৩০-৪৯ পিস টিয়ারে) প্যাকেজ {p_num}-এর রেট প্রতি সেট {p_price} টাকা (প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য)।"
                    else:
                        draft_reply = f"জি {honorific}, প্যাকেজ {p_num}-এর রেগুলার রেট হলো প্রতি সেট {p_price} টাকা (সর্বনিম্ন ৩০ পিস)। আপনার কত পিস প্রয়োজন জানাবেন প্লিজ {honorific}?"
                    response_source = "package_price_known_quantity"
                elif effective_qty is not None and effective_qty >= 30:
                    pkg_lines = []
                    for pid in range(1, 8):
                        p_info = calculate_package_price(package_id=pid, quantity=effective_qty)
                        u_p = int(p_info['effective_unit_price'])
                        bn_p = str(u_p).replace('0','০').replace('1','১').replace('2','২').replace('3','৩').replace('4','৪').replace('5','৫').replace('6','৬').replace('7','৭').replace('8','৮').replace('9','৯')
                        bn_pid = str(pid).replace('1','১').replace('2','২').replace('3','৩').replace('4','৪').replace('5','৫').replace('6','৬').replace('7','৭')
                        pkg_lines.append(f"• প্যাকেজ {bn_pid}: {bn_p} টাকা ({u_p} Tk)")
                    breakdown_str = "\n".join(pkg_lines)
                    draft_reply = (
                        f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্রতিটি প্যাকেজের রেগুলার রেট নিচে দেওয়া হলো:\n"
                        f"{breakdown_str}\n"
                        f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন প্লিজ {honorific}।"
                    )
                    response_source = "package_breakdown_known_quantity"
                else:
                    draft_reply = (
                        f"জি {honorific}, আমাদের আইডি কার্ডের প্যাকেজ রেট প্রতি সেট ৭০ টাকা থেকে ৯১ টাকা (70 Tk - 91 Tk) পর্যন্ত "
                        f"(সর্বনিম্ন ৩০ পিস)। আপনার কত পিস প্রয়োজন জানালে আপনার জন্য প্রযোজ্য সঠিক রেট বলতে পারব {honorific}।"
                    )
                    response_source = "id_card_package_pricing_breakdown"

                if CustomerIntent.DELIVERY_INQUIRY in all_intents:
                    selected_tools.append("delivery_calculator")
                    draft_reply = f"{draft_reply} আমাদের ডেলিভারি চার্জ ঢাকার ভেতরে ৮০ টাকা (80 Tk) এবং ঢাকার বাইরে ১৩০ টাকা (130 Tk)।"

            # O. NEGOTIATION & DISCOUNT REQUEST
            elif primary_intent in (CustomerIntent.NEGOTIATION, CustomerIntent.DISCOUNT_REQUEST):
                selected_tools.append("pricing_engine")
                p_num = entities.get("package_id") or 7
                demanded = entities.get("demanded_price")

                if effective_qty is None or effective_qty < 30:
                    draft_reply = f"জি {honorific}, আপনার কত পিস প্রয়োজন জানাবেন প্লিজ? আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস।"
                    response_source = "negotiation_missing_quantity"
                else:
                    tier = get_quantity_tier(effective_qty)
                    if tier == QuantityTier.SMALL_ORDER:
                        draft_reply = f"দুঃখিত {honorific}, {effective_qty} পিস অর্ডারের ক্ষেত্রে (৩০-৪৯ পিস টিয়ারে) ফিক্সড রেট প্রযোজ্য—প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ রয়েছে এবং কোনো ডিসকাউন্ট প্রযোজ্য নয়।"
                        response_source = "discount_negotiation_response"
                    elif tier == QuantityTier.REGULAR:
                        draft_reply = f"দুঃখিত {honorific}, {effective_qty} পিস অর্ডারের ক্ষেত্রে আমাদের এই রেটটি ফিক্সড রেগুলার রেট। ১০০+ বাল্ক অর্ডারের ক্ষেত্রে স্পেশাল ডিসকাউন্ট পলিসি প্রযোজ্য হয়।"
                        response_source = "discount_negotiation_response"
                    else:
                        # 80+ Bulk Tier Step Negotiation
                        current_disc = memory_dict.get("current_discount", 0.0)
                        neg_res = negotiate_step(
                            package_id=p_num,
                            quantity=effective_qty,
                            current_discount=current_disc,
                            customer_demanded_price=demanded
                        )
                        draft_reply = neg_res["reply_text"]
                        offered_p = neg_res.get("offered_unit_price")
                        requires_owner_approval = neg_res.get("requires_owner_approval", False)

                        if offered_p is not None:
                            try:
                                update_conversation_state(s_id, {"quoted_price": offered_p}, reason="discount_negotiation", workspace_id=ws_id)
                                record_fact_confirmed(s_id, "offered_price", offered_p, ws_id)
                            except Exception:
                                pass
                        response_source = "discount_negotiation_response"

            # P. DELIVERY CHARGE & TIME
            elif primary_intent in (CustomerIntent.DELIVERY_INQUIRY, CustomerIntent.DELIVERY_TIME_INQUIRY):
                selected_tools.append("delivery_calculator")
                loc = entities.get("location")
                del_info = calculate_delivery_and_cod(subtotal=0.0, is_inside_dhaka=(loc != "outside_dhaka"))
                if primary_intent == CustomerIntent.DELIVERY_TIME_INQUIRY:
                    draft_reply = f"জি {honorific}, তথ্য ও ডিজাইন চূড়ান্ত হওয়ার পর সাধারণত ৩-৫ কার্যদিবসের মধ্যে ডেলিভারি সম্পন্ন হয়। ডেলিভারি চার্জ ঢাকার ভেতরে ৮০ টাকা (80 Tk) এবং ঢাকার বাইরে ১৩০ টাকা (130 Tk)।"
                else:
                    if loc == "outside_dhaka":
                        draft_reply = f"জি {honorific}, ঢাকার বাইরে আমাদের ডেলিভারি চার্জ ১৩০ টাকা (130 Tk) এবং ঢাকার ভেতরে ৮০ টাকা (80 Tk)।"
                    elif loc == "inside_dhaka":
                        draft_reply = f"জি {honorific}, ঢাকার ভেতরে আমাদের ডেলিভারি চার্জ ৮০ টাকা (80 Tk) এবং ঢাকার বাইরে ১৩০ টাকা (130 Tk)।"
                    else:
                        draft_reply = f"জি {honorific}, আমাদের ডেলিভারি চার্জ ঢাকার ভেতরে ৮০ টাকা (80 Tk) এবং ঢাকার বাইরে ১৩০ টাকা (130 Tk)।"

                if CustomerIntent.PRICE_INQUIRY in all_intents or entities.get("package_id"):
                    selected_tools.append("pricing_engine")
                    p_num = entities.get("package_id") or 7
                    p_info = calculate_package_price(package_id=p_num, quantity=effective_qty or 100)
                    p_price = int(p_info["effective_unit_price"])
                    draft_reply = f"জি {honorific}, আপনার {effective_qty or 100} পিস অর্ডারের জন্য প্যাকেজ {p_num}-এর রেগুলার রেট প্রতি সেট {p_price} টাকা (91 Tk)। {draft_reply}"

                response_source = "delivery_inquiry_response"

            # Q. ADVANCE & COD POLICY
            elif primary_intent in (CustomerIntent.ADVANCE_INQUIRY, CustomerIntent.COD_INQUIRY, CustomerIntent.PAYMENT_INQUIRY):
                selected_tools.append("pricing_engine")
                draft_reply = f"জি {honorific}, অর্ডার কনফার্ম করতে ৫০% অগ্রিম পেমেন্ট করতে হয় (অগ্রিম পেমেন্ট বাধ্যতামূলক)। বাকি টাকা প্রোডাক্ট হাতে পেয়ে ক্যাশ অন ডেলিভারিতে দিতে পারবেন (ফুল ক্যাশ অন ডেলিভারি প্রযোজ্য নয়)।"
                response_source = "advance_payment_policy"

            # R. GENERAL PRODUCT INQUIRY ("আইডি কার্ড বানাবো")
            elif primary_intent == CustomerIntent.PRODUCT_INQUIRY:
                selected_tools.append("pricing_engine")
                if effective_qty is not None and effective_qty >= 30:
                    draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য অবশ্যই করতে পারব। আমাদের স্যাম্পলগুলো পাঠাবো কি?"
                else:
                    draft_reply = f"জি {honorific}, অবশ্যই। আপনি কত পিস আইডি কার্ড করতে চান এবং কার্ডের সঙ্গে ফিতা ও কভারও নিতে চান কি?"
                response_source = "product_inquiry_quantity_prompt"

            # S. UNKNOWN / KNOWLEDGE ENGINE RETRIEVAL / TEAM ESCALATION
            else:
                selected_tools.append("knowledge_engine")
                k_res = KnowledgeEngine.retrieve_relevant_knowledge(customer_message, workspace_id=ws_id)
                if k_res.get("has_authoritative_answer") and k_res.get("direct_answers"):
                    r_rule = k_res["direct_answers"][0]
                    draft_reply = f"জি {honorific}, {r_rule.get('response_or_rule', '')}"
                    response_source = "training_rule_answer"
                elif k_res.get("has_authoritative_answer") and k_res.get("matched_faqs"):
                    r_faq = k_res["matched_faqs"][0]
                    draft_reply = f"জি {honorific}, {r_faq.get('answer', '')}"
                    response_source = "faq_answer"
                else:
                    unk = KnowledgeEngine.handle_unknown_inquiry(
                        customer_message=customer_message,
                        sender_id=s_id,
                        detected_topic="unknown_inquiry",
                        workspace_id=ws_id,
                        customer_name=customer_name,
                        channel=channel
                    )
                    draft_reply = unk["reply_text"]
                    response_source = "no_guess_team_escalation"

            # -------------------------------------------------------------
            # STEP 5: UNIVERSAL RESPONSE VALIDATION & POLICY GUARD
            # -------------------------------------------------------------
            draft_payload = {
                "reply_text": draft_reply,
                "matched_images": matched_images,
                "media_sequence": media_sequence,
                "voice_url": voice_url,
                "video_url": video_url,
                "order_created": None,
                "response_source": response_source
            }

            try:
                validated_res = ResponseValidator.validate_and_sanitize(
                    draft_response=draft_payload,
                    customer_message=customer_message,
                    conversation_history=conversation_history,
                    sender_id=s_id,
                    customer_name=customer_name,
                    workspace_id=ws_id,
                    channel=channel
                )
            except Exception as val_err:
                print(f"[Orchestrator Validator Fallback]: {val_err}")
                validated_res = draft_payload

            validated_res["orchestrator_log"] = {
                "primary_intent": primary_intent,
                "intents": all_intents,
                "entities": entities,
                "selected_tools": selected_tools,
                "requires_owner_approval": requires_owner_approval,
                "response_source": response_source
            }

            return validated_res

        except Exception as top_err:
            print(f"[Orchestrator Top-Level Fallback Error]: {top_err}")
            return {
                "reply_text": f"জি {honorific}, আরএস গ্রাফিক্সে আপনাকে স্বাগতম। আপনি কত পিস আইডি কার্ড বানাতে চান জানাবেন প্লিজ? আমাদের হেল্পলাইন: 01816504097।",
                "matched_images": [],
                "media_sequence": [],
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "response_source": "top_level_safe_fallback",
                "orchestrator_log": {
                    "primary_intent": CustomerIntent.UNKNOWN,
                    "intents": [CustomerIntent.UNKNOWN],
                    "entities": {},
                    "selected_tools": ["safe_fallback"],
                    "requires_owner_approval": False,
                    "error": str(top_err)
                }
            }
