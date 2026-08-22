import asyncio
import time
from typing import Dict, Any, Callable, Optional, List
from app.database import get_conversation_state, is_conversation_ai_active

class PendingBatch:
    def __init__(self, channel: str, workspace_id: int, sender_id: str, customer_name: str, initial_version: int, page_id: str = ""):
        self.channel = channel
        self.workspace_id = workspace_id
        self.sender_id = sender_id
        self.customer_name = customer_name
        self.page_id = page_id
        self.initial_version = initial_version
        self.created_at = time.time()
        self.messages: List[Dict[str, Any]] = []
        self.timer_task: Optional[asyncio.Task] = None
        self.is_cancelled = False

class MessageDebouncer:
    """
    Asynchronous 3-Second Message Debouncer & Aggregator.
    Aggregates rapid incoming customer messages into a single conversational turn.
    Guarantees deterministic cancellation if an admin takes over or if conversation_version changes.
    """
    def __init__(self, debounce_seconds: float = 3.0):
        self.debounce_seconds = debounce_seconds
        self._batches: Dict[str, PendingBatch] = {}
        self._lock = asyncio.Lock()

    def _get_key(self, channel: str, workspace_id: int, sender_id: str) -> str:
        return f"{channel}:{workspace_id}:{sender_id}"

    async def add_message(
        self,
        channel: str,
        workspace_id: int,
        sender_id: str,
        customer_name: str,
        text: str = "",
        image_bytes: bytes = None,
        image_mime: str = "image/jpeg",
        audio_bytes: bytes = None,
        audio_mime: str = "audio/mp4",
        page_id: str = "",
        callback: Callable[[PendingBatch], Any] = None
    ):
        key = self._get_key(channel, workspace_id, sender_id)
        
        # Check current state BEFORE scheduling
        state = get_conversation_state(sender_id=sender_id, workspace_id=workspace_id)
        if state.get("admin_takeover") or not state.get("ai_enabled") or state.get("human_takeover", 0) == 1:
            print(f"[AI_GUARD] customer={sender_id} admin_takeover=true action=SKIP_AI_RESPONSE reason=takeover_active")
            return

        current_version = state.get("conversation_version", 1)

        async with self._lock:
            batch = self._batches.get(key)
            if not batch or batch.is_cancelled:
                batch = PendingBatch(
                    channel=channel,
                    workspace_id=workspace_id,
                    sender_id=sender_id,
                    customer_name=customer_name,
                    initial_version=current_version,
                    page_id=page_id
                )
                self._batches[key] = batch
                print(f"[AI_BATCH_CREATED] key={key} version={current_version}")
            else:
                # Cancel existing timer to extend debounce window
                if batch.timer_task and not batch.timer_task.done():
                    batch.timer_task.cancel()

            # Append message to batch
            batch.messages.append({
                "sender": "CUSTOMER",
                "text": text,
                "image_bytes": image_bytes,
                "image_mime": image_mime,
                "audio_bytes": audio_bytes,
                "audio_mime": audio_mime,
                "timestamp": time.time()
            })

            # Start new debounce timer
            batch.timer_task = asyncio.create_task(
                self._debounce_worker(key, batch, callback)
            )

    async def _debounce_worker(self, key: str, batch: PendingBatch, callback: Callable[[PendingBatch], Any]):
        try:
            await asyncio.sleep(self.debounce_seconds)
            
            async with self._lock:
                # Remove from active map
                if self._batches.get(key) == batch:
                    del self._batches[key]

            if batch.is_cancelled:
                print(f"[AI_BATCH_CANCELLED] key={key} action=discarded_due_to_cancellation")
                return

            # Check database state AGAIN after debounce window
            state = get_conversation_state(sender_id=batch.sender_id, workspace_id=batch.workspace_id)
            if state.get("admin_takeover") or not state.get("ai_enabled") or state.get("human_takeover", 0) == 1:
                print(f"[AI_BATCH_CANCELLED] key={key} action=discarded_due_to_admin_takeover")
                return

            if state.get("conversation_version", 1) != batch.initial_version:
                print(f"[AI_JOB_INVALIDATED] key={key} expected_version={batch.initial_version} current_version={state.get('conversation_version')} action=discarded_stale_job")
                return

            # Execute callback with consolidated batch
            if callback:
                if asyncio.iscoroutinefunction(callback):
                    await callback(batch)
                else:
                    callback(batch)

        except asyncio.CancelledError:
            # Expected when debouncing extends or batch is cancelled
            pass
        except Exception as e:
            print(f"[Debounce Worker Error for {key}]: {e}")

    def cancel_batch(self, channel: str, workspace_id: int, sender_id: str):
        """Immediately cancels and discards any pending AI response batch for a customer."""
        key = self._get_key(channel, workspace_id, sender_id)
        batch = self._batches.get(key)
        if batch:
            batch.is_cancelled = True
            if batch.timer_task and not batch.timer_task.done():
                batch.timer_task.cancel()
            self._batches.pop(key, None)
            print(f"[AI_BATCH_CANCELLED] key={key} reason=admin_takeover_or_manual_cancel")

# Global debouncer instance
message_debouncer = MessageDebouncer(debounce_seconds=3.0)
