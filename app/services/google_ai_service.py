"""
Google AI / Gemini API Service
Provides a unified interface for Google's Generative AI models
"""

from __future__ import annotations

from dotenv import load_dotenv
import os
import time
import logging
import random

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - optional dependency in some environments
    genai = None

load_dotenv()

GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY")
_is_google_ai_configured = False

# Configuration for retry logic
MAX_RETRIES = int(os.getenv("GOOGLE_AI_MAX_RETRIES", "2"))
RETRY_BACKOFF_SECONDS = float(os.getenv("GOOGLE_AI_RETRY_BACKOFF_SECONDS", "0.5"))

logger = logging.getLogger(__name__)


def _ensure_google_ai_configured() -> None:
    global _is_google_ai_configured
    if _is_google_ai_configured:
        return

    if genai is None:
        raise GoogleAIError(
            "google-generativeai package is not installed. Install it before using Google AI service."
        )

    if not GOOGLE_AI_API_KEY:
        raise GoogleAIError("GOOGLE_AI_API_KEY is not configured. Please set it in your .env file")

    genai.configure(api_key=GOOGLE_AI_API_KEY)
    _is_google_ai_configured = True


class GoogleAIError(Exception):
    """Base exception for Google AI service errors"""
    pass


class GoogleAIClient:
    """Client for interacting with Google's Generative AI models"""
    
    # Available models
    GEMINI_PRO = "gemini-pro"
    GEMINI_PRO_VISION = "gemini-pro-vision"
    GEMINI_ULTRA = "gemini-ultra"
    
    def __init__(self, model: str = GEMINI_PRO):
        """
        Initialize the Google AI client
        
        Args:
            model: The model to use (default: gemini-pro)
        """
        _ensure_google_ai_configured()
        self.model_name = model
        self.model = genai.GenerativeModel(model)
    
    def generate_text(self, prompt: str, temperature: float = 0.7, max_output_tokens: int = 1000) -> str:
        """
        Generate text response from a prompt
        
        Args:
            prompt: The input prompt
            temperature: Controls randomness (0-1), higher = more creative
            max_output_tokens: Maximum tokens in response
            
        Returns:
            Generated text response
        """
        try:
            response = self._generate_with_retries(
                prompt=prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens
            )
            return response.text
        except Exception as e:
            logger.error(f"Error generating text: {e}")
            raise GoogleAIError(f"Failed to generate text: {str(e)}") from e
    
    def generate_response_for_chat(self, messages: list[dict], temperature: float = 0.7, max_output_tokens: int = 1000) -> str:
        """
        Generate response from chat message history
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Controls randomness (0-1)
            max_output_tokens: Maximum tokens in response
            
        Returns:
            Generated response
        """
        try:
            chat = self.model.start_chat()
            for msg in messages[:-1]:
                chat.send_message(msg["content"])
            
            response = chat.send_message(
                messages[-1]["content"],
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_output_tokens
                )
            )
            return response.text
        except Exception as e:
            logger.error(f"Error in chat response: {e}")
            raise GoogleAIError(f"Failed to generate chat response: {str(e)}") from e
    
    def _generate_with_retries(self, prompt: str, temperature: float = 0.7, max_output_tokens: int = 1000):
        """
        Generate response with retry logic for transient failures
        
        Args:
            prompt: The input prompt
            temperature: Controls randomness
            max_output_tokens: Maximum tokens
            
        Returns:
            Generation response object
        """
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        top_k=40,
                        top_p=0.95
                    )
                )
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable_exception(exc):
                    raise
                
                if attempt < MAX_RETRIES:
                    self._sleep_with_backoff(attempt)
                    logger.debug(f"Retrying after error (attempt {attempt + 1}): {exc}")
                else:
                    logger.error(f"Max retries exceeded for prompt: {str(exc)}")
        
        raise last_exc or GoogleAIError("Unknown error after retries")
    
    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        """
        Determine if exception is retryable
        
        Args:
            exc: The exception to check
            
        Returns:
            True if the exception is retryable
        """
        retryable_names = {
            "ResourceExhausted",
            "DeadlineExceeded",
            "Unavailable",
            "InternalServerError",
            "ServiceUnavailable"
        }
        if exc.__class__.__name__ in retryable_names:
            return True
        
        message = str(exc).lower()
        return any(token in message for token in ("timeout", "rate limit", "unavailable", "try again"))
    
    @staticmethod
    def _sleep_with_backoff(attempt: int) -> None:
        """
        Sleep with exponential backoff and jitter
        
        Args:
            attempt: The attempt number (0-indexed)
        """
        jitter = random.uniform(0, 0.1)
        delay = (RETRY_BACKOFF_SECONDS * (2 ** attempt)) + jitter
        time.sleep(delay)


# Singleton instance
_client: GoogleAIClient | None = None


def get_client(model: str = GoogleAIClient.GEMINI_PRO) -> GoogleAIClient:
    """
    Get or create a Google AI client
    
    Args:
        model: The model to use
        
    Returns:
        GoogleAIClient instance
    """
    global _client
    if _client is None:
        _client = GoogleAIClient(model=model)
    return _client


def generate_text(prompt: str, temperature: float = 0.7, max_output_tokens: int = 1000) -> str:
    """
    Quick function to generate text
    
    Args:
        prompt: The input prompt
        temperature: Controls randomness
        max_output_tokens: Maximum tokens
        
    Returns:
        Generated text
    """
    client = get_client()
    return client.generate_text(prompt, temperature, max_output_tokens)


def generate_chat_response(messages: list[dict], temperature: float = 0.7, max_output_tokens: int = 1000) -> str:
    """
    Quick function to generate chat response
    
    Args:
        messages: Chat message history
        temperature: Controls randomness
        max_output_tokens: Maximum tokens
        
    Returns:
        Generated response
    """
    client = get_client()
    return client.generate_response_for_chat(messages, temperature, max_output_tokens)
