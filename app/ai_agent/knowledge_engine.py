"""
Phase 9: Knowledge Engine, Strict No-Guess Boundary & Team Escalation for RS Graphics AI Agent.

Guarantees:
1. Centralized dynamic knowledge retrieval from database (Active Training Rules, FAQs, Products).
2. Strict No-Guess Boundary: Never invents unknown facts or specs; escalates to human team.
3. Persistent Deduplicated Team Escalations in SQLite.
4. Agent Persona: Explicit agent name is 'নাদিম'.
5. Owner Persona: Never hallucinates owner identity unless authoritatively defined.
"""

import re
from typing import Dict, Any, List, Optional

from app.database import (
    get_active_training_rules, search_training_rules,
    get_all_faqs, get_all_products,
    create_team_escalation
)
from app.ai_agent.response_validator import detect_customer_gender_title


AGENT_NAME_BN = "নাদিম"
AGENT_NAME_EN = "Nadim"


class KnowledgeEngine:
    """
    Centralized knowledge lookup layer and strict anti-hallucination boundary.
    """

    @classmethod
    def retrieve_relevant_knowledge(
        cls,
        query: str,
        intent: str = "",
        topic: str = "",
        workspace_id: int = 1
    ) -> Dict[str, Any]:
        """
        Retrieves strictly relevant active training rules, FAQs, and product specs
        scoped to workspace without dumping the whole database into prompts.
        """
        ws_id = int(workspace_id or 1)
        q_clean = (query or "").strip().lower()

        matched_rules = []
        matched_faqs = []
        matched_products = []

        if q_clean:
            # 1. Search training rules by relevance
            rule_candidates = search_training_rules(q_clean, workspace_id=ws_id)
            if not rule_candidates:
                # Try fallback search with individual high-value keywords
                stopwords = {"এবং", "করে", "হবে", "জন্য", "আমাদের", "আপনার", "চাই", "বানাতে", "করতে", "লাগবে", "বানাবো", "আমি", "আমরা", "আছে", "কি"}
                keywords = [w for w in q_clean.split() if len(w) >= 3 and w not in stopwords]
                for kw in keywords[:3]:
                    kw_matches = search_training_rules(kw, workspace_id=ws_id)
                    for r in kw_matches:
                        if r not in rule_candidates:
                            rule_candidates.append(r)
            matched_rules = rule_candidates[:5]

            # 2. Search FAQs
            all_faqs = get_all_faqs(workspace_id=ws_id)
            for f in all_faqs:
                q_text = str(f.get("question") or "").lower()
                a_text = str(f.get("answer") or "").lower()
                if any(w in q_text or w in a_text for w in q_clean.split() if len(w) >= 3):
                    matched_faqs.append(f)
            matched_faqs = matched_faqs[:3]

            # 3. Search Products
            all_prods = get_all_products(workspace_id=ws_id)
            for p in all_prods:
                p_name = str(p.get("name") or "").lower()
                p_desc = str(p.get("description") or "").lower()
                if p_name in q_clean or any(w in p_name or w in p_desc for w in q_clean.split() if len(w) >= 3):
                    matched_products.append(p)
            matched_products = matched_products[:3]

        has_authoritative_answer = bool(matched_rules or matched_faqs or matched_products)

        return {
            "query": query,
            "intent": intent,
            "topic": topic,
            "workspace_id": ws_id,
            "matched_rules": matched_rules,
            "matched_faqs": matched_faqs,
            "matched_products": matched_products,
            "has_authoritative_answer": has_authoritative_answer
        }

    @classmethod
    def check_identity_inquiry(
        cls,
        message: str,
        customer_name: str = "Customer",
        workspace_id: int = 1,
        sender_id: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Handles identity inquiries (Agent Name 'নাদিম' or Owner Name inquiry).
        """
        raw_msg = (message or "").strip().lower()
        honorific = detect_customer_gender_title(customer_name)
        ws_id = int(workspace_id or 1)

        # Agent Name inquiry
        agent_name_patterns = [
            "তোমার নাম কি", "তোমার নাম কী", "আপনার নাম কি", "আপনার নাম কী",
            "তোমার নাম", "আপনার নাম", "who are you", "what is your name",
            "কার সাথে কথা বলছি", "কার সাথে কথা বলতেছি"
        ]
        if any(p in raw_msg for p in agent_name_patterns):
            return {
                "reply_text": f"জি {honorific}, আমার নাম {AGENT_NAME_BN}। আমি আরএস গ্রাফিক্সের সেলস সহকারী। আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ?",
                "is_handled": True,
                "response_source": "agent_identity_inquiry"
            }

        # Owner Name inquiry (Never hallucinate; follow Rule 13 / No-guess policy)
        owner_patterns = [
            "owner এর নাম কি", "owner এর নাম কী", "owner কে", "মালিকের নাম কি", "মালিকের নাম কী",
            "মালিক কে", "ওনারের নাম কি", "ওনারের নাম কী", "বসের নাম কি", "বসের নাম কী",
            "who is the owner", "owner name"
        ]
        if any(p in raw_msg for p in owner_patterns):
            # Record team escalation
            if sender_id:
                create_team_escalation(
                    sender_id=str(sender_id),
                    customer_message=message,
                    detected_unknown_topic="owner_identity_inquiry",
                    workspace_id=ws_id
                )
            return {
                "reply_text": f"জি {honorific}, Owner স্যারের নামের তথ্যটি এই মুহূর্তে আমার কাছে সংরক্ষিত নেই। বিষয়টি আমাদের টিমকে জানাচ্ছি। আমাদের টিম আপনাকে জানাবে।",
                "is_handled": True,
                "response_source": "owner_identity_escalation"
            }

        # Specific mention of Rashed Bhai (Rule 13)
        if any(p in raw_msg for p in ["রাশেদ ভাই কোথায়", "রাশেদ কোথায়", "রাশেদ ভাইয়ের সাথে", "রাশেদ এর সাথে", "rashed bhai", "রাশেদুল ইসলাম কে", "রাশেদুল ইসলাম", "রাশেদ কে", "রাশেদুল"]):
            return {
                "reply_text": f"জি {honorific}, রাশেদ স্যার আমাদের ওনার স্যার। আপনার বিষয়টি ওনার স্যারকে জানিয়ে দিচ্ছি।",
                "is_handled": True,
                "response_source": "owner_mention_rule_13"
            }

        return None

    @classmethod
    def handle_unknown_inquiry(
        cls,
        customer_message: str,
        sender_id: str,
        detected_topic: str = "unsupported_inquiry",
        workspace_id: int = 1,
        customer_name: str = "Customer",
        channel: str = "facebook"
    ) -> Dict[str, Any]:
        """
        Strict No-Guess fallback: creates a deduplicated team escalation and responds politely.
        """
        ws_id = int(workspace_id or 1)
        honorific = detect_customer_gender_title(customer_name)

        # Create deduplicated escalation
        esc_id = None
        if sender_id:
            try:
                esc_id = create_team_escalation(
                    sender_id=str(sender_id),
                    customer_message=customer_message,
                    detected_unknown_topic=detected_topic,
                    workspace_id=ws_id,
                    source_channel=channel
                )
            except Exception as e:
                print(f"[Team Escalation Save Warning]: {e}")

        reply_text = f"জি {honorific}, এই বিষয়টির সঠিক তথ্য এই মুহূর্তে আমার কাছে নেই। বিষয়টি আমাদের টিমকে জানাচ্ছি। আমাদের টিম আপনাকে জানাবে।"

        return {
            "reply_text": reply_text,
            "matched_images": [],
            "media_sequence": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "is_unknown": True,
            "escalation_id": esc_id,
            "response_source": "no_guess_team_escalation"
        }
