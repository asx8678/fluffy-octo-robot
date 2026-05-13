"""Streaming response handling for the standalone Gemini model."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.messages import ModelResponseStreamEvent
from pydantic_ai.models import StreamedResponse
from pydantic_ai.usage import RequestUsage

from code_muse.gemini_utils import generate_tool_call_id

_MISSING = object()


def _extract_partial_value(p_arg: dict) -> Any:
    for key in [
        "stringValue",
        "numberValue",
        "boolValue",
        "nullValue",
        "structValue",
        "listValue",
    ]:
        if key in p_arg:
            val = p_arg[key]
            if key == "nullValue":
                return None
            return val
    return _MISSING


def _apply_json_path(target: dict, path: str, value: Any):
    parts = path.split(".")
    curr = target
    for i, part in enumerate(parts):
        if "[" in part and part.endswith("]"):
            key, idx_str = part.split("[")
            idx = int(idx_str[:-1])
            if key not in curr:
                curr[key] = []
            while len(curr[key]) <= idx:
                curr[key].append(None)

            if i == len(parts) - 1:
                curr[key][idx] = value
            else:
                if curr[key][idx] is None:
                    curr[key][idx] = {}
                curr = curr[key][idx]
        else:
            if i == len(parts) - 1:
                curr[part] = value
            else:
                if part not in curr or curr[part] is None:
                    curr[part] = {}
                curr = curr[part]


@dataclass
class GeminiStreamingResponse(StreamedResponse):
    """Streaming response handler for Gemini API."""

    _chunks: AsyncIterator[dict[str, Any]]
    _model_name_str: str
    _provider_name_str: str = "google"
    _provider_url_str: str | None = None
    _timestamp_val: datetime = field(default_factory=lambda: datetime.now(UTC))
    _current_tool_call_id: str | None = None
    _current_tool_name: str | None = None
    _current_vendor_part_id: uuid.UUID | None = None
    _current_args: dict[str, Any] = field(default_factory=dict)

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        """Process streaming chunks and yield events."""
        async for chunk in self._chunks:
            # Extract usage
            usage_meta = chunk.get("usageMetadata", {})
            if usage_meta:
                self._usage = RequestUsage(
                    input_tokens=usage_meta.get("promptTokenCount", 0),
                    output_tokens=usage_meta.get("candidatesTokenCount", 0),
                )

            # Extract response ID
            if chunk.get("responseId"):
                self.provider_response_id = chunk["responseId"]

            candidates = chunk.get("candidates", [])
            if not candidates:
                continue

            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            for part in parts:
                # Handle thinking part
                if part.get("thought") and part.get("text") is not None:
                    for event in self._parts_manager.handle_thinking_delta(
                        vendor_part_id=None,
                        content=part["text"],
                    ):
                        yield event

                # Handle regular text
                elif part.get("text") is not None and not part.get("thought"):
                    text = part["text"]
                    if len(text) == 0:
                        continue
                    for event in self._parts_manager.handle_text_delta(
                        vendor_part_id=None,
                        content=text,
                    ):
                        yield event

                # Handle function call
                elif part.get("functionCall"):
                    fc = part["functionCall"]

                    # Check if it's a new function call
                    if fc.get("name"):
                        self._current_tool_name = fc["name"]
                        self._current_tool_call_id = (
                            fc.get("id") or generate_tool_call_id()
                        )
                        self._current_vendor_part_id = uuid.uuid4()
                        self._current_args = {}

                    delta_args = {}
                    # Handle partial arguments if present
                    if "partialArgs" in fc:
                        for p_arg in fc["partialArgs"]:
                            json_path = p_arg.get("jsonPath")
                            if json_path and json_path.startswith("$."):
                                value = _extract_partial_value(p_arg)
                                if value is not _MISSING:
                                    _apply_json_path(
                                        self._current_args, json_path[2:], value
                                    )
                                    _apply_json_path(delta_args, json_path[2:], value)

                    elif "args" in fc:
                        delta_args = fc["args"]
                        self._current_args.update(fc["args"])

                    # Yield delta event if we have a current part ID
                    if self._current_vendor_part_id:
                        event = self._parts_manager.handle_tool_call_delta(
                            vendor_part_id=self._current_vendor_part_id,
                            tool_name=self._current_tool_name,
                            args=delta_args,
                            tool_call_id=self._current_tool_call_id,
                        )
                        if event is not None:
                            yield event

    @property
    def model_name(self) -> str:
        return self._model_name_str

    @property
    def provider_name(self) -> str | None:
        return self._provider_name_str

    @property
    def provider_url(self) -> str | None:
        return self._provider_url_str

    @property
    def timestamp(self) -> datetime:
        return self._timestamp_val
