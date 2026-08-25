"""
Phase 6.0: Master Brain Orchestrator for RS Graphics AI Agent.

Architecture:
Customer Message
      ↓
Conversation State (Persistent SQLite State Machine)
      ↓
Intent & Entity Detection (Structured Intent Object)
      ↓
Master Orchestrator
      ↓
Decision & Tool Selection (Structured Decision Object)
      ↓
Authoritative Business Tools (Pricing Engine, Media Router, Product Catalog, Form Resolver)
      ↓
Controlled Language Synthesis / Verified Response
      ↓
Response Validator & Policy Guard
      ↓
Outbound Dispatch

Authoritative Hierarchy:
LEVEL 1 — HARD BUSINESS RULES (Pricing Engine, State Machine, Policy Guard)
LEVEL 2 — VERIFIED DATABASE DATA (Products, Saved Media, FAQs, Training Rules)
LEVEL 3 — CUSTOMER CONVERSATION CONTEXT (History, Customer Name, Sender ID)
LEVEL 4 — GEMINI GENERATION (Language formatting only)
"""

import re
import time
from enum import Enum
from typing import Dict, Any, List, Optional

from app.ai_agent.conversation_state import (
    SalesStage, get_structured_conversation_state, update_conversation_state
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
from app.database import (
    is_conversation_ai_active, get_saved_media, get_db_connection
)
from app.ai_agent.rule_registry import (
    RuleRegistry, AuthorityLevel, ConflictAction, ConflictType
)


class CustomerIntent(str, Enum):
    SERVICE_INQUIRY = "SERVICE_INQUIRY"
    QUANTITY_INQUIRY = "QUANTITY_INQUIRY"
    PRICE_INQUIRY = "PRICE_INQUIRY"
    PACKAGE_INQUIRY = "PACKAGE_INQUIRY"
    PRODUCT_INQUIRY = "PRODUCT_INQUIRY"
    SAMPLE_REQUEST = "SAMPLE_REQUEST"
    GOOGLE_FORM_SUBMISSION_HELP = "GOOGLE_FORM_SUBMISSION_HELP"
    GOOGLE_FORM_CORRECTION_HELP = "GOOGLE_FORM_CORRECTION_HELP"
    CARD_FEATURES = "CARD_FEATURES"
    RIBBON_FEATURES = "RIBBON_FEATURES"
    COVER_FEATURES = "COVER_FEATURES"
    DELIVERY_INQUIRY = "DELIVERY_INQUIRY"
    DELIVERY_TIME_INQUIRY = "DELIVERY_TIME_INQUIRY"
    PAYMENT_INQUIRY = "PAYMENT_INQUIRY"
    ADVANCE_INQUIRY = "ADVANCE_INQUIRY"
    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"
    NEGOTIATION = "NEGOTIATION"
    OWNER_REQUEST = "OWNER_REQUEST"
    GREETING = "GREETING"
    MOQ_REJECTED = "MOQ_REJECTED"
    UNKNOWN = "UNKNOWN"


class MasterOrchestrator:
    """
    Master Brain Orchestrator coordinating all deterministic business engines,
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
        Extracts structured intent and entities from customer message.
        """
        raw_msg = (message or "").strip()
        norm_msg = raw_msg.lower()

        # Bengali digit normalizer
        bn_digits = {'০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4', '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'}
        digits_norm_msg = norm_msg
        for b, d in bn_digits.items():
            digits_norm_msg = digits_norm_msg.replace(b, d)

        intents = []
        entities: Dict[str, Any] = {
            "quantity": None,
            "package_id": None,
            "demanded_price": None,
            "location": None,
            "is_negotiating": False
        }

        # 1. Entity: Quantity extraction
        # Use battle-tested safe quantity extractor from gemini_brain if available
        try:
            from app.ai_agent.gemini_brain import extract_order_quantity_number
            extracted_q = extract_order_quantity_number(raw_msg)
            if extracted_q:
                entities["quantity"] = extracted_q
        except Exception:
            pass

        if entities["quantity"] is None:
            q_match = re.search(r'(\d{1,5})\s*(?:পিস|pcs|টা|টি|কপি|বানাবো|cards?|id\s*cards?)', digits_norm_msg)
            if q_match:
                try:
                    entities["quantity"] = int(q_match.group(1))
                except Exception:
                    pass

        # If quantity not in current message, inherit from saved conversation state
        if entities["quantity"] is None and conversation_state:
            entities["quantity"] = conversation_state.get("quantity")

        # 2. Entity: Package ID extraction
        pkg_match = re.search(r'(?:প্যাকেজ|package|pkg)\s*([১-৭1-7])', norm_msg)
        if pkg_match:
            entities["package_id"] = normalize_package_id(pkg_match.group(1))
        elif conversation_state and conversation_state.get("package_id"):
            entities["package_id"] = conversation_state.get("package_id")

        # 3. Entity: Demanded Price extraction (e.g. '৮০ টাকা করে দেন', '75 tk rakhen', '৮০ টাকা হবে?')
        dem_match = re.search(r'(\d{2,4})\s*(?:টাকা|টাকায়|টাকাতে|tk|taka|৳)\s*(?:করে\s*)?(?:রাখ|দেন|দিবেন|হবে|নেব|রাখবেন|করেন|কইরেন|হবেনা)?', digits_norm_msg)
        if dem_match:
            try:
                p_val = float(dem_match.group(1))
                # Check if it's a price inquiry vs negotiation vs package id
                if p_val not in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]:
                    if any(kw in norm_msg for kw in ["রাখ", "দেন", "দিবেন", "হবে", "নেব", "রাখবেন", "করেন", "কইরেন", "সম্মতি", "অনুমতি", "কমান", "ছাড়"]):
                        entities["demanded_price"] = p_val
                        entities["is_negotiating"] = True
            except Exception:
                pass

        # 4. Entity: Location (inside vs outside Dhaka)
        if any(kw in norm_msg for kw in ["ঢাকা", "ঢাকার ভেতরে", "মিরপুর", "ধানমন্ডি", "উত্তরা", "গুলশান", "inside dhaka"]):
            entities["location"] = "inside_dhaka"
        elif any(kw in norm_msg for kw in ["ঢাকার বাইরে", "চট্টগ্রাম", "সিলেট", "রাজশাহী", "খুলনা", "বরিশাল", "রংপুর", "outside dhaka", "গ্রাম"]):
            entities["location"] = "outside_dhaka"

        # -------------------------------------------------------------
        # Intent Classification
        # -------------------------------------------------------------
        # Greeting Intent
        if any(kw in norm_msg for kw in ["সালাম", "salam", "assalam", "হাই", "হ্যালো", "hello", "hi"]):
            intents.append(CustomerIntent.GREETING)

        # MOQ Check
        if entities["quantity"] is not None and entities["quantity"] < 30:
            intents.append(CustomerIntent.MOQ_REJECTED)

        # Negotiation Intent
        if entities["demanded_price"] is not None or any(kw in norm_msg for kw in [
            "কম রাখা যায় না", "কম রাখবেন", "কম হবে না", "ডিসকাউন্ট দেন", "ছাড় দেন", "কিছু কম রাখেন",
            "কিছু কম হবে", "সম্মান করবেন", "একটু কম রাখেন", "বেশি রাখছেন", "কমায় দেন", "অনুমতি দিয়েছে", "সম্মতি আছে"
        ]):
            intents.append(CustomerIntent.NEGOTIATION)
            entities["is_negotiating"] = True

        # Owner Request Intent
        if any(kw in norm_msg for kw in ["ওনার", "মালিক", "owner", "বসের সাথে", "কথা বলব", "স্যার এর সাথে", "রাশেদ", "rashed"]):
            intents.append(CustomerIntent.OWNER_REQUEST)

        # Price Inquiry Intent
        if any(kw in norm_msg for kw in ["দাম কত", "রেট কত", "কত টাকা", "খরচ কত", "price", "cost", "মূল্য কত", "কত পড়বে", "কত পরবে", "হিসাব কত"]) or re.search(r'(?:প্যাকেজ|package|pkg)\s*[১-৭1-7]\s*(?:কত|দাম|রেট|মূল্য)', norm_msg):
            intents.append(CustomerIntent.PRICE_INQUIRY)

        # Package Inquiry Intent
        if any(kw in norm_msg for kw in ["প্যাকেজ", "package", "কম্বো", "combo"]) and CustomerIntent.PRICE_INQUIRY not in intents:
            intents.append(CustomerIntent.PACKAGE_INQUIRY)

        # Delivery & Delivery Time Intent
        if any(kw in norm_msg for kw in ["কবে পাব", "কয়দিন লাগবে", "কতদিন লাগবে", "ডেলিভারি সময়", "কত সময় লাগবে"]):
            intents.append(CustomerIntent.DELIVERY_TIME_INQUIRY)
        elif any(kw in norm_msg for kw in ["ডেলিভারি", "কুরিয়ার", "delivery", "হোম ডেলিভারি", "কুরিয়ার চার্জ"]):
            intents.append(CustomerIntent.DELIVERY_INQUIRY)

        # Advance / Payment Intent
        if any(kw in norm_msg for kw in ["অগ্রিম", "এডভান্স", "advance", "ক্যাশ অন ডেলিভারি", "cod", "পেমেন্ট"]):
            intents.append(CustomerIntent.ADVANCE_INQUIRY)

        # Sample Request Intent
        if any(kw in norm_msg for kw in ["স্যাম্পল", "ছবি", "নমুনা", "sample", "photo", "picture", "ছবি পাঠান"]):
            intents.append(CustomerIntent.SAMPLE_REQUEST)

        # Media Intents (Routing to MediaRouter)
        media_intent_res = MediaRouter.classify_media_intent(raw_msg, conversation_history, conversation_state)
        if media_intent_res["intent"] == MediaIntent.GOOGLE_FORM_CORRECTION_HELP:
            intents.append(CustomerIntent.GOOGLE_FORM_CORRECTION_HELP)
        elif media_intent_res["intent"] == MediaIntent.GOOGLE_FORM_SUBMISSION_HELP:
            intents.append(CustomerIntent.GOOGLE_FORM_SUBMISSION_HELP)
        elif media_intent_res["intent"] == MediaIntent.CARD_FEATURES:
            intents.append(CustomerIntent.CARD_FEATURES)
        elif media_intent_res["intent"] == MediaIntent.RIBBON_FEATURES:
            intents.append(CustomerIntent.RIBBON_FEATURES)
        elif media_intent_res["intent"] == MediaIntent.COVER_FEATURES:
            intents.append(CustomerIntent.COVER_FEATURES)

        # General Product / Quantity Inquiry
        if entities["quantity"] is not None and not intents:
            intents.append(CustomerIntent.QUANTITY_INQUIRY)
        elif not intents:
            intents.append(CustomerIntent.UNKNOWN)

        primary_intent = intents[0] if intents else CustomerIntent.UNKNOWN

        return {
            "primary_intent": primary_intent,
            "intents": intents,
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
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Executes decision orchestration across authoritative tools and generates validated response payload.
        """
        ws_id = int(workspace_id or 1)
        honorific = detect_customer_gender_title(customer_name)
        start_time = time.time()

        # -------------------------------------------------------------
        # STEP 1: HUMAN / ADMIN TAKEOVER CHECK (Absolute Silence Guard)
        # -------------------------------------------------------------
        if sender_id and not is_conversation_ai_active(sender_id=str(sender_id), workspace_id=ws_id):
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
                "orchestrator_log": {
                    "sender_id": sender_id,
                    "workspace_id": ws_id,
                    "status": "blocked_by_human_takeover",
                    "requires_owner_approval": False
                }
            }

        # -------------------------------------------------------------
        # STEP 2: LOAD PERSISTENT CONVERSATION STATE
        # -------------------------------------------------------------
        conversation_state = {}
        if sender_id:
            try:
                conversation_state = get_structured_conversation_state(str(sender_id), ws_id)
            except Exception:
                pass

        # -------------------------------------------------------------
        # STEP 3: INTENT & ENTITY DETECTION
        # -------------------------------------------------------------
        try:
            intent_data = cls.detect_intents_and_entities(
                message=customer_message,
                conversation_history=conversation_history,
                conversation_state=conversation_state
            )
        except Exception as e:
            intent_data = {
                "primary_intent": CustomerIntent.UNKNOWN,
                "intents": [CustomerIntent.UNKNOWN],
                "confidence": 0.4,
                "entities": {"quantity": None, "package_id": None, "demanded_price": None, "location": None, "is_negotiating": False}
            }
        intents = intent_data["intents"]
        entities = intent_data["entities"]
        selected_tools = []
        verified_context: Dict[str, Any] = {}
        requires_owner_approval = False
        owner_approval_reason = ""

        # -------------------------------------------------------------
        # STEP 4: AUTHORITATIVE TOOL EXECUTION
        # -------------------------------------------------------------
        # A. PRICING & NEGOTIATION TOOL
        if entities.get("quantity") is not None or entities.get("package_id") is not None or CustomerIntent.NEGOTIATION in intents:
            selected_tools.append("pricing_engine")
            pkg_id = entities.get("package_id") or "1"
            qty = entities.get("quantity") or 100

            # Check if customer has an existing approved/modified exception
            approved_exception = None
            if sender_id:
                from app.ai_agent.owner_approval import OwnerApprovalEngine, ApprovalRequestType
                approved_exception = OwnerApprovalEngine.get_active_approved_exception(
                    customer_id=str(sender_id),
                    workspace_id=ws_id,
                    package_id=str(pkg_id),
                    quantity=int(qty)
                )

            if approved_exception:
                # Use owner-approved price exception
                appr_val = float(approved_exception["approved_value"])
                verified_context["pricing"] = {
                    "package_id": str(pkg_id),
                    "quantity": int(qty),
                    "upfront_unit_price": appr_val,
                    "offered_unit_price": appr_val,
                    "total_amount": appr_val * int(qty),
                    "is_approved_exception": True,
                    "approved_by": approved_exception.get("resolved_by", "owner")
                }
            elif CustomerIntent.NEGOTIATION in intents:
                current_disc = float(conversation_state.get("applied_discount") or 0.0)
                dem_price = entities.get("demanded_price")
                neg_res = negotiate_step(
                    package_id=str(pkg_id),
                    quantity=int(qty),
                    current_discount=current_disc,
                    customer_demanded_price=dem_price
                )
                verified_context["pricing"] = neg_res
                if neg_res.get("requires_owner_approval"):
                    requires_owner_approval = True
                    owner_approval_reason = "Customer requested price below minimum authorized floor"
                    if sender_id:
                        from app.ai_agent.owner_approval import OwnerApprovalEngine, ApprovalRequestType
                        pkg_floor = PACKAGE_CATALOG.get(str(pkg_id), {}).get("min_price", 82.0)
                        OwnerApprovalEngine.create_or_get_pending_approval(
                            customer_id=str(sender_id),
                            conversation_id=str(conversation_state.get("conversation_id") or f"conv_{ws_id}_{sender_id}"),
                            request_type=ApprovalRequestType.PRICE_EXCEPTION,
                            requested_value=float(dem_price or 0.0),
                            authorized_value=float(pkg_floor),
                            package_id=str(pkg_id),
                            quantity=int(qty),
                            reason="Customer requested price below authorized floor",
                            workspace_id=ws_id
                        )
            else:
                price_res = calculate_package_price(
                    package_id=str(pkg_id),
                    quantity=int(qty)
                )
                verified_context["pricing"] = price_res

        # B. DELIVERY CALCULATOR TOOL
        if CustomerIntent.DELIVERY_INQUIRY in intents or CustomerIntent.DELIVERY_TIME_INQUIRY in intents:
            selected_tools.append("delivery_calculator")
            is_inside = entities.get("location") == "inside_dhaka" if entities.get("location") else True
            subtotal = float(verified_context.get("pricing", {}).get("total_amount") or 5000.0)
            try:
                del_res = calculate_delivery_and_cod(
                    subtotal=subtotal,
                    is_inside_dhaka=is_inside
                )
                verified_context["delivery"] = del_res
            except Exception as e:
                verified_context["delivery"] = {
                    "base_delivery": 80.0 if is_inside else 130.0,
                    "cod_charge": 0.0,
                    "total_delivery_charge": 80.0 if is_inside else 130.0
                }

        # C. MEDIA ROUTER TOOL
        routed_media = MediaRouter.route_media(
            message=customer_message,
            conversation_history=conversation_history,
            conversation_state=conversation_state,
            workspace_id=ws_id
        )
        if routed_media.get("video_url") or routed_media.get("voice_url") or routed_media.get("requires_clarification"):
            selected_tools.append("media_router")
            verified_context["media"] = routed_media

        # -------------------------------------------------------------
        # STEP 5: CONTROLLED RESPONSE SYNTHESIS (DRAFT GENERATION)
        # -------------------------------------------------------------
        draft_reply_text = ""
        matched_images: List[str] = []
        voice_url = routed_media.get("voice_url", "")
        video_url = routed_media.get("video_url", "")

        # 1. Ambiguous media request clarification
        if routed_media.get("requires_clarification"):
            draft_reply_text = routed_media.get("clarification_prompt", "")

        # 2. MOQ rejection (< 30 pcs)
        elif CustomerIntent.MOQ_REJECTED in intents or (entities.get("quantity") and entities["quantity"] < 30):
            draft_reply_text = f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"
        
        # 3. Price / Negotiation response synthesis from verified context
        elif "pricing" in verified_context:
            p_data = verified_context["pricing"]
            if requires_owner_approval:
                from app.ai_agent.owner_approval import OwnerApprovalEngine
                draft_reply_text = OwnerApprovalEngine.get_pending_customer_response(honorific)
            elif p_data.get("is_approved_exception"):
                pkg_id_str = p_data.get("package_id", "7")
                unit_p = int(p_data.get("upfront_unit_price", 0))
                draft_reply_text = f"জি {honorific}, Owner স্যারের বিশেষ অনুমতিতে প্যাকেজ {pkg_id_str} এর জন্য প্রতি সেট {unit_p} টাকা রাখা যাবে।"
            elif CustomerIntent.NEGOTIATION in intents:
                draft_reply_text = p_data.get("reply_text") or (
                    f"জি {honorific}, আমাদের প্যাকেজ {p_data.get('package_id')} এর জন্য বিশেষ অফারে "
                    f"প্রতি সেট {int(p_data.get('offered_unit_price', 0))} টাকা করে রাখা যাবে।"
                )
            else:
                pkg_title = p_data.get("title", f"প্যাকেজ {p_data.get('package_id')}")
                unit_p = int(p_data.get("upfront_unit_price", 0))
                draft_reply_text = f"জি {honorific}, {pkg_title}-এর রেগুলার রেট প্রতি সেট {unit_p} টাকা।"

        # 3. Delivery response synthesis from verified context
        elif "delivery" in verified_context:
            if CustomerIntent.DELIVERY_TIME_INQUIRY in intents:
                draft_reply_text = (
                    f"জি {honorific}, আমাদের কাজ সম্পন্ন করতে ৫-৬ দিন সময় লাগে "
                    f"এবং কুরিয়ারে পৌঁছাতে ২৪-৪৮ ঘণ্টা সময় লাগে।"
                )
            else:
                d_data = verified_context["delivery"]
                base_fee = int(d_data.get("base_delivery", 80.0))
                draft_reply_text = (
                    f"জি {honorific}, আমাদের ডেলিভারি চার্জ ঢাকার ভেতরে {base_fee} টাকা "
                    f"এবং ঢাকার বাইরে ১৩০ টাকা। কাজ শুরুর পূর্বে ডেলিভারি চার্জ অগ্রিম পেমেন্ট বাধ্যতামূলক।"
                )

        # 4. Media response synthesis from verified context
        elif "media" in verified_context and (video_url or voice_url):
            if video_url:
                draft_reply_text = f"জি {honorific}, নিচে নির্দেশিকা ডেমো ভিডিওটি পাঠানো হলো।"
            else:
                draft_reply_text = f"জি {honorific}, নিচে আমাদের বিস্তারিত ভয়েস বার্তাটি শুনুন।"

        # 5. Owner request response synthesis
        elif CustomerIntent.OWNER_REQUEST in intents:
            draft_reply_text = f"জি {honorific}, রাশেদ স্যার আমাদের ওনার স্যার। ওনার স্যারের সাথে জরুরি প্রয়োজনে অফিশিয়াল নম্বরে যোগাযোগ করতে পারেন।"

        # 6. Greeting response synthesis
        elif CustomerIntent.GREETING in intents:
            draft_reply_text = f"ওয়ালাইকুমুস সালাম {honorific}, আরএস গ্রাফিক্সে আপনাকে স্বাগতম। আপনি কত পিস আইডি কার্ড তৈরি করতে চাচ্ছেন জানাবেন প্লিজ?"

        # 7. Price inquiry without quantity synthesis
        elif CustomerIntent.PRICE_INQUIRY in intents and entities.get("quantity") is None:
            draft_reply_text = f"জি {honorific}, আমাদের আইডি কার্ডের রেট অর্ডারের পরিমাণের ওপর নির্ভর করে (সর্বনিম্ন ৩০ পিস)। আপনার কত পিস কার্ড প্রয়োজন জানাবেন প্লিজ?"

        # 8. Unknown / Safe Fallback
        if not draft_reply_text:
            draft_reply_text = f"জি {honorific}, আমাদের আইডি কার্ড, ফিতা ও কভারের যেকোনো তথ্য বা অর্ডার সম্পর্কে সহযোগিতা করতে পেরে আনন্দিত। আপনার কত পিস কার্ড প্রয়োজন জানাবেন প্লিজ?"

        # -------------------------------------------------------------
        # STEP 6: RESPONSE VALIDATOR & POLICY GUARD (Mandatory Inspection)
        # -------------------------------------------------------------
        draft_payload = {
            "reply_text": draft_reply_text,
            "matched_images": matched_images,
            "media_sequence": [],
            "voice_url": voice_url,
            "video_url": video_url,
            "order_created": None,
            "response_source": "master_orchestrator"
        }

        try:
            validated_payload = ResponseValidator.validate_and_sanitize(
                draft_response=draft_payload,
                customer_message=customer_message,
                conversation_history=conversation_history,
                sender_id=sender_id,
                customer_name=customer_name,
                workspace_id=ws_id
            )
        except Exception as ex:
            print(f"[MasterOrchestrator Validator Fallback Error]: {ex}")
            validated_payload = {
                "reply_text": draft_reply_text or f"জি {honorific}, আরএস গ্রাফিক্সের পক্ষ থেকে আপনাকে স্বাগতম। আপনার অর্ডার বা তথ্যের বিষয়ে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।",
                "matched_images": matched_images,
                "media_sequence": [],
                "voice_url": voice_url,
                "video_url": video_url,
                "order_created": None,
                "response_source": "master_orchestrator_safe_fallback"
            }

        # Append structured orchestrator log
        validated_payload["orchestrator_log"] = {
            "conversation_id": sender_id,
            "primary_intent": intent_data["primary_intent"],
            "all_intents": [i.value if hasattr(i, "value") else str(i) for i in intents],
            "confidence": intent_data["confidence"],
            "selected_tools": selected_tools,
            "entities": entities,
            "requires_owner_approval": requires_owner_approval,
            "owner_approval_reason": owner_approval_reason,
            "duration_ms": round((time.time() - start_time) * 1000, 2)
        }

        return validated_payload
