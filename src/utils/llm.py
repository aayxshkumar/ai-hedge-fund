"""Helper functions for LLM"""

import json
import time
from pydantic import BaseModel
from src.llm.models import get_model, get_model_info
from src.utils import llm_status
from src.utils.progress import progress
from src.graph.state import AgentState


def call_llm(
    prompt: any,
    pydantic_model: type[BaseModel],
    agent_name: str | None = None,
    state: AgentState | None = None,
    max_retries: int = 3,
    default_factory=None,
) -> BaseModel:
    """
    Makes an LLM call with retry logic, handling both JSON supported and non-JSON supported models.

    Args:
        prompt: The prompt to send to the LLM
        pydantic_model: The Pydantic model class to structure the output
        agent_name: Optional name of the agent for progress updates and model config extraction
        state: Optional state object to extract agent-specific model configuration
        max_retries: Maximum number of retries (default: 3)
        default_factory: Optional factory function to create default response on failure

    Returns:
        An instance of the specified Pydantic model
    """
    
    # Extract model configuration if state is provided and agent_name is available
    if state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        # Use system defaults when no state or agent_name is provided
        model_name, model_provider = _default_model()

    # Extract API keys from state if available
    api_keys = None
    if state:
        request = state.get("metadata", {}).get("request")
        if request and hasattr(request, 'api_keys'):
            api_keys = request.api_keys

    model_info = get_model_info(model_name, model_provider)
    llm = get_model(model_name, model_provider, api_keys)

    # For non-JSON support models, we can use structured output
    # Command Code's gateway rejects forced tool_choice ("any"/"tool"), which is
    # what with_structured_output relies on. Bind the schema as an ordinary tool
    # (tool_choice auto) instead and fall back to parsing JSON out of the text.
    via_tool_call = model_provider == "Command Code"
    if via_tool_call:
        try:
            llm = llm.bind_tools([pydantic_model], tool_choice="auto")
        except Exception:
            via_tool_call = False
    elif not (model_info and not model_info.has_json_mode()):
        llm = llm.with_structured_output(
            pydantic_model,
            method="json_mode",
        )

    # Inside a usage-limit window every call fails identically: skip the
    # network round-trip and return the default straight away.
    if llm_status.is_limited():
        if agent_name:
            progress.update_status(agent_name, None, "LLM usage limit reached - skipped")
        return default_factory() if default_factory else create_default_response(pydantic_model)

    # Call the LLM with retries
    for attempt in range(max_retries):
        try:
            # Call the LLM
            result = llm.invoke(prompt)
            llm_status.note_success()

            if via_tool_call:
                calls = getattr(result, "tool_calls", None) or []
                if calls:
                    return pydantic_model(**calls[0]["args"])
                parsed_result = extract_json_from_response(content_text(result))
                if parsed_result:
                    return pydantic_model(**parsed_result)
                raise ValueError("model returned neither a tool call nor parseable JSON")
            # For non-JSON support models, we need to extract and parse the JSON manually
            if model_info and not model_info.has_json_mode():
                parsed_result = extract_json_from_response(content_text(result))
                if parsed_result:
                    return pydantic_model(**parsed_result)
            else:
                return result

        except Exception as e:
            if llm_status.note_error(e):
                # Usage window exhausted: retrying cannot help.
                print(f"LLM usage limit reached; skipping retries: {str(e)[:160]}")
                if agent_name:
                    progress.update_status(agent_name, None, "LLM usage limit reached")
                return default_factory() if default_factory else create_default_response(pydantic_model)
            if agent_name:
                progress.update_status(agent_name, None, f"Error - retry {attempt + 1}/{max_retries}")

            if attempt < max_retries - 1:
                backoff = 2 ** attempt
                time.sleep(backoff)

            if attempt == max_retries - 1:
                print(f"Error in LLM call after {max_retries} attempts: {e}")
                # Use default_factory if provided, otherwise create a basic default
                if default_factory:
                    return default_factory()
                return create_default_response(pydantic_model)

    # This should never be reached due to the retry logic above
    return create_default_response(pydantic_model)


def create_default_response(model_class: type[BaseModel]) -> BaseModel:
    """Creates a safe default response based on the model's fields."""
    default_values = {}
    for field_name, field in model_class.model_fields.items():
        if field.annotation == str:
            default_values[field_name] = "Error in analysis, using default"
        elif field.annotation == float:
            default_values[field_name] = 0.0
        elif field.annotation == int:
            default_values[field_name] = 0
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ == dict:
            default_values[field_name] = {}
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ in (list, set, tuple):
            default_values[field_name] = []
        elif field.annotation == bool:
            default_values[field_name] = False
        else:
            # For other types (like Literal), try to use the first allowed value
            if hasattr(field.annotation, "__args__"):
                default_values[field_name] = field.annotation.__args__[0]
            else:
                default_values[field_name] = None

    return model_class(**default_values)


def extract_json_from_response(content: str) -> dict | None:
    """Extracts JSON from a response: a ```json fence first, then any fence,
    then the outermost {...} in plain text."""
    if not content:
        return None
    candidates = []
    for fence in ("```json", "```"):
        start = content.find(fence)
        if start != -1:
            body = content[start + len(fence):]
            end = body.find("```")
            candidates.append(body[:end] if end != -1 else body)
    lo, hi = content.find("{"), content.rfind("}")
    if lo != -1 and hi > lo:
        candidates.append(content[lo:hi + 1])
    for text in candidates:
        try:
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    print("Error extracting JSON from response: no parseable JSON object found")
    return None


def content_text(response) -> str:
    """Plain text of an LLM response. Newer langchain-anthropic returns
    ``content`` as a list of blocks ({"type": "text", "text": ...}); older
    versions and most other providers return a string. Callers that parse
    JSON out of the reply need the string either way."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type", "text") == "text":
                parts.append(str(block.get("text", "")))
            elif hasattr(block, "text"):
                parts.append(str(block.text))
        return "".join(parts)
    return str(content)


def _default_model() -> tuple[str, str]:
    """System default model, overridable from .env so every agent call that is
    not explicitly configured follows the same provider (Command Code by
    default) instead of a hardcoded Anthropic model."""
    import os
    return (
        os.getenv("ALGO_MODEL_NAME", "claude-sonnet-5-5"),
        os.getenv("ALGO_MODEL_PROVIDER", "Command Code"),
    )


def get_agent_model_config(state, agent_name):
    """
    Get model configuration for a specific agent from the state.
    Falls back to global model configuration if agent-specific config is not available.
    Always returns valid model_name and model_provider values.
    """
    request = state.get("metadata", {}).get("request")
    
    if request and hasattr(request, 'get_agent_model_config'):
        # Get agent-specific model configuration
        model_name, model_provider = request.get_agent_model_config(agent_name)
        # Ensure we have valid values
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, 'value') else str(model_provider)
    
    # Fall back to global configuration (system defaults)
    default_name, default_provider = _default_model()
    model_name = state.get("metadata", {}).get("model_name") or default_name
    model_provider = state.get("metadata", {}).get("model_provider") or default_provider
    
    # Convert enum to string if necessary
    if hasattr(model_provider, 'value'):
        model_provider = model_provider.value
    
    return model_name, model_provider
