import os
import io
import base64
import logging
import asyncio
import time
from abc import ABC, abstractmethod
from typing import AsyncIterable, AsyncGenerator, Dict, Optional, Any, Callable, Awaitable

from dotenv import find_dotenv, load_dotenv
from openai import AsyncAzureOpenAI, APIError, RateLimitError, APIConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configure logging
logger = logging.getLogger(__name__)
load_dotenv(find_dotenv())


INTERPRETER_PROMPT = """
You are an interpreter who can help people who speak different languages interact with chinese-speaking people.
Your sole function is to translate the input from the user accurately and with proper grammar, maintaining the original meaning and tone of the message.

Whenever the user speaks in English, you will translate it to Chinese.
Whenever the user speaks in Chinese, you will translate it to English.

Act like an interpreter, DO NOT add, omit, or alter any information.
DO NOT provide explanations, opinions, or any additional text beyond the direct translation.
DO NOT respond to the speakers' questions or asks and DO NOT add your own thoughts. You only need to translate the audio input coming from the two speakers.
You are not aware of any other facts, knowledge, or context beyond the audio input you are translating.
Wait until the speaker is done speaking before you start translating, and translate the entire audio inputs in one go. If the speaker is providing a series of instructions, wait until the end of the instructions before translating.

# Notes
- Handle technical terms literally if no equivalent exists.
- In cases of unclear audio, indicate uncertainty: "[unclear: possible interpretation]".
- ONLY RESPOND WITH THE TRANSLATED TEXT. DO NOT ADD ANY OTHER TEXT, EXPLANATIONS, OR CONTEXTUAL INFORMATION.
""".strip()


class AzureOpenAIClient:
    """Handles Azure OpenAI API connection and basic configuration"""

    def __init__(self):
        # Initialize client with configuration from environment
        self.client = AsyncAzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "")
        )
        self.available = self._check_configuration()

    def _check_configuration(self) -> bool:
        """Check if the client is properly configured"""
        required_vars = ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"]
        missing = [var for var in required_vars if not os.getenv(var)]

        if missing:
            logger.warning(f"Azure OpenAI client missing configuration: {', '.join(missing)}")
            return False
            
        return True


class ProcessingStrategy(ABC):
    """Abstract base strategy for different audio processing operations"""

    @abstractmethod
    async def process(self, data: Any) -> Any:
        """Process the input data according to the strategy"""
        pass


class TranscriptionStrategy(ProcessingStrategy):
    """Strategy for transcribing speech to text using Azure Whisper"""
    
    def __init__(self, client: AzureOpenAIClient):
        self.client = client
        self.model = os.getenv("AZURE_WHISPER_DEPLOYMENT", "whisper")

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError))
    )
    async def process(self, audio_data: bytes) -> Optional[str]:
        """Transcribe audio data to text"""
        if not self.client.available:
            logger.error("Azure OpenAI client not properly configured")
            return None

        try:
            # Create a BytesIO object from the audio data
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"  # Set a filename
            
            # Call Azure OpenAI to transcribe the audio
            result = await self.client.client.audio.transcriptions.create(
                model=self.model,
                file=audio_file
            )

            return result.text
        except RateLimitError as e:
            logger.warning(f"Rate limit hit during transcription: {e}")
            raise
        except APIConnectionError as e:
            logger.error(f"API connection error during transcription: {e}")
            raise
        except APIError as e:
            logger.error(f"Azure API error during transcription: {e}")
            return None
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}", exc_info=True)
            return None


class AudioTranslationStrategy(ProcessingStrategy):
    """Strategy for translating audio directly to another language"""

    def __init__(self, client: AzureOpenAIClient, target_language: str = "en"):
        self.client = client
        self.target_language = target_language
        self.model = os.getenv("AZURE_GPT4O_RT_DEPLOYMENT", "gpt-4o-mini-realtime-preview")

    @retry(
        stop=stop_after_attempt(1),  # Realtime processing should only retry once
        wait=wait_exponential(min=0.5, max=2),
        retry=retry_if_exception_type(APIConnectionError)
    )
    async def process(self, audio_data: bytes) -> Optional[bytes]:
        """Translate audio directly to another language"""
        if not self.client.available:
            logger.error("Azure OpenAI client not properly configured")
            return None

        try:
            max_size = 25 * 1024 * 1024  # 25MB

            if len(audio_data) > max_size:
                logger.warning(f"Audio data size ({len(audio_data)} bytes) exceeds maximum limit, truncating")
                audio_data = audio_data[:max_size]

            # Log the size being sent to Azure
            logger.info(f"Sending {len(audio_data) / 1024:.2f} KB of audio data to Azure Real-time API")

            # Use Azure real-time API
            start_time = time.time()

            async with self.client.client.beta.realtime.connect(
                model=self.model
            ) as conn:
                await conn.session.update(session={"modalities": ["audio"]})
                await conn.conversation.item.create(item={
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "text", "text": INTERPRETER_PROMPT},
                        {"type": "input_audio", "audio": base64.b64encode(audio_data).decode()}
                    ]
                })

                await conn.response.create()
                output_audio = bytearray()

                async for event in conn:
                    if event.type == "response.audio.delta":
                        output_audio.extend(base64.b64decode(event.delta))
                    elif event.type == "response.done":
                        break

                processing_time = time.time() - start_time
                logger.info(f"Audio translation completed in {processing_time:.3f}s: {len(output_audio)} bytes generated from {len(audio_data)} input bytes")

                if len(output_audio) < 100 and len(audio_data) > 1000:
                    logger.warning(f"Suspiciously small output ({len(output_audio)} bytes) from large input ({len(audio_data)} bytes)")

                return bytes(output_audio)

        except RateLimitError as e:
            logger.warning(f"Rate limit hit during audio translation: {e}")
            return None
        except APIConnectionError as e:
            logger.error(f"API connection error during audio translation: {e}")
            raise
        except Exception as e:
            logger.error(f"Error translating audio: {e}", exc_info=True)
            return None


class TextTranslationStrategy(ProcessingStrategy):
    """Strategy for translating text using Azure OpenAI"""
    
    def __init__(self, client: AzureOpenAIClient, target_language: str = "en"):
        self.client = client
        self.target_language = target_language
        self.model = os.getenv("AZURE_GPT4O_TEXT_DEPLOYMENT", "gpt-4o")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError))
    )
    async def process(self, text: str) -> Optional[str]:
        """Translate text to target language"""
        if not self.client.available or not text or not text.strip():
            return None
        
        try:
            # Create a prompt for translation
            prompt = f"""Translate the following text to {self.target_language}. 
            Return only the translated text without explanations or quotations:
            
            "{text}"
            
            Translation:"""
            
            # Track performance for monitoring
            start_time = time.time()
            
            response = await self.client.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # Lower temperature for more deterministic translations
                max_tokens=len(text.split()) * 2  # Estimate max tokens based on input length
            )
            
            elapsed = time.time() - start_time
            logger.debug(f"Text translation took {elapsed:.3f}s: {len(text)} chars")
            
            # Extract the translation from the response
            if response.choices and response.choices[0].message.content:
                translation = response.choices[0].message.content.strip()
                return translation
            return None
        except RateLimitError as e:
            logger.warning(f"Rate limit hit during text translation: {e}")
            raise
        except APIConnectionError as e:
            logger.error(f"API connection error during text translation: {e}")
            raise
        except Exception as e:
            logger.error(f"Text translation error: {e}")
            return None


class SpeechProcessor:
    """
    Orchestrates multiple processing strategies to handle speech processing:
    1. Transcription and text translation for captions
    2. Direct audio translation for real-time speech
    
    Follows Azure best practices for performance, error handling, and resource management
    """

    def __init__(self, target_language: str = "en", audio_only: bool = True):
        self.client = AzureOpenAIClient()
        self.target_language = target_language
        self.audio_only = audio_only
        self.audio_translation_strategy = AudioTranslationStrategy(self.client, target_language)
        if not audio_only:
            self.transcription_strategy = TranscriptionStrategy(self.client)
            self.text_translation_strategy = TextTranslationStrategy(self.client, target_language)

    async def process(self, audio_data: bytes) -> Dict[str, Any]:
        """
        Process audio data with operations based on mode:
        1. Audio-only mode: Only direct audio translation via GPT-4o Realtime
        2. Full mode: Audio translation + Transcription & text translation

        Returns a dictionary with results based on processing mode
        """
        if not audio_data:
            return {"original_text": None, "translated_text": None, "audio": None}

        start_time = time.time()

        if self.audio_only:
            try:
                # Only process audio translation
                translated_audio = await self.audio_translation_strategy.process(audio_data)
                
                # Log performance for audio-only mode
                total_time = time.time() - start_time
                logger.info(f"Audio-only processing completed in {total_time:.3f}s")
                
                return {
                    "original_text": None, 
                    "translated_text": None, 
                    "audio": translated_audio
                }
            except Exception as e:
                logger.error(f"Error in audio-only processing: {e}", exc_info=True)
                return {"original_text": None, "translated_text": None, "audio": None}
        
        # Full processing mode with transcription and translation
        try:
            # Verify strategies are initialized for full mode
            if not hasattr(self, 'transcription_strategy') or not hasattr(self, 'text_translation_strategy'):
                logger.error("Transcription strategies not initialized but required for full processing mode")
                return {"original_text": None, "translated_text": None, "audio": None}
                
            # Create tasks for parallel processing
            transcription_task = self.transcription_strategy.process(audio_data)
            audio_translation_task = self.audio_translation_strategy.process(audio_data)
            
            # Run tasks in parallel with timeout protection
            results = await asyncio.gather(
                transcription_task,
                audio_translation_task,
                return_exceptions=True
            )
            
            # Extract results safely
            transcription = results[0] if not isinstance(results[0], Exception) else None
            translated_audio = results[1] if not isinstance(results[1], Exception) else None
            
            # Log any exceptions for monitoring
            for i, item in enumerate(results):
                if isinstance(item, Exception):
                    logger.error(f"Task {i} failed: {item}")
        except Exception as e:
            logger.error(f"Error in parallel processing: {e}", exc_info=True)
            transcription = None
            translated_audio = None
        
        # Prepare result dictionary
        result: Dict[str, Optional[Any]] = {"original_text": None, "translated_text": None, "audio": None}
        
        # Handle transcription result
        if isinstance(transcription, str):
            result["original_text"] = transcription
            
            # Translate the transcription
            try:
                translated_text = await self.text_translation_strategy.process(transcription)
                if translated_text:
                    result["translated_text"] = translated_text
            except Exception as e:
                logger.error(f"Error translating transcription: {e}")
        
        # Handle audio translation result
        if translated_audio:
            result["audio"] = translated_audio
        
        # Log performance metrics
        total_time = time.time() - start_time
        success_count = sum(1 for v in result.values() if v is not None)
        logger.info(f"Audio processing completed in {total_time:.3f}s with {success_count}/3 successful operations")
        
        return result
