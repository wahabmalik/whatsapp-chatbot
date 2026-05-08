from __future__ import annotations

from openai import OpenAI
import shelve
from dotenv import load_dotenv
import inspect
import os
import time
import logging
import random
from threading import Lock
from typing import Callable, TypedDict

from app.services.observability import sanitize_text

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
_client_lock = Lock()
client = OpenAI(api_key=OPENAI_API_KEY)

POLL_INTERVAL_SECONDS = float(os.getenv("OPENAI_POLL_INTERVAL_SECONDS", "0.5"))
RUN_TIMEOUT_SECONDS = float(os.getenv("OPENAI_RUN_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "2"))
RETRY_BACKOFF_SECONDS = float(os.getenv("OPENAI_RETRY_BACKOFF_SECONDS", "0.5"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_SYSTEM_PROMPT = os.getenv(
    "OPENAI_SYSTEM_PROMPT",
    "You are a helpful WhatsApp assistant. Be concise and friendly.",
)

TERMINAL_FAILURE_STATUSES = {"failed", "cancelled", "expired", "incomplete"}


def refresh_openai_client(api_key: str | None = None) -> OpenAI:
    global OPENAI_API_KEY, client

    OPENAI_API_KEY = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
    with _client_lock:
        client = OpenAI(api_key=OPENAI_API_KEY)
        return client


class AIReplyResult(TypedDict):
    ok: bool
    status: str
    reply_text: str | None
    confidence: float | None
    metadata: dict
    error_code: str | None
    error_detail: str | None


def upload_file(path):
    # Upload a file with an "assistants" purpose
    file = client.files.create(
        file=open("../../data/airbnb-faq.pdf", "rb"), purpose="assistants"
    )


def create_assistant(file):
    """
    You currently cannot set the temperature for Assistant via the API.
    """
    assistant = client.beta.assistants.create(
        name="WhatsApp AirBnb Assistant",
        instructions="You're a helpful WhatsApp assistant that can assist guests that are staying in our Paris AirBnb. Use your knowledge base to best respond to customer queries. If you don't know the answer, say simply that you cannot help with question and advice to contact the host directly. Be friendly and funny.",
        tools=[{"type": "retrieval"}],
        model="gpt-4-1106-preview",
        file_ids=[file.id],
    )
    return assistant


# Use context manager to ensure the shelf file is closed properly
def check_if_thread_exists(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id, None)


def store_thread(wa_id, thread_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[wa_id] = thread_id


def run_assistant(thread, name):
    if not OPENAI_ASSISTANT_ID:
        raise RuntimeError("OPENAI_ASSISTANT_ID is not configured")

    # Retrieve the Assistant
    assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)

    run = _create_run_with_retries(thread.id, assistant.id)
    run = _wait_for_terminal_run_state(thread.id, run.id)

    if run.status in TERMINAL_FAILURE_STATUSES:
        raise RuntimeError(f"Assistant run failed with status={run.status}")

    if run.status != "completed":
        raise RuntimeError(f"Assistant run ended unexpectedly with status={run.status}")

    # Retrieve the Messages
    messages = _messages_with_retries(thread.id)
    new_message = messages.data[0].content[0].text.value
    logging.info(f"Generated message: {new_message}")
    return new_message


def _sleep_with_backoff(attempt: int) -> None:
    jitter = random.uniform(0, 0.1)
    delay = (RETRY_BACKOFF_SECONDS * (2**attempt)) + jitter
    time.sleep(delay)


def _is_retryable_exception(exc: Exception) -> bool:
    retryable_names = {"RateLimitError", "APIConnectionError", "APITimeoutError"}
    if exc.__class__.__name__ in retryable_names:
        return True

    message = str(exc).lower()
    return any(token in message for token in ("timeout", "tempor", "rate limit", "connection"))


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if exc.__class__.__name__ in {"APITimeoutError", "TimeoutError"}:
        return True
    return "timeout" in str(exc).lower() or "timed out" in str(exc).lower()


def _is_auth_exception(exc: Exception) -> bool:
    if exc.__class__.__name__ in {"AuthenticationError", "PermissionDeniedError"}:
        return True
    message = str(exc).lower()
    return any(
        token in message
        for token in ("unauthorized", "authentication", "invalid api key", "forbidden")
    )


def _is_rate_limited_exception(exc: Exception) -> bool:
    if exc.__class__.__name__ == "RateLimitError":
        return True
    message = str(exc).lower()
    return "rate limit" in message or "too many requests" in message


def _classify_ai_exception(exc: Exception) -> tuple[str, str]:
    if _is_timeout_exception(exc):
        return "timeout", "timeout"
    if _is_auth_exception(exc):
        return "auth_error", "auth_error"
    if _is_rate_limited_exception(exc):
        return "rate_limited", "rate_limited"
    return "provider_error", "provider_error"


def _increment_metrics(metrics, key: str) -> bool:
    """Increment a metrics counter safely.
    
    Returns:
        True if successful, False if metrics operation failed.
    """
    if metrics is None:
        return True
    try:
        metrics.increment(key)
        return True
    except Exception as exc:
        logging.warning("AI metrics increment failed key=%s error=%s", key, exc)
        return False


def _observe_reply_duration(metrics, duration_seconds: float) -> bool:
    """Observe reply duration safely.
    
    Returns:
        True if successful, False if metrics operation failed.
    """
    if metrics is None:
        return True
    try:
        metrics.observe_duration("ai.reply_duration", max(0.0, duration_seconds))
        return True
    except Exception as exc:
        logging.warning("AI metrics duration observe failed error=%s", exc)
        return False


def _safe_elapsed_seconds(started_at: float) -> float:
    try:
        return max(0.0, time.monotonic() - started_at)
    except Exception:
        return 0.0


def _sanitize_error_detail(exc: Exception, limit: int = 300) -> str:
    detail = sanitize_text(str(exc))
    if len(detail) <= limit:
        return detail
    return detail[:limit] + "..."


def _call_provider_with_optional_agent_context(
    provider: Callable,
    message_text: str,
    wa_id: str,
    name: str,
    agent_context: dict | None,
) -> str:
    """Call provider with agent context if supported, else 3-arg fallback.

    Supports:
    - 4-argument: provider(message_text, wa_id, name, agent_context)
    - 3-argument: provider(message_text, wa_id, name)

    Explicitly checks for "agent_context" parameter to avoid unintended
    behavior with permissive signatures (e.g., Mock objects).
    """
    accepts_agent_context = False

    try:
        signature = inspect.signature(provider)
        params = list(signature.parameters.values())
        accepts_agent_context = any(param.name == "agent_context" for param in params)
    except (TypeError, ValueError):
        # Cannot inspect; assume 3-arg contract
        pass

    if accepts_agent_context:
        try:
            return provider(message_text, wa_id, name, agent_context)
        except TypeError as exc:
            # Fallback: signature inspection was wrong or runtime constraint
            logging.debug("4-arg provider call failed, retrying 3-arg: %s", exc)
            try:
                return provider(message_text, wa_id, name)
            except TypeError:
                raise

    return provider(message_text, wa_id, name)


def generate_reply_result(
    message_text: str,
    wa_id: str,
    name: str,
    agent_context: dict | None = None,
    request_id: str | None = None,
    provider: Callable[[str, str, str], str] | None = None,
    metrics=None,
) -> AIReplyResult:
    started_at = time.monotonic()
    metrics_ok = _increment_metrics(metrics, "ai.reply_attempt")

    active_provider = provider or generate_response
    metadata = {
        "request_id": request_id,
        "agent": (agent_context or {}).get("name"),
        "attempts": 1,
        "provider": "openai",
        "assistant_id": None,
        "model": OPENAI_MODEL,
        "duration_seconds": 0.0,
    }
    result: AIReplyResult

    try:
        reply_text = _call_provider_with_optional_agent_context(
            active_provider,
            message_text,
            wa_id,
            name,
            agent_context,
        )
        
        # If metrics failed on attempt, treat as controlled failure
        if not metrics_ok:
            logging.warning(
                "AI reply blocked by metrics failure request_id=%s",
                request_id,
            )
            result = {
                "ok": False,
                "status": "metrics_error",
                "reply_text": None,
                "confidence": None,
                "metadata": metadata,
                "error_code": "metrics_error",
                "error_detail": "Metrics collection failed; request aborted",
            }
        else:
            result = {
                "ok": True,
                "status": "success",
                "reply_text": reply_text,
                "confidence": None,
                "metadata": metadata,
                "error_code": None,
                "error_detail": None,
            }
            _increment_metrics(metrics, "ai.reply_success")
    except Exception as exc:  # pragma: no cover - provider behavior
        status, error_code = _classify_ai_exception(exc)
        _increment_metrics(metrics, f"ai.reply_{status}")
        safe_detail = _sanitize_error_detail(exc)
        logging.warning(
            "AI reply failed status=%s request_id=%s error=%s",
            status,
            request_id,
            safe_detail,
        )
        result = {
            "ok": False,
            "status": status,
            "reply_text": None,
            "confidence": None,
            "metadata": metadata,
            "error_code": error_code,
            "error_detail": safe_detail,
        }
    finally:
        duration = _safe_elapsed_seconds(started_at)
        metadata["duration_seconds"] = duration
        _observe_reply_duration(metrics, duration)

    return result


def _create_run_with_retries(thread_id: str, assistant_id: str):
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=assistant_id,
            )
        except Exception as exc:  # pragma: no cover - network behavior
            last_exc = exc
            if attempt >= MAX_RETRIES or not _is_retryable_exception(exc):
                raise
            logging.warning("Retrying run.create attempt=%s due to %s", attempt + 1, exc)
            _sleep_with_backoff(attempt)

    raise RuntimeError(f"Failed to create run: {last_exc}")


def _retrieve_run_with_retries(thread_id: str, run_id: str):
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        except Exception as exc:  # pragma: no cover - network behavior
            last_exc = exc
            if attempt >= MAX_RETRIES or not _is_retryable_exception(exc):
                raise
            logging.warning("Retrying run.retrieve attempt=%s due to %s", attempt + 1, exc)
            _sleep_with_backoff(attempt)

    raise RuntimeError(f"Failed to retrieve run: {last_exc}")


def _messages_with_retries(thread_id: str):
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.beta.threads.messages.list(thread_id=thread_id)
        except Exception as exc:  # pragma: no cover - network behavior
            last_exc = exc
            if attempt >= MAX_RETRIES or not _is_retryable_exception(exc):
                raise
            logging.warning("Retrying messages.list attempt=%s due to %s", attempt + 1, exc)
            _sleep_with_backoff(attempt)

    raise RuntimeError(f"Failed to list messages: {last_exc}")


def _wait_for_terminal_run_state(thread_id: str, run_id: str):
    deadline = time.monotonic() + RUN_TIMEOUT_SECONDS
    while True:
        run = _retrieve_run_with_retries(thread_id=thread_id, run_id=run_id)
        if run.status == "completed" or run.status in TERMINAL_FAILURE_STATUSES:
            return run

        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Assistant run timed out after {RUN_TIMEOUT_SECONDS}s with status={run.status}"
            )

        time.sleep(POLL_INTERVAL_SECONDS)


def generate_response(message_body, wa_id, name, agent_context: dict | None = None) -> str:
    """Generate response using OpenAI API with optional agent context.

    Args:
        message_body: User message text.
        wa_id: WhatsApp user ID.
        name: User display name.
        agent_context: Optional dict with agent metadata (name, title, description).
                      If provided, agent persona is included in system prompt.

    Returns:
        Generated response text from OpenAI.
    """
    logging.info("Generating chat completion wa_id=%s model=%s", wa_id, OPENAI_MODEL)
    system_prompt = OPENAI_SYSTEM_PROMPT

    # Inject agent persona into system prompt if context provided
    if agent_context and isinstance(agent_context, dict):
        persona_parts = []
        for key in ("name", "title", "description"):
            val = str(agent_context.get(key) or "").strip()
            if val:
                persona_parts.append(val)

        if persona_parts:
            system_prompt = (
                f"{OPENAI_SYSTEM_PROMPT}\n"
                f"Active support agent persona: {' | '.join(persona_parts)}. "
                "Answer in a style that matches this persona while staying accurate and concise."
            )
            logging.info(
                "Agent persona injected into system prompt wa_id=%s agent=%s",
                wa_id,
                agent_context.get("name", "unknown"),
            )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message_body},
        ],
        max_tokens=500,
        timeout=10,
    )
    new_message = response.choices[0].message.content.strip()
    logging.info("Generated message: %s", new_message[:120])
    return new_message
