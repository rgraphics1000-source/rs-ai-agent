# -*- coding: utf-8 -*-
import unittest
import asyncio
from app.channels.debouncer import MessageDebouncer, PendingBatch
from app.database import enable_conversation_ai
from app.channels.omnichat import record_conversation_message

class TestDebouncerDeduplication(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        enable_conversation_ai(sender_id='8801899990001', workspace_id=1)
        enable_conversation_ai(sender_id='8801899990002', workspace_id=1)

    async def test_01_aggregates_multiple_rapid_messages_into_one_turn(self):
        debouncer = MessageDebouncer(debounce_seconds=0.2)
        processed_batches = []

        async def callback(batch: PendingBatch):
            processed_batches.append(batch)

        record_conversation_message('whatsapp', '8801899990001', 'Customer', 'customer', 'এই কলম গুলো আছে??', workspace_id=1)
        await debouncer.add_message('whatsapp', 1, '8801899990001', 'Customer', msg_id='m1', text='এই কলম গুলো আছে??', callback=callback)
        await debouncer.add_message('whatsapp', 1, '8801899990001', 'Customer', msg_id='m2', image_bytes=b'fake_image', callback=callback)
        await debouncer.add_message('whatsapp', 1, '8801899990001', 'Customer', msg_id='m3', text='দাম কত?', callback=callback)

        await asyncio.sleep(0.45)

        # Must only produce 1 processed batch with all 3 messages aggregated
        self.assertEqual(len(processed_batches), 1)
        batch = processed_batches[0]
        self.assertEqual(len(batch.messages), 3)

    async def test_02_identical_duplicate_message_within_window_is_suppressed(self):
        debouncer = MessageDebouncer(debounce_seconds=0.2)
        processed_count = 0

        async def callback(batch: PendingBatch):
            nonlocal processed_count
            processed_count += 1

        # First turn
        record_conversation_message('whatsapp', '8801899990002', 'Customer', 'customer', 'এই কলম গুলো আছে??', workspace_id=1)
        await debouncer.add_message('whatsapp', 1, '8801899990002', 'Customer', msg_id='m10', text='এই কলম গুলো আছে??', callback=callback)
        await asyncio.sleep(0.35)
        self.assertEqual(processed_count, 1)

        # Second turn with identical text within short window
        record_conversation_message('whatsapp', '8801899990002', 'Customer', 'customer', 'এই কলম গুলো আছে??', workspace_id=1)
        await debouncer.add_message('whatsapp', 1, '8801899990002', 'Customer', msg_id='m11', text='এই কলম গুলো আছে??', callback=callback)
        await asyncio.sleep(0.35)

        # Second identical turn must NOT trigger a second generation / reply
        self.assertEqual(processed_count, 1)

if __name__ == '__main__':
    unittest.main()
