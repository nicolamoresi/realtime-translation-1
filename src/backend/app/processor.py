# app/processor.py
import os
import logging
import asyncio
import time
from abc import ABC, abstractmethod
from typing import AsyncIterable, AsyncGenerator, Dict, Optional, Any, List

from dotenv import find_dotenv, load_dotenv
from openai import AsyncAzureOpenAI, APIError, RateLimitError, APIConnectionError
from openai.types.chat import ChatCompletion
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Configure logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(find_dotenv())

class AzureOpenAIClient:
    def __init__(self):
        # Initialize client with configuration from environment
        self.client = AsyncAzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", "")
        )
        self.default_model = os.getenv("AZURE_OPENAI_MODEL", "gpt-35-turbo")
        self.available = self._check_configuration()
        self.request_count = 0
        self.last_request_time = 0
        
    def _check_configuration(self) -> bool:
        """Check if the client is properly configured"""
        required_vars = ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"]
        missing = [var for var in required_vars if not os.getenv(var)]
        
        if missing:
            logger.warning(f"Azure OpenAI client missing configuration: {', '.join(missing)}")
            return False
            
        return True
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError))
    )
    async def generate_completion(self, 
                                 prompt: str, 
                                 model: Optional[str] = None,
                                 temperature: float = 0.7,
                                 max_tokens: int = 100) -> ChatCompletion:
        """Generate a completion from Azure OpenAI with proper error handling and retry logic"""
        if not self.available:
            logger.error("Azure OpenAI client not properly configured")
            raise ValueError("Azure OpenAI client not configured")
            
        # Basic rate limiting
        now = time.time()
        if now - self.last_request_time < 0.1:  # No more than 10 requests per second
            await asyncio.sleep(0.1)
            
        self.last_request_time = time.time()
        self.request_count += 1
        
        try:
            response = await self.client.chat.completions.create(
                model=model or self.default_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response
        except RateLimitError as e:
            logger.warning(f"Rate limit reached: {e}")
            raise
        except APIConnectionError as e:
            logger.error(f"API connection error: {e}")
            raise
        except APIError as e:
            logger.error(f"API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in Azure OpenAI call: {e}", exc_info=True)
            raise
            
    async def generate_streaming_completion(self, 
                                           prompt: str,
                                           model: Optional[str] = None,
                                           temperature: float = 0.7,
                                           max_tokens: int = 100) -> AsyncGenerator[str, None]:
        """Generate a streaming completion from Azure OpenAI"""
        if not self.available:
            logger.error("Azure OpenAI client not properly configured")
            raise ValueError("Azure OpenAI client not configured")
            
        # Basic rate limiting
        now = time.time()
        if now - self.last_request_time < 0.1:
            await asyncio.sleep(0.1)
            
        self.last_request_time = time.time()
        self.request_count += 1
        
        try:
            response = await self.client.chat.completions.create(
                model=model or self.default_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )
            
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"Error in streaming completion: {e}", exc_info=True)
            raise
            
    async def translate_text(self,
                            text: str,
                            source_language: str = "auto",
                            target_language: str = "en") -> Optional[str]:
        """Translate text using Azure OpenAI"""
        if not text or not text.strip():
            return None
            
        try:
            # Create a prompt for translation
            prompt = f"""Translate the following text from {source_language} to {target_language}. 
            Return only the translated text without explanations or quotations:
            
            "{text}"
            
            Translation:"""
            
            response = await self.generate_completion(
                prompt=prompt,
                temperature=0.3,  # Lower temperature for more deterministic translations
                max_tokens=len(text.split()) * 2  # Estimate max tokens based on input length
            )
            
            # Extract the translation from the response
            if response.choices and response.choices[0].message.content:
                translation = response.choices[0].message.content.strip()
                return translation
            return None
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return None

class SpeechProcessor:
    def __init__(self):
        # Initialize any speech processing models or services
        self.sample_rate = 16000  # Common sample rate for speech recognition
        self.chunk_size = 4096    # Chunk size for processing
        self.language = "en-US"   # Default language
        
    async def transcribe_audio_stream(self, audio_queue: asyncio.Queue) -> AsyncGenerator[str, None]:
        """Process audio data from queue and generate transcriptions"""
        buffer = bytearray()
        silence_threshold = 0.2  # seconds of silence to consider end of utterance
        max_buffer_time = 10.0   # maximum seconds to buffer before processing
        bytes_per_second = self.sample_rate * 2  # 16-bit audio = 2 bytes per sample
        
        silence_bytes = int(silence_threshold * bytes_per_second)
        max_buffer_bytes = int(max_buffer_time * bytes_per_second)
        
        try:
            while True:
                # Get audio chunk from queue with timeout
                try:
                    chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
                    buffer.extend(chunk)
                    audio_queue.task_done()
                except asyncio.TimeoutError:
                    # No new data, check if we should process the buffer
                    if len(buffer) > silence_bytes:
                        # Process the buffer
                        transcript = await self._process_audio_buffer(bytes(buffer))
                        if transcript:
                            yield transcript
                        buffer.clear()
                    continue
                    
                # Check if buffer exceeds maximum size
                if len(buffer) >= max_buffer_bytes:
                    # Process the buffer
                    transcript = await self._process_audio_buffer(bytes(buffer))
                    if transcript:
                        yield transcript
                    buffer.clear()
                    
        except asyncio.CancelledError:
            logger.info("Audio transcription task cancelled")
            # Process any remaining audio in buffer
            if buffer:
                try:
                    transcript = await self._process_audio_buffer(bytes(buffer))
                    if transcript:
                        yield transcript
                except Exception as e:
                    logger.error(f"Error processing final audio buffer: {e}")
            raise
        except Exception as e:
            logger.error(f"Error in audio transcription stream: {e}", exc_info=True)
            raise
            
    async def _process_audio_buffer(self, audio_data: bytes) -> Optional[str]:
        """Process a buffer of audio data to generate a transcript"""
        # This is a placeholder for actual speech-to-text processing
        # In a real implementation, this would call a speech recognition service
        
        try:
            # Simulate processing time
            await asyncio.sleep(0.1)
            
            # This is where you would call your speech-to-text service
            # For example, using Azure Speech Services or another provider
            
            # For demo purposes, return a dummy transcript
            # Replace with actual implementation
            if len(audio_data) > 1000:  # Only process if we have enough data
                # Just a placeholder - this should use a real STT service
                return "This is a simulated transcript from audio data."
            return None
        except Exception as e:
            logger.error(f"Error processing audio buffer: {e}")
            return None

class BaseProcessor(ABC):
    """Abstract base class for implementing different processors"""
    
    @abstractmethod
    async def process(self, input_data: Any) -> Any:
        """Process input data and return processed output"""
        pass
        
    @abstractmethod
    async def process_stream(self, input_stream: AsyncIterable) -> AsyncGenerator:
        """Process a stream of input data and yield processed outputs"""
        pass