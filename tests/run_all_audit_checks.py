import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from tests.test_multi_page_suite import (
    test_database_and_migration, test_multi_page_crud_and_isolation, test_omnichat_page_scoping
)
from tests.test_webhook_e2e_routing import (
    test_facebook_messenger_routing, test_whatsapp_multi_account_routing
)
from tests.verify_audit_checks import (
    run_import_checks, run_route_checks, run_legacy_fallback_check
)
from tests.verify_database_preservation import audit_database_preservation
from tests.test_isolation_and_admin_reply import test_admin_reply_isolation
from tests.test_token_masking_security import test_token_masking_security

async def run_master_audit():
    print("================================================================")
    print("       FINAL PRODUCTION SAFETY AUDIT: FULL SUITE RUN           ")
    print("================================================================")

    # 1. Imports & Routes
    run_import_checks()
    run_route_checks()

    # 2. Database Preservation & Legacy Fallback
    audit_database_preservation()
    run_legacy_fallback_check()

    # 3. Multi-Page CRUD & Token Isolation
    test_database_and_migration()
    test_multi_page_crud_and_isolation()
    test_omnichat_page_scoping()

    # 4. E2E Webhook Routing
    await test_facebook_messenger_routing()
    await test_whatsapp_multi_account_routing()

    # 5. Cross-Route Isolation & Admin Replies
    test_admin_reply_isolation()

    # 6. Security & Token Masking
    test_token_masking_security()

    print("\n================================================================")
    print("       ALL 16 PRODUCTION AUDIT CHECKS PASSED PERFECTLY!        ")
    print("================================================================\n")

if __name__ == "__main__":
    asyncio.run(run_master_audit())
