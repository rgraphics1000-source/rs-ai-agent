"""
Phase 9: Central Intelligent Conversation Engine & Master Orchestrator for RS Graphics AI Agent.

Architecture:
CUSTOMER MESSAGE
        ↓
MESSAGE NORMALIZATION
        ↓
CONVERSATION MEMORY LOAD
        ↓
CURRENT CONTEXT BUILD
        ↓
INTENT UNDERSTANDING (Contextual, Multi-turn, Affirmations, Topic-aware)
        ↓
ENTITY / TOPIC UNDERSTANDING
        ↓
CONTEXT + HISTORY REASONING
        ↓
KNOWLEDGE AVAILABILITY CHECK
        ↓
ACTION PLANNING
        ↓
AUTHORITATIVE BUSINESS ENGINE / TOOL (Pricing, MOQ, Delivery, Owner Approval, Form Resolver, Media Router)
        ↓
RESPONSE GENERATION (Dynamic Constrained Synthesis)
        ↓
RESPONSE RELEVANCE VALIDATION (Addresses intent, answers actual question, no repetition, no duplicate media)
        ↓
PERSIST MEMORY + ACTION + RESPONSE + STATE
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
from app.database import is_conversation_ai_active, get_db_connection


class CustomerIntent(str, Enum):
    GREETING = "GREETING"
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
        """
        raw_msg = (message or "").strip()
        norm_msg = raw_msg.lower()

        # Bengali digit normalizer
        bn_digits = {'০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4', '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'}
        digits_norm_msg = norm_msg
        for b, d in bn_digits.items():
            digits_norm_msg = digits_norm_msg.replace(b, d)

        intents: List[CustomerIntent] = []
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
        # Specific item pricing (detect first to protect model numbers like T-014 from quantity parsing)
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

            # Robust local regex fallback for quantity
            if entities["quantity"] is None:
                clean_for_qty = re.sub(r't-?\d+[a-z]?', '', digits_norm_msg, flags=re.IGNORECASE)
                m_q = re.search(r'(\d+)\s*(?:টা|টি|পিস|কার্ড|কপি|id\s*cards?|cards?|pieces?|pcs?|items?)', clean_for_qty)
                if not m_q:
                    m_q = re.search(r'(?:প্যাকেজ|package|pkg)\s*[১-৭1-7]\s*(\d+)', clean_for_qty)
                if not m_q:
                    m_q = re.search(r'\b(\d{2,4})\b', clean_for_qty)
                if m_q:
                    try:
                        entities["quantity"] = int(m_q.group(1))
                    except Exception:
                        pass

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

        is_query = any(q in norm_msg for q in ["কত", "দাম", "রেট", "কী", "কি", "কেমন", "কবে", "কোথায়", "কেন", "price", "cost"])
        affirmative_words = ["জি", "হ্যাঁ", "হুম", "hm", "yes", "jee", "ji", "আচ্ছা", "ঠিক আছে", "ok", "sure"]
        if not is_query and (norm_msg in affirmative_words or any(norm_msg == w or (len(norm_msg.split()) <= 3 and (norm_msg.startswith(w + " ") or norm_msg.endswith(" " + w))) for w in affirmative_words)):
            entities["is_affirmative"] = True

        if any(kw in norm_msg for kw in ["আবার পাঠান", "পুনরায় পাঠান", "আগের ছবিটা আবার", "ছবি আবার দিন", "আবার দেখান"]):
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
        # 3. MULTI-INTENT DETECTION
        # -------------------------------------------------------------
        # Identity Inquiries
        if any(kw in norm_msg for kw in ["তোমার নাম", "আপনার নাম", "who are you", "what is your name", "কার সাথে কথা"]):
            intents.append(CustomerIntent.AGENT_IDENTITY_INQUIRY)

        if any(kw in norm_msg for kw in ["ওনার", "মালিক", "owner", "বসের সাথে", "কথা বলব", "স্যার এর সাথে", "রাশেদ", "rashed"]):
            intents.append(CustomerIntent.OWNER_REQUEST)

        # Photo Service
        if any(kw in norm_msg for kw in [
            "ছবি কি আপনারা তুলে", "ছবি কি আপনারা তোলেন", "ছবি কি আপনারা তুলে দেন", "ছবি তুলে দেন", "ছবি কি তুলে দেন",
            "ছবি তোলার ব্যবস্থা", "ফটোগ্রাফার", "ছবি কি তুলবেন", "ছবি তুলে দেবেন", "ছবি তুলে দিবেন", "ছবি কি তোলেন", "ছবি তোলেন"
        ]) or ("ছবি" in norm_msg and any(kw in norm_msg for kw in ["তুলে দেন", "তুলে দিবেন", "তুলে দেবেন", "তোলার ব্যবস্থা", "তুলে নেন", "তোলেন কি"])):
            intents.append(CustomerIntent.PHOTO_SERVICE)
            entities["topic"] = "photo_service"

        # Topic Change / Mosque
        if "মসজিদ" in norm_msg and any(kw in norm_msg for kw in ["বানাবো না", "বানাব না", "লাগবে না", "লাগবে", "জন্য"]):
            intents.append(CustomerIntent.TOPIC_CHANGE)
            entities["topic"] = "mosque_requirement"
        elif any(k in norm_msg for k in ["বানাবো না", "বানাব না", "লাগবে না", "আইডি কার্ড না", "id card না"]) and any(k in norm_msg for k in ["ব্যানার", "মগ", "টি-শার্ট", "ভিজিটিং কার্ড", "ক্যালেন্ডার", "সিল"]):
            intents.append(CustomerIntent.TOPIC_CHANGE)
            entities["topic"] = "other_product_inquiry"

        # Google Form Correction Help / Media Request
        if any(kw in norm_msg for kw in ["তথ্য সংশোধন", "সংশোধনের নিয়ম", "সংশোধন করার নিয়ম", "সংশোধন করার ভিডিও", "সংশোধনের ভিডিও", "ফর্ম ভিডিও", "ভিডিও দেন", "ভিডিও দিন", "কীভাবে পূরণ", "ভিডিও", "সংশোধন"]):
            intents.append(CustomerIntent.GOOGLE_FORM_CORRECTION_HELP)
            intents.append(CustomerIntent.MEDIA_REQUEST)

        # Specific item pricing
        if entities["is_specific_item"]:
            intents.append(CustomerIntent.SPECIFIC_ITEM_PRICE)

        # MOQ rejection
        if entities["quantity"] is not None and entities["quantity"] < 30 and not entities["is_specific_item"]:
            intents.append(CustomerIntent.MOQ_REJECTED)

        # Resample request
        if entities["is_resample_request"]:
            intents.append(CustomerIntent.RESAMPLE_REQUEST)

        # Contextual Affirmation resolving
        if entities["is_affirmative"]:
            if pending_question == "SAMPLE_PERMISSION_PROMPT" or "স্যাম্পল পাঠাবো কি" in last_bot_msg or "স্যাম্পলগুলো পাঠাবো কি" in last_bot_msg:
                intents.append(CustomerIntent.SAMPLE_CONFIRMATION)
            elif pending_question == "PACKAGE_SELECTION_PROMPT" or "প্যাকেজটি পছন্দ" in last_bot_msg:
                intents.append(CustomerIntent.PACKAGE_SELECTION)
            elif pending_question == "QUANTITY_PROMPT" or "কত পিস" in last_bot_msg:
                intents.append(CustomerIntent.QUANTITY_INQUIRY)
            else:
                intents.append(CustomerIntent.SAMPLE_CONFIRMATION)

        # Explicit Sample Request
        if any(kw in norm_msg for kw in ["স্যাম্পল", "ছবি পাঠান", "ছবি দেন", "নমুনা পাঠান", "প্যাকেজের ছবি", "প্যাকেজ দেখতে চাই"]):
            intents.append(CustomerIntent.SAMPLE_REQUEST)

        # Price Inquiry vs Per Piece Rate vs Negotiation
        if any(kw in norm_msg for kw in [
            "প্রতি পিস কত", "প্রতি পিস কত টাকা", "প্রতি পিস কত রাখা যাবে", "দাম কত", "রেট কত",
            "কত টাকা", "খরচ কত", "মূল্য কত", "কত পড়বে", "কত পরবে", "হিসাব কত", "price", "cost",
            "প্যাকেজের দাম", "প্যাকেজের রেট", "প্যাকেজ কত", "প্যাকেজ মূল্য", "প্যাকেজগুলোর দাম"
        ]) or (pkg_match and any(kw in norm_msg for kw in ["কত", "দাম", "রেট", "মূল্য", "টাকা"])) or (pkg_match and not any(i in intents for i in (CustomerIntent.GREETING, CustomerIntent.TOPIC_CHANGE))):
            if any(kw in norm_msg for kw in ["প্রতি পিস", "per piece", "এক পিস", "প্রতিটি"]):
                intents.append(CustomerIntent.PER_PIECE_PRICE)
            else:
                intents.append(CustomerIntent.PRICE_INQUIRY)
        elif entities["package_id"] and any(kw in norm_msg for kw in ["এটা কত", "দাম কত", "রেট কত", "কত", "মূল্য"]):
            intents.append(CustomerIntent.PRICE_INQUIRY)

        if entities["is_negotiating"] or any(kw in norm_msg for kw in [
            "কম রাখা যায় না", "কম রাখবেন", "কম হবে না", "কম করা যাবে না", "কম করা যাবে না?", "কম হবে?",
            "কম রাখা যাবে", "কম রাখা যাবে কি", "কম রাখবেন কি", "কিছু কম", "একটু কম", "ডিসকাউন্ট দেন",
            "ডিসকাউন্ট", "ছাড় দেন", "ছাড় হবে", "কিছু কম রাখেন", "কিছু কম হবে", "সম্মান করবেন",
            "একটু কম রাখেন", "বেশি রাখছেন", "কমায় দেন", "অনুমতি দিয়েছে", "সম্মতি আছে"
        ]):
            intents.append(CustomerIntent.NEGOTIATION)
            entities["is_negotiating"] = True

        # Advance / COD
        if any(kw in norm_msg for kw in ["অগ্রিম", "এডভান্স", "advance", "ক্যাশ অন ডেলিভারি", "cod", "পেমেন্ট", "বিকাশ"]):
            intents.append(CustomerIntent.ADVANCE_INQUIRY)

        # Delivery Time
        if any(kw in norm_msg for kw in ["কবে পাব", "কয়দিন লাগবে", "কতদিন লাগবে", "ডেলিভারি সময়", "কত সময় লাগবে", "সময় কত"]):
            intents.append(CustomerIntent.DELIVERY_TIME_INQUIRY)

        # Delivery Fee
        if any(kw in norm_msg for kw in ["ডেলিভারি চার্জ", "কুরিয়ার চার্জ", "ডেলিভারি", "কুরিয়ার", "delivery"]):
            intents.append(CustomerIntent.DELIVERY_INQUIRY)

        # Greeting
        if any(kw in norm_msg for kw in ["সালাম", "salam", "assalam", "হাই", "হ্যালো", "hello", "hi"]):
            intents.append(CustomerIntent.GREETING)

        # Non-ID Card Products / Other Services
        non_id_products = ["ব্যানার", "মগ", "টি-শার্ট", "টি শার্ট", "ভিজিটিং কার্ড", "ক্যালেন্ডার", "সিল", "পোস্টার", "লিফলেট", "রশিদ", "ডোনেশন", "বই", "প্যাড", "ফ্লাইয়ার"]
        if any(p in norm_msg for p in non_id_products) and not any(kw in norm_msg for kw in ["আইডি কার্ড", "id card"]):
            intents.append(CustomerIntent.TOPIC_CHANGE)
            entities["topic"] = "non_id_product_inquiry"

        # General ID Card Product interest (without specific quantity or price keyword)
        if any(kw in norm_msg for kw in ["আইডি কার্ড", "id card", "কার্ড বানাবো", "কার্ড বানাতে", "কার্ড করতে চাই", "কার্ডের কাজ", "কার্ড লাগবে", "কার্ড তৈরি"]):
            if entities["quantity"] is None and not entities["package_id"] and not any(i in intents for i in (CustomerIntent.PRICE_INQUIRY, CustomerIntent.GREETING, CustomerIntent.TOPIC_CHANGE)):
                intents.append(CustomerIntent.PRODUCT_INQUIRY)

        # Quantity provided
        if entities["quantity"] is not None and entities["quantity"] >= 30 and not entities["is_specific_item"]:
            if not any(i in intents for i in (CustomerIntent.PRICE_INQUIRY, CustomerIntent.NEGOTIATION, CustomerIntent.DELIVERY_INQUIRY, CustomerIntent.GREETING, CustomerIntent.SAMPLE_REQUEST)):
                intents.append(CustomerIntent.QUANTITY_PROVIDED)

        # Deduplicate intents preserving order
        dedup_intents = []
        for it in intents:
            if it not in dedup_intents:
                dedup_intents.append(it)

        if not dedup_intents:
            dedup_intents.append(CustomerIntent.UNKNOWN)

        primary_intent = dedup_intents[0]

        return {
            "primary_intent": primary_intent,
            "intents": dedup_intents,
            "confidence": 0.95 if primary_intent != CustomerIntent.UNKNOWN else 0.40,
            "entities": entities
        }

    @classmethod
    def execute_decision(
        cls,
        customer_message: str,
        sender_id: Optional[str] = None,
        customer_name: str = "Customer",
        workspace_id: int = 1,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        channel: str = "facebook"
    ) -> Dict[str, Any]:
        """
        Executes central decision orchestration across authoritative tools and returns validated payload.
        """
        ws_id = int(workspace_id or 1)
        honorific = detect_customer_gender_title(customer_name)
        s_id = str(sender_id or "web_user").strip()

        try:
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
            # STEP 2: LOAD PERSISTENT CONVERSATION MEMORY & STATE
            # -------------------------------------------------------------
            conversation_state = {}
            memory = {}
            samples_already_sent = False
            try:
                conversation_state = get_structured_conversation_state(s_id, ws_id)
                memory = get_conversation_memory(s_id, ws_id)
                samples_already_sent = is_media_already_sent(s_id, "samples", ws_id)
            except Exception as db_err:
                print(f"[Orchestrator DB State Warning]: {db_err}")

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
            # STEP 4: IDENTITY & NO-GUESS KNOWLEDGE SHORT-CIRCUITS
            # -------------------------------------------------------------
            # A. Identity Inquiries (Agent Name: নাদিম, Owner Name: Escalation)
            identity_res = KnowledgeEngine.check_identity_inquiry(
                message=customer_message,
                customer_name=customer_name,
                workspace_id=ws_id,
                sender_id=s_id
            )
            if identity_res and identity_res.get("is_handled"):
                draft_reply = identity_res["reply_text"]
                response_source = identity_res.get("response_source", "knowledge_engine")
                selected_tools.append("knowledge_engine")

            # B. Media Request / Google Form Video Help
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

            # C. Topic Change & Non-ID Card Inquiries
            elif primary_intent == CustomerIntent.PHOTO_SERVICE:
                selected_tools.append("knowledge_engine")
                draft_reply = (
                    f"জি {honorific}, আমরা ছবি তোলার সার্ভিস প্রদান করি না। ছবি ও তথ্য আপনাকেই তুলে দিতে হবে। "
                    f"আমরা সম্পূর্ণ কাজ তৈরি করে, প্রিমিয়াম প্রিন্ট ও ডেলিভারি সম্পন্ন করে দেব।"
                )
                response_source = "photo_service_policy"

            elif primary_intent == CustomerIntent.TOPIC_CHANGE:
                selected_tools.append("knowledge_engine")
                if entities.get("topic") == "mosque_requirement":
                    draft_reply = f"জি {honorific}, আপনার মসজিদের কী ধরণের কাজ প্রয়োজন জানাবেন প্লিজ (যেমন: আইডি কার্ড, ডোনেশন রশিদ, ব্যানার বা সিল)? আমরা আপনার প্রয়োজন অনুযায়ী সহায়তা করতে পারব।"
                    response_source = "topic_switch_clarification"
                else:
                    k_res = KnowledgeEngine.retrieve_relevant_knowledge(customer_message, workspace_id=ws_id)
                    if k_res.get("has_authoritative_answer") and k_res.get("matched_rules"):
                        r_rule = k_res["matched_rules"][0]
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

            # -------------------------------------------------------------
            # STEP 5: MOQ POLICY (< 30 pieces)
            # -------------------------------------------------------------
            elif primary_intent == CustomerIntent.MOQ_REJECTED or (effective_qty is not None and effective_qty < 30 and not entities.get("is_specific_item")):
                selected_tools.append("pricing_engine")
                draft_reply = f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"
                response_source = "moq_rejected_policy"

            # -------------------------------------------------------------
            # STEP 6: SAMPLE DELIVERY & DUPLICATION PROTECTION
            # -------------------------------------------------------------
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

                    v_url = "/static/uploads/package/PTT-20260119-WA0105.mp3" if (effective_qty is not None and effective_qty >= 80) else ""
                    draft_reply = f"জি {honorific}, অবশ্যই দিচ্ছি।"
                    matched_images = matched_imgs
                    media_sequence = seq
                    voice_url = v_url
                    response_source = "sample_dispatch_pipeline"

            # -------------------------------------------------------------
            # STEP 7: GENERAL PRODUCT INQUIRY (Asks for quantity before price)
            # -------------------------------------------------------------
            elif primary_intent == CustomerIntent.PRODUCT_INQUIRY:
                selected_tools.append("pricing_engine")
                try:
                    record_question_asked(s_id, "QUANTITY_PROMPT", ws_id)
                except Exception:
                    pass
                draft_reply = f"জি {honorific}, অবশ্যই। আপনি কত পিস আইডি কার্ড করতে চান এবং কার্ডের সঙ্গে ফিতা ও কভারও নিতে চান কি?"
                response_source = "product_inquiry_quantity_prompt"

            # -------------------------------------------------------------
            # STEP 8: QUANTITY PROVIDED & TIER ACKNOWLEDGMENT
            # -------------------------------------------------------------
            elif primary_intent == CustomerIntent.QUANTITY_PROVIDED:
                selected_tools.append("pricing_engine")
                try:
                    record_fact_confirmed(s_id, "quantity", effective_qty, ws_id)
                except Exception:
                    pass

                if not samples_already_sent:
                    try:
                        record_question_asked(s_id, "SAMPLE_PERMISSION_PROMPT", ws_id)
                    except Exception:
                        pass
                    if effective_qty < 50:
                        draft_reply = f"জি {honorific}, ৩০-৪৯ পিস অর্ডারের জন্য প্যাকেজ ১ এর রেট প্রতি সেট ৮০ টাকা (80 Tk) থেকে শুরু (যেহেতু ৫০ পিসের কম, তাই প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য)। আমাদের স্যাম্পলগুলো পাঠাবো কি?"
                    else:
                        draft_reply = f"জি {honorific}, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"
                    response_source = "sample_permission_prompt"
                else:
                    try:
                        record_question_asked(s_id, "PACKAGE_SELECTION_PROMPT", ws_id)
                    except Exception:
                        pass
                    if effective_qty >= 80:
                        tier_note = "আমাদের প্যাকেজ রেগুলার রেট প্রযোজ্য হবে"
                    elif effective_qty >= 50:
                        tier_note = "ফিক্সড রেগুলার প্যাকেজ রেট প্রযোজ্য হবে"
                    else:
                        tier_note = "(৩০-৪৯ পিস টিয়ারে) রেগুলার রেটের চেয়ে প্রতি সেটে ১০ টাকা বেশি হবে (প্যাকেজ ১ ৮০ টাকা / 80 Tk)"
                    draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য {tier_note}। কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                    response_source = "quantity_updated_tier_ack"

            # -------------------------------------------------------------
            # STEP 9: PRICING, PER-PIECE RATES & NEGOTIATION
            # -------------------------------------------------------------
            elif any(i in all_intents for i in (CustomerIntent.PRICE_INQUIRY, CustomerIntent.PER_PIECE_PRICE, CustomerIntent.SPECIFIC_ITEM_PRICE, CustomerIntent.NEGOTIATION)):
                selected_tools.append("pricing_engine")
                if CustomerIntent.DELIVERY_INQUIRY in all_intents:
                    selected_tools.append("delivery_calculator")

                # Specific item pricing
                if entities.get("is_specific_item"):
                    msg_l = customer_message.lower()
                    if "t-014" in msg_l or "t014" in msg_l:
                        draft_reply = f"জি {honorific}, এটি আমাদের T-014V সফট কভার। এর রেগুলার মূল্য প্রতি পিস ১০ টাকা।"
                    elif "dx" in msg_l:
                        draft_reply = f"জি {honorific}, এটি আমাদের DX কভার। এর রেগুলার মূল্য প্রতি পিস ১২ টাকা।"
                    elif "t-065" in msg_l or "t065" in msg_l:
                        draft_reply = f"জি {honorific}, এটি আমাদের T-065V সফট কভার। এর রেগুলার মূল্য প্রতি পিস ১৪ টাকা।"
                    elif "t-994" in msg_l or "t994" in msg_l:
                        draft_reply = f"জি {honorific}, এটি আমাদের T-994V হার্ড কভার। এর রেগুলার মূল্য প্রতি পিস ২০ টাকা।"
                    elif "reap" in msg_l:
                        draft_reply = f"জি {honorific}, এটি আমাদের REAP হার্ড কভার। এর রেগুলার মূল্য প্রতি পিস ২০ টাকা।"
                    elif "শুধু কার্ড" in msg_l:
                        draft_reply = f"জি {honorific}, শুধু প্রিমিয়াম UV কার্ড প্রতি পিস ৩৫ টাকা (১০০+ পিসের ক্ষেত্রে)।"
                    elif "শুধু ফিতা" in msg_l:
                        draft_reply = f"জি {honorific}, শুধু ফিতা: ১.৫ সেমি ২৫ টাকা এবং ২ সেমি ২৮ টাকা প্রতি পিস।"
                    else:
                        draft_reply = f"জি {honorific}, আমাদের নির্দিষ্ট কভার ও ফিতার মূল্য তালিকা উপরে দেওয়া রয়েছে।"
                    response_source = "specific_item_pricing"

                # Negotiation
                elif primary_intent == CustomerIntent.NEGOTIATION or entities.get("is_negotiating"):
                    current_disc = float(conversation_state.get("discount_amount") or 0.0) if conversation_state else 0.0
                    dem_price = entities.get("demanded_price")
                    pkg_id = entities.get("package_id") or "7"
                    neg_qty = effective_qty if effective_qty is not None else 100

                    neg_res = negotiate_step(
                        package_id=pkg_id,
                        quantity=neg_qty,
                        current_discount=current_disc,
                        customer_demanded_price=dem_price
                    )

                    if neg_res.get("requires_owner_approval"):
                        requires_owner_approval = True

                    if sender_id and not neg_res.get("requires_owner_approval") and neg_res.get("offered_discount", 0.0) > 0:
                        try:
                            update_conversation_state(
                                sender_id=s_id,
                                updates={
                                    "discount_amount": neg_res["offered_discount"],
                                    "quoted_price": neg_res["offered_unit_price"]
                                },
                                reason="negotiation_step_applied",
                                workspace_id=ws_id
                            )
                        except Exception:
                            pass

                    draft_reply = neg_res["reply_text"]
                    response_source = "discount_negotiation_response"

                # Specific Single Package Rate Inquiry (Package is explicitly identified)
                elif entities.get("package_id"):
                    p_id = entities.get("package_id")
                    p_qty = effective_qty if effective_qty is not None else 100
                    p_calc = calculate_package_price(package_id=p_id, quantity=p_qty)
                    u_p = int(p_calc.get("effective_unit_price") or p_calc.get("upfront_unit_price") or p_calc.get("regular_price") or 70)
                    pkg_name = PACKAGE_CATALOG.get(p_id, {}).get("name_bn", f"প্যাকেজ {p_id}")

                    if effective_qty is None:
                        try:
                            record_question_asked(s_id, "QUANTITY_PROMPT", ws_id)
                        except Exception:
                            pass
                        draft_reply = (
                            f"জি {honorific}, প্যাকেজ {p_id} এর রেগুলার রেট প্রতি সেট {u_p} (91) টাকা (১০০+ পিসের ক্ষেত্রে)। "
                            f"আপনার কত পিস প্রয়োজন জানালে আপনার জন্য প্রযোজ্য সঠিক রেট বলতে পারব {honorific}।"
                        )
                    else:
                        if effective_qty < 50:
                            draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (যেহেতু ৫০ পিসের কম, তাই প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য) প্যাকেজ {p_id} ({pkg_name}) এর রেট প্রতি সেট {u_p} টাকা ({u_p} Tk)।"
                        elif effective_qty < 80:
                            draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজ {p_id} ({pkg_name}) এর ফিক্সড রেগুলার মূল্য প্রতি সেট {u_p} টাকা ({u_p} Tk)।"
                        else:
                            draft_reply = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজ {p_id} ({pkg_name}) এর রেগুলার মূল্য প্রতি সেট {u_p} টাকা ({u_p} Tk)।"
                    response_source = "single_package_price_prompt"

                # General Price Inquiry / Per Piece Rate: Answer directly based on verified tier
                else:
                    p_qty = effective_qty if effective_qty is not None else 100
                    p_calc = calculate_package_price(package_id="7", quantity=p_qty)

                    if effective_qty is not None and effective_qty >= 30:
                        if effective_qty < 50:
                            draft_reply = (
                                f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (যেহেতু ৫০ পিসের কম, তাই প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য) প্রতিটি প্যাকেজের রেট নিচে দেওয়া হলো:\n\n"
                                f"• প্যাকেজ ১: ৮০ টাকা (80 Tk) (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                                f"• প্যাকেজ ২: ৮০ টাকা (80 Tk) (কার্ড + ফিতা + ডিএক্স কভার)\n"
                                f"• প্যাকেজ ৩: ৮৩ টাকা (83 Tk) (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                                f"• প্যাকেজ ৪: ৮৩ টাকা (83 Tk) (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                                f"• প্যাকেজ ৫: ৯৩ টাকা (93 Tk) (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                                f"• প্যাকেজ ৬: ৯৩ টাকা (93 Tk) (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                                f"• প্যাকেজ ৭: ১০১ টাকা (101 Tk) (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                                f"(নোট: ৩০-৪৯ পিস অর্ডারের ক্ষেত্রে ফিক্সড রেট প্রযোজ্য, কোনো ডিসকাউন্ট প্রযোজ্য নয়।)\n\n"
                                f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                            )
                        elif effective_qty < 80:
                            draft_reply = (
                                f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্রতিটি প্যাকেজের ফিক্সড রেগুলার মূল্য নিচে দেওয়া হলো:\n\n"
                                f"• প্যাকেজ ১: ৭০ টাকা (70 Tk) (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                                f"• প্যাকেজ ২: ৭০ টাকা (70 Tk) (কার্ড + ফিতা + ডিএক্স কভার)\n"
                                f"• প্যাকেজ ৩: ৭৩ টাকা (73 Tk) (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                                f"• প্যাকেজ ৪: ৭৩ টাকা (73 Tk) (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                                f"• প্যাকেজ ৫: ৮৩ টাকা (83 Tk) (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                                f"• প্যাকেজ ৬: ৮৩ টাকা (83 Tk) (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                                f"• প্যাকেজ ৭: ৯১ টাকা (91 Tk) (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                                f"(নোট: ৫০-৭৯ পিস অর্ডারের ক্ষেত্রে ফিক্সড রেগুলার রেট প্রযোজ্য, কোনো ডিসকাউন্ট প্রযোজ্য নয়।)\n\n"
                                f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                            )
                        else:
                            draft_reply = (
                                f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্রতিটি প্যাকেজের রেগুলার মূল্য নিচে দেওয়া হলো:\n\n"
                                f"• প্যাকেজ ১: ৭০ টাকা (70 Tk) (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                                f"• প্যাকেজ ২: ৭০ টাকা (70 Tk) (কার্ড + ফিতা + ডিএক্স কভার)\n"
                                f"• প্যাকেজ ৩: ৭৩ টাকা (73 Tk) (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                                f"• প্যাকেজ ৪: ৭৩ টাকা (73 Tk) (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                                f"• প্যাকেজ ৫: ৮৩ টাকা (83 Tk) (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                                f"• প্যাকেজ ৬: ৮৩ টাকা (83 Tk) (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                                f"• প্যাকেজ ৭: ৯১ টাকা (91 Tk) (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                                f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                            )
                    else:
                        try:
                            record_question_asked(s_id, "QUANTITY_PROMPT", ws_id)
                        except Exception:
                            pass
                        draft_reply = (
                            f"জি {honorific}, আমাদের আইডি কার্ডের প্যাকেজ রেট প্রতি সেট ৭০ টাকা থেকে ৯১ টাকা (70-91 Tk) পর্যন্ত রয়েছে "
                            f"(সর্বনিম্ন ৩০ পিস)। আপনার কত পিস প্রয়োজন জানালে আপনার জন্য প্রযোজ্য সঠিক রেট বলতে পারব {honorific}।"
                        )
                    response_source = "id_card_package_pricing_breakdown"

                    # If delivery was also asked, append delivery details
                    if CustomerIntent.DELIVERY_INQUIRY in all_intents:
                        draft_reply += f"\n\nডেলিভারি চার্জ: ঢাকার ভেতরে ৮০ টাকা এবং ঢাকার বাইরে ১৩০ টাকা।"

            # -------------------------------------------------------------
            # STEP 10: DELIVERY & ADVANCE PAYMENT INQUIRIES
            # -------------------------------------------------------------
            elif primary_intent == CustomerIntent.DELIVERY_TIME_INQUIRY:
                selected_tools.append("delivery_calculator")
                draft_reply = f"জি {honorific}, তথ্য দেওয়ার পর কাজ ও ডিজাইন করতে ৫-৬ দিন সময় লাগবে। প্রুফ অনুমোদনের পর প্রিন্ট করে ২৪-৪৮ ঘণ্টার মধ্যে কুরিয়ারে ডেলিভারি পেয়ে যাবেন ইনশাআল্লাহ।"
                response_source = "delivery_timeline_response"

            elif primary_intent == CustomerIntent.DELIVERY_INQUIRY:
                selected_tools.append("delivery_calculator")
                draft_reply = f"জি {honorific}, ডেলিভারি চার্জ ঢাকার ভেতরে ৮০ টাকা এবং ঢাকার বাইরে ১৩০ টাকা (প্রতি কেজিতে ২০ টাকা এবং প্রতি হাজারে ১০ টাকা COD চার্জ প্রযোজ্য)।"
                response_source = "delivery_fee_response"

            elif primary_intent == CustomerIntent.ADVANCE_INQUIRY:
                selected_tools.append("pricing_engine")
                draft_reply = f"জি {honorific}, আমাদের পণ্যগুলো কাস্টমাইজড হওয়ায় ফুল ক্যাশ অন ডেলিভারি প্রযোজ্য নয়। অর্ডার কনফার্ম করতে কাজের শুরুতে ডেলিভারি চার্জ বা আংশিক অগ্রিম পেমেন্ট বাধ্যতামূলক, বাকি টাকা ডেলিভারির সময় পরিশোধযোগ্য।"
                response_source = "advance_payment_policy"

            # -------------------------------------------------------------
            # STEP 11: GREETING & GENERAL SAFE INTENT
            # -------------------------------------------------------------
            elif primary_intent == CustomerIntent.GREETING:
                if effective_qty is not None and effective_qty >= 30:
                    draft_reply = f"ওয়ালাইকুমুস সালাম {honorific}! আরএস গ্রাফিক্সে আপনাকে স্বাগতম। আপনার {effective_qty} পিস আইডি কার্ডের অর্ডারের জন্য কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ?"
                else:
                    draft_reply = f"ওয়ালাইকুমুস সালাম {honorific}! আরএস গ্রাফিক্সে আপনাকে স্বাগতম। আপনি কত পিস ID Card করতে চান এবং কার্ডের সঙ্গে ফিতা ও কভারও নিতে চান কি?"
                response_source = "standard_greeting"

            # -------------------------------------------------------------
            # STEP 12: UNKNOWN INQUIRY / NO-GUESS BOUNDARY
            # -------------------------------------------------------------
            else:
                selected_tools.append("knowledge_engine")
                unk = KnowledgeEngine.handle_unknown_inquiry(
                    customer_message=customer_message,
                    sender_id=s_id,
                    detected_topic="unresolved_inquiry",
                    workspace_id=ws_id,
                    customer_name=customer_name,
                    channel=channel
                )
                draft_reply = unk["reply_text"]
                response_source = "no_guess_team_escalation"

            # -------------------------------------------------------------
            # STEP 13: UNIVERSAL RESPONSE VALIDATION & POLICY GUARD
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
