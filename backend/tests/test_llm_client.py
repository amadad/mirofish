import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.llm_client import LLMClient


def test_clean_content_strips_think_tags():
    client = object.__new__(LLMClient)

    cleaned = LLMClient._clean_content(
        client,
        '<think>hidden reasoning</think>\n{"status": "ok"}',
    )

    assert cleaned == '{"status": "ok"}'


def test_chat_json_accepts_markdown_fenced_json():
    client = object.__new__(LLMClient)
    client.chat = lambda **kwargs: '```json\n{"status": "ok"}\n```'

    payload = LLMClient.chat_json(client, messages=[])

    assert payload == {"status": "ok"}
