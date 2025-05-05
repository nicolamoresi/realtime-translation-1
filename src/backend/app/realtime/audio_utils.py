"""
Audio processing utilities for Azure real-time translation.

This module provides functions for converting between different audio formats
and encoding/decoding for WebSocket transmission following Azure best practices.
"""

import base64
import tempfile
import subprocess
import logging
from typing import Union

import numpy as np


logger = logging.getLogger(__name__)


def float_to_16bit_pcm(float32_array: np.ndarray) -> np.ndarray:
    """
    Convert a float32 numpy array to signed 16-bit PCM for Azure services.
    
    Args:
        float32_array: Audio signal as float32 numpy array with values in [-1.0, 1.0]
        
    Returns:
        Converted audio signal as int16 numpy array
    """
    int16_array = np.clip(float32_array, -1, 1) * 32767
    return int16_array.astype(np.int16)


def base64_to_array_buffer(base64_string: str) -> np.ndarray:
    """
    Decode a base64 string to a numpy array buffer.
    
    Args:
        base64_string: Base64 encoded audio data
        
    Returns:
        Decoded audio data as uint8 numpy array
    """
    binary_data = base64.b64decode(base64_string)
    return np.frombuffer(binary_data, dtype=np.uint8)


def array_buffer_to_base64(array_buffer: Union[np.ndarray, bytes, bytearray]) -> str:
    """
    Convert an array/bytes with audio data to base64 for Azure Realtime API.
    Ensures correct format: little-endian PCM-16 when a numpy array is supplied.
    
    Args:
        array_buffer: Audio data as numpy array, bytes, or bytearray
        
    Returns:
        Base64 encoded string ready for Azure Realtime API
    """
    if isinstance(array_buffer, np.ndarray):
        # For float arrays, convert to int16 PCM
        if array_buffer.dtype == np.float32:
            array_buffer = float_to_16bit_pcm(array_buffer)
        
        # Critical: Ensure int16 arrays are LITTLE-ENDIAN for Azure
        if array_buffer.dtype == np.int16:
            # '<i2' specifies little-endian 16-bit signed integer
            array_buffer = array_buffer.astype('<i2', copy=False).tobytes()
        else:
            array_buffer = array_buffer.tobytes()
    
    # Already bytes or bytearray
    return base64.b64encode(array_buffer).decode('utf-8')


def merge_int16_arrays(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """
    Concatenate two int16 numpy arrays efficiently, optimized for audio streams.
    
    Args:
        left: First numpy array of dtype int16
        right: Second numpy array of dtype int16
        
    Returns:
        Concatenated numpy array
        
    Raises:
        ValueError: If inputs aren't numpy arrays with dtype int16
    """
    if (isinstance(left, np.ndarray) and left.dtype == np.int16 and 
        isinstance(right, np.ndarray) and right.dtype == np.int16):
        return np.concatenate((left, right))
    else:
        raise ValueError("Both arguments must be numpy arrays of dtype=int16")


def ensure_pcm16le_24khz(raw: bytes) -> bytes:
    """
    Convert any incoming blob (webm / wav / mp3 …) to mono PCM‑16 LE @ 24 kHz,
    the exact format Azure Realtime expects.

    Requires ffmpeg in the container image.
    """
    with tempfile.NamedTemporaryFile(suffix=".in",  delete=False) as fin, \
         tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as fout:
        fin.write(raw)
        fin.flush()

        cmd = [
            "ffmpeg", "-y",                # overwrite
            "-i", fin.name,                # input file
            "-ac", "1",                    # mono
            "-ar", "24000",                # 24 kHz
            "-f", "s16le",                 # raw PCM‑16‑LE
            fout.name,
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            logger.error("ffmpeg stderr: %s", proc.stderr.decode())
            raise RuntimeError("ffmpeg failed to transcode audio")

        fout.seek(0)
        return fout.read()