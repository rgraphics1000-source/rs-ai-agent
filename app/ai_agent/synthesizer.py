import json
import re
from google import genai
from app.config import settings
from app.database import get_setting, create_training_rule, get_db_connection

def synthesize_training_text_to_rules(raw_text: str) -> list:
    """
    Takes raw, unorganized, or messy Bengali business instructions from the owner
    and uses Gemini to extract cleanly structured, categorized business rules.
    """
    if not raw_text or not raw_text.strip():
        return []

    api_key = get_setting("gemini_api_key", settings.GEMINI_API_KEY)
    if not api_key:
        # Fallback basic rule creation
        rule_id = create_training_rule(
            title="কাস্টম বিজনেস পলিসি",
            response_or_rule=raw_text.strip(),
            rule_type="instruction",
            category="Custom Knowledge",
            is_active=1
        )
        return [{"id": rule_id, "title": "কাস্টম বিজনেস পলিসি", "category": "Custom Knowledge", "response_or_rule": raw_text.strip()}]

    client = genai.Client(api_key=api_key)

    prompt = f"""
তুমি একজন সিনিয়র এআই সেলস ট্রেইনার। 
নিচে একজন বিজনেস ওনারের দেওয়া অসংগঠিত/এলোমেলো ট্রেইনিং নোট দেওয়া হলো।
এলোমেলো কথাগুলো থেকে আলাদা আলাদা বাস্তবসম্মত ব্যবসায়িক সেলস ও বিহেভিয়ার রুলস এক্সট্রাক্ট করে নিচের JSON ফরম্যাটে রিটার্ন করো:

```json
[
  {{
    "title": "রুলের সংক্ষিপ্ত শিরোনাম (যেমন: সংক্ষিপ্ত উত্তর দেওয়ার নিয়ম, ক্রয়মূল্য গোপন রাখা)",
    "category": "General / Pricing / Objection / Protocol / Politeness",
    "question_or_trigger": "কখন এই রুলটি প্রযোজ্য হবে (যদি থাকে)",
    "response_or_rule": "এআই কীভাবে আচরণ করবে তার পরিষ্কার বাংলা নির্দেশ"
  }}
]
```

বিজনেস ওনারের এলোমেলো র নোটিস:
{raw_text}

শুধুমাত্র ভ্যালিড JSON অ্যারে রিটার্ন করো। কোনো অতিরিক্ত ভূমিকা বা সমাপ্তি লিখবে না।
"""

    models = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-2.5-flash"]
    response_text = ""
    for m in models:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=prompt
            )
            if resp and resp.text:
                response_text = resp.text.strip()
                break
        except Exception as e:
            print(f"[Synthesizer Model {m} error]: {e}")
            continue

    rules_created = []
    if response_text:
        try:
            # Extract JSON block
            clean_json = response_text
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[1].split("```")[0].strip()

            parsed_rules = json.loads(clean_json)
            if isinstance(parsed_rules, list):
                for item in parsed_rules:
                    title = item.get("title", "").strip()
                    rule_content = item.get("response_or_rule", "").strip()
                    cat = item.get("category", "General").strip()
                    trigger = item.get("question_or_trigger", "").strip()
                    
                    if title and rule_content:
                        rid = create_training_rule(
                            title=title,
                            response_or_rule=rule_content,
                            rule_type="instruction" if not trigger else "qa",
                            question_or_trigger=trigger,
                            category=cat,
                            is_active=1
                        )
                        rules_created.append({
                            "id": rid,
                            "title": title,
                            "category": cat,
                            "question_or_trigger": trigger,
                            "response_or_rule": rule_content
                        })
        except Exception as parse_err:
            print(f"[Synthesizer JSON parse error]: {parse_err}")

    # If parsing failed or was empty, save as single consolidated rule
    if not rules_created:
        rid = create_training_rule(
            title="কাস্টম বিজনেস পলিসি নোট",
            response_or_rule=raw_text.strip(),
            rule_type="instruction",
            category="Custom Knowledge",
            is_active=1
        )
        rules_created.append({
            "id": rid,
            "title": "কাস্টম বিজনেস পলিসি নোট",
            "category": "Custom Knowledge",
            "response_or_rule": raw_text.strip()
        })

    return rules_created
