# -*- coding: utf-8 -*-
"""
Asynchronous 3-Second Message Debouncer & Multimodal Aggregator.
Guarantees activity-based batching measured from the LAST incoming customer message.
Ensures deterministic AI cancellation upon Admin Takeover, version validation, generation locks,
and hard post-send stop (ONE customer turn = ONE generation = ONE reply).
"""

import asyncio
import time
import uuid
from typing import Dict, Any, Callable, Optional, List, Set
from app.database import (
    get_conversation_state, is_conversation_ai_active,
    acquire_generation_lock, release_generation_lock,
    get_conversation_turn_versions, mark_turn_responded
)


class PendingBatch:
    def __init__(
        self,
        channel: str,
        workspace_id: int,
        sender_id: str,
        customer_name: str,
        initial_version: int,
        page_id: str = "",
        effective_phone_id: str = "",
        effective_token: str = "",
        debounce_seconds: float = 1.2
    ):
        self.channel = channel
        self.workspace_id = workspace_id
        self.sender_id = sender_id
        self.customer_name = customer_name
        self.page_id = page_id
        self.effective_phone_id = effective_phone_id
        self.effective_token = effective_token
        self.initial_version = initial_version
        self.batch_id = str(uuid.uuid4())
        self.status = "PENDING"  # PENDING -> PROCESSING -> PROCESSED / CANCELLED
        self.created_at = time.time()
        self.last_message_at = self.created_at
        self.debounce_deadline = self.created_at + debounce_seconds
        self.messages: List[Dict[str, Any]] = []
        self.seen_msg_ids: Set[str] = set()
        self.timer_task: Optional[asyncio.Task] = None
        self.is_cancelled = False
        self.is_processing = False
        self.processing_lock = asyncio.Lock()
        self.callback: Optional[Callable[['PendingBatch'], Any]] = None

    @property
    def conversation_id(self) -> str:
        return f"{self.channel}_{self.sender_id}"


class MessageDebouncer:
    """
    Authoritative Asynchronous Message Debouncer & Multimodal Aggregator.
    Enforces a strict activity-based debounce window measured from the LAST incoming customer message.
    Guarantees:
    - 1 batch per conversation activity window.
    - Exactly 1 AI generation and 1 AI reply per customer turn.
    - Concurrency & generation locks to prevent duplicate execution across workers.
    - Priority 0 immediate cancellation upon Admin Takeover.
    - Idempotency against duplicate webhook messages.
    """
    def __init__(self, debounce_seconds: float = 1.2):
        self.debounce_seconds = debounce_seconds
        self._batches: Dict[str, PendingBatch] = {}
        self._processed_batches: Set[str] = set()
        self._lock = asyncio.Lock()

    def _get_key(self, channel: str, workspace_id: int, sender_id: str) -> str:
        return f"{channel}:{workspace_id}:{sender_id}"

    async def add_message(
        self,
        channel: str,
        workspace_id: int,
        sender_id: str,
        customer_name: str,
        msg_id: str = "",
        text: str = "",
        image_bytes: bytes = None,
        image_mime: str = "image/jpeg",
        audio_bytes: bytes = None,
        audio_mime: str = "audio/mp4",
        page_id: str = "",
        effective_phone_id: str = "",
        effective_token: str = "",
        callback: Callable[[PendingBatch], Any] = None
    ) -> bool:
        """
        Enqueues an incoming customer message into the pending batch and resets the 3-second timer.
        Returns True if enqueued, False if dropped due to admin takeover or duplicate.
        """
        key = self._get_key(channel, workspace_id, sender_id)
        now = time.time()

        # Check Admin Takeover State immediately BEFORE batching
        state = get_conversation_state(sender_id=sender_id, workspace_id=workspace_id)
        if state.get("admin_takeover") or not state.get("ai_enabled") or state.get("human_takeover", 0) == 1:
            print(f"[AI_GUARD] customer={sender_id} workspace_id={workspace_id} admin_takeover=true action=SKIP_AI_RESPONSE reason=takeover_active")
            return False

        current_version = state.get("conversation_version", 1)

        async with self._lock:
            batch = self._batches.get(key)

            # Idempotency check: Ignore duplicate msg_id within the active batch
            if batch and not batch.is_cancelled and not batch.is_processing and batch.status == "PENDING":
                if msg_id and msg_id in batch.seen_msg_ids:
                    print(f"[AI_DEBOUNCER_DUPLICATE_IGNORED] key={key} msg_id={msg_id} action=skip_duplicate_in_batch")
                    return False

            if not batch or batch.is_cancelled or batch.is_processing or batch.status != "PENDING":
                batch = PendingBatch(
                    channel=channel,
                    workspace_id=workspace_id,
                    sender_id=sender_id,
                    customer_name=customer_name,
                    initial_version=current_version,
                    page_id=page_id,
                    effective_phone_id=effective_phone_id,
                    effective_token=effective_token,
                    debounce_seconds=self.debounce_seconds
                )
                self._batches[key] = batch
                is_new = True
            else:
                is_new = False
                # Cancel existing timer to extend debounce window from the LAST message
                if batch.timer_task and not batch.timer_task.done():
                    batch.timer_task.cancel()

            if msg_id:
                batch.seen_msg_ids.add(msg_id)

            if customer_name:
                batch.customer_name = customer_name
            if page_id:
                batch.page_id = page_id
            if effective_phone_id:
                batch.effective_phone_id = effective_phone_id
            if effective_token:
                batch.effective_token = effective_token
            if callback:
                batch.callback = callback

            batch.messages.append({
                "msg_id": msg_id,
                "text": text,
                "image_bytes": image_bytes,
                "image_mime": image_mime,
                "audio_bytes": audio_bytes,
                "audio_mime": audio_mime,
                "timestamp": now
            })

            batch.last_message_at = now
            batch.debounce_deadline = now + self.debounce_seconds

            log_event = "AI_BATCH_CREATED" if is_new else "BATCH_TIMER_RESET"
            print(
                f"[{log_event}] conversation_id={batch.conversation_id} "
                f"message_id={msg_id} received_at={now:.3f} "
                f"batch_id={batch.batch_id} batch_message_count={len(batch.messages)} "
                f"debounce_deadline={batch.debounce_deadline:.3f} "
                f"conversation_version={current_version}"
            )

            # Start new debounce timer from the LAST customer message
            batch.timer_task = asyncio.create_task(
                self._debounce_worker(key, batch)
            )
            return True

    async def _debounce_worker(self, key: str, batch: PendingBatch):
        try:
            # Loop until 3 full seconds have passed since the LAST message
            while True:
                now = time.time()
                remaining = batch.debounce_deadline - now
                if remaining > 0.005:
                    await asyncio.sleep(remaining)
                else:
                    break

            async with batch.processing_lock:
                if batch.is_cancelled or batch.status == "CANCELLED":
                    print(f"[BATCH_CANCELLED_ADMIN_TAKEOVER] key={key} batch_id={batch.batch_id} reason=cancelled_before_processing")
                    return

                if batch.is_processing or batch.status != "PENDING":
                    print(f"[BATCH_ALREADY_PROCESSING] key={key} batch_id={batch.batch_id} action=skip_concurrent_worker")
                    return

                batch.status = "PROCESSING"
                batch.is_processing = True

                async with self._lock:
                    if self._batches.get(key) == batch:
                        del self._batches[key]

            # Re-verify Takeover & Version State at Finalization
            state = get_conversation_state(sender_id=batch.sender_id, workspace_id=batch.workspace_id)
            if state.get("admin_takeover") or not state.get("ai_enabled") or state.get("human_takeover", 0) == 1:
                batch.status = "CANCELLED"
                print(f"[BATCH_CANCELLED_ADMIN_TAKEOVER] key={key} batch_id={batch.batch_id} action=discarded_due_to_admin_takeover")
                return

            if state.get("conversation_version", 1) != batch.initial_version:
                batch.status = "CANCELLED"
                print(f"[AI_JOB_INVALIDATED] key={key} batch_id={batch.batch_id} expected_version={batch.initial_version} current_version={state.get('conversation_version')} action=discarded_stale_job")
                return

            # Double-check idempotency across workers
            if batch.batch_id in self._processed_batches:
                print(f"[BATCH_ALREADY_PROCESSING] key={key} batch_id={batch.batch_id} action=skip_already_completed")
                return
            self._processed_batches.add(batch.batch_id)
            if len(self._processed_batches) > 5000:
                self._processed_batches.pop()

            # Sequence Check: Verify this customer turn hasn't already been responded to
            turn_info = get_conversation_turn_versions(batch.channel, batch.sender_id, batch.workspace_id)
            customer_turn_ver = turn_info.get("customer_turn_version", 1)
            last_resp_ver = turn_info.get("last_responded_turn_version", 0)
            
            if customer_turn_ver <= last_resp_ver:
                batch.status = "PROCESSED"
                print(f"[GENERATION_BLOCKED] conversation_id={batch.conversation_id} batch_id={batch.batch_id} reason=turn_already_responded customer_turn_version={customer_turn_ver} last_responded_version={last_resp_ver}")
                return

            print(
                f"[BATCH_FINALIZED] conversation_id={batch.conversation_id} "
                f"batch_id={batch.batch_id} total_messages={len(batch.messages)} "
                f"conversation_version={batch.initial_version} "
                f"customer_turn_version={customer_turn_ver}"
            )

            # Acquire Exclusive Per-Conversation Generation Lock
            has_gen_lock = await acquire_generation_lock(batch.conversation_id)
            if not has_gen_lock:
                print(f"[GENERATION_BLOCKED] conversation_id={batch.conversation_id} batch_id={batch.batch_id} reason=concurrent_generation_lock_active")
                return

            try:
                print(f"[GENERATION_START] conversation_id={batch.conversation_id} batch_id={batch.batch_id} customer_turn_version={customer_turn_ver}")
                if batch.callback:
                    if asyncio.iscoroutinefunction(batch.callback):
                        await batch.callback(batch)
                    else:
                        batch.callback(batch)

                # Mark turn as responded
                mark_turn_responded(batch.channel, batch.sender_id, customer_turn_ver, batch.workspace_id)
                batch.status = "PROCESSED"
                print(f"[GENERATION_END] conversation_id={batch.conversation_id} batch_id={batch.batch_id}")

            finally:
                await release_generation_lock(batch.conversation_id)

        except asyncio.CancelledError:
            # Expected when extended by a new message or cancelled by admin
            pass
        except Exception as e:
            print(f"[Debounce Worker Error for {key}]: {e}")

    async def flush(self, channel: str, workspace_id: int, sender_id: str):
        """Immediately flushes and processes any pending batch for testing or forced immediate dispatch."""
        key = self._get_key(channel, workspace_id, sender_id)
        batch = self._batches.get(key)
        if batch and not batch.is_cancelled and not batch.is_processing and batch.status == "PENDING":
            if batch.timer_task and not batch.timer_task.done():
                batch.timer_task.cancel()
            batch.debounce_deadline = time.time() - 1
            await self._debounce_worker(key, batch)

    def cancel_batch(self, channel: str, workspace_id: int, sender_id: str):
        """Immediately cancels and discards any pending AI response batch for a customer."""
        key = self._get_key(channel, workspace_id, sender_id)
        batch = self._batches.get(key)
        if batch:
            batch.is_cancelled = True
            batch.status = "CANCELLED"
            if batch.timer_task and not batch.timer_task.done():
                batch.timer_task.cancel()
            self._batches.pop(key, None)
            print(f"[BATCH_CANCELLED_ADMIN_TAKEOVER] key={key} batch_id={batch.batch_id} reason=admin_takeover_or_manual_cancel")

    def cancel_all_batches(self):
        """Immediately cancels all pending AI response batches across all channels and workspaces."""
        keys = list(self._batches.keys())
        for key in keys:
            batch = self._batches.get(key)
            if batch:
                batch.is_cancelled = True
                batch.status = "CANCELLED"
                if batch.timer_task and not batch.timer_task.done():
                    batch.timer_task.cancel()
        self._batches.clear()
        print(f"[ALL_BATCHES_CANCELLED_AI_PAUSED] Cancelled {len(keys)} in-flight pending batches.")

    def cancel_workspace_batches(self, workspace_id: int):
        """Immediately cancels all pending AI response batches for a specific workspace."""
        ws_str = f":{workspace_id}:"
        keys_to_cancel = [k for k in self._batches.keys() if ws_str in k]
        for key in keys_to_cancel:
            batch = self._batches.get(key)
            if batch:
                batch.is_cancelled = True
                batch.status = "CANCELLED"
                if batch.timer_task and not batch.timer_task.done():
                    batch.timer_task.cancel()
                self._batches.pop(key, None)
        print(f"[WORKSPACE_BATCHES_CANCELLED] workspace_id={workspace_id} count={len(keys_to_cancel)}")


# Global debouncer instance
message_debouncer = MessageDebouncer(debounce_seconds=1.2)
