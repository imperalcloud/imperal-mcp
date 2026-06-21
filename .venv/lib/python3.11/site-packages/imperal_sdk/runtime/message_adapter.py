"""Message format translation between LLM providers.

Anthropic and OpenAI use different formats for tool use conversations:
- Anthropic: content blocks (tool_use/tool_result) in message content arrays
- OpenAI: tool_calls on assistant messages, role="tool" for results

This module isolates ALL format translation so the rest of the system
works with Anthropic-format internally, and this adapter handles conversion.
"""
import json
import logging

log = logging.getLogger(__name__)


class AnthropicCompat:
    """Mimics anthropic.types.Message for non-Anthropic provider responses."""

    def __init__(self, content, stop_reason, model, usage=None):
        self.content = [ContentBlock(b) if isinstance(b, dict) else b for b in content]
        self.stop_reason = stop_reason
        self.model = model
        self.usage = usage or _EmptyUsage()


class ContentBlock:
    """Mimics anthropic content block (TextBlock / ToolUseBlock)."""

    def __init__(self, data: dict):
        self.type = data.get("type", "text")
        self.text = data.get("text", "")
        self.id = data.get("id", "")
        self.name = data.get("name", "")
        self.input = data.get("input", {})


class _EmptyUsage:
    input_tokens = 0
    output_tokens = 0


class MessageAdapter:
    """Translates messages between Anthropic and OpenAI formats."""

    @staticmethod
    def to_openai_messages(messages: list, system: str = "") -> list:
        """Translate Anthropic-format message history to OpenAI format.

        Handles:
        - system string -> {"role": "system", ...}
        - assistant messages with ContentBlock objects -> tool_calls format
        - user messages with tool_result dicts -> role="tool" messages
        - _ContentBlock objects from AnthropicCompat -> proper dicts
        - Regular text messages -> pass through
        """
        oai = []
        if system:
            oai.append({"role": "system", "content": system})

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # --- Plain string content ---
            if isinstance(content, str):
                oai.append({"role": role, "content": content})
                continue

            # --- List content (Anthropic content blocks) ---
            if isinstance(content, list):
                # Check if this is a tool_result list (user message after tool calls)
                if content and _is_tool_result_list(content):
                    for item in content:
                        tr = _as_dict(item)
                        if tr.get("type") == "tool_result":
                            oai.append({
                                "role": "tool",
                                "tool_call_id": tr.get("tool_use_id", ""),
                                "content": tr.get("content", ""),
                            })
                    continue

                # Check if this is an assistant message with tool_use blocks
                text_parts = []
                tool_calls = []
                for block in content:
                    b = _as_dict(block)
                    if b.get("type") == "tool_use":
                        tool_calls.append({
                            "id": b.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": b.get("name", ""),
                                "arguments": json.dumps(b.get("input", {})),
                            },
                        })
                    elif b.get("type") == "text":
                        text_parts.append(b.get("text", ""))

                if tool_calls:
                    msg_out = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
                    msg_out["tool_calls"] = tool_calls
                    oai.append(msg_out)
                elif text_parts:
                    oai.append({"role": role, "content": "\n".join(text_parts)})
                else:
                    oai.append({"role": role, "content": str(content)})
                continue

            # Fallback
            oai.append({"role": role, "content": str(content)})

        return oai

    @staticmethod
    def to_openai_tools(tools: list) -> list:
        """Anthropic tool schema -> OpenAI function calling format."""
        if not tools:
            return []
        result = []
        for t in tools:
            fn_params = t.get("input_schema", {})
            # Guard: OpenAI requires "items" on all array types
            # Auto-add default if missing (prevents 400 schema errors)
            if "properties" in fn_params:
                for _pname, _pschema in fn_params["properties"].items():
                    if isinstance(_pschema, dict) and _pschema.get("type") == "array" and "items" not in _pschema:
                        _pschema["items"] = {"type": "string"}
            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": fn_params,
                    },
                }
            )
        return result

    @staticmethod
    def to_openai_tool_choice(tool_choice: dict | None) -> str | dict | None:
        """Anthropic tool_choice -> OpenAI tool_choice."""
        if not tool_choice:
            return None
        tc_type = tool_choice.get("type", "auto")
        if tc_type == "any":
            return "required"
        if tc_type == "tool":
            return {"type": "function", "function": {"name": tool_choice.get("name", "")}}
        return "auto"

    @staticmethod
    def from_openai_response(response, model: str) -> "AnthropicCompat":
        """OpenAI chat completion -> AnthropicCompat wrapper."""
        choice = response.choices[0] if response.choices else None
        content_blocks = []
        stop_reason = "end_turn"

        if choice:
            if choice.message.content:
                content_blocks.append({"type": "text", "text": choice.message.content})
            if choice.message.tool_calls:
                stop_reason = "tool_use"
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": args,
                    })
            if choice.finish_reason == "tool_calls":
                stop_reason = "tool_use"

        # Normalize OpenAI usage to Anthropic format (input_tokens/output_tokens)
        usage = None
        if hasattr(response, "usage") and response.usage:
            oai_usage = response.usage
            # OpenAI uses prompt_tokens/completion_tokens
            # Anthropic uses input_tokens/output_tokens
            # Normalize to Anthropic format so LLM Provider tracking works uniformly
            class _NormalizedUsage:
                def __init__(self, u):
                    self.input_tokens = getattr(u, 'input_tokens', 0) or getattr(u, 'prompt_tokens', 0) or 0
                    self.output_tokens = getattr(u, 'output_tokens', 0) or getattr(u, 'completion_tokens', 0) or 0
            usage = _NormalizedUsage(oai_usage)

        return AnthropicCompat(content_blocks, stop_reason, model, usage)


def _as_dict(item) -> dict:
    """Convert ContentBlock or dict to dict for uniform access."""
    if isinstance(item, dict):
        return item
    # ContentBlock object — read attributes
    return {
        "type": getattr(item, "type", "text"),
        "text": getattr(item, "text", ""),
        "id": getattr(item, "id", ""),
        "name": getattr(item, "name", ""),
        "input": getattr(item, "input", {}),
        "tool_use_id": getattr(item, "tool_use_id", ""),
        "content": getattr(item, "content", ""),
    }


def _is_tool_result_list(content: list) -> bool:
    """Check if a content list contains tool_result items."""
    for item in content:
        d = _as_dict(item)
        if d.get("type") == "tool_result":
            return True
    return False
