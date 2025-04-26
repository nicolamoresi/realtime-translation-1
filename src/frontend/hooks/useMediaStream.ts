import { useCallback, useEffect, useRef, useState } from 'react';
import { getSupportedMimeType } from '@/utils/mediaUtils';

/**
 * Interface defining options for media streaming
 */
interface MediaStreamOptions {
  enabled: boolean;
  audioWS: WebSocket | null;
  videoWS: WebSocket | null;
  videoPath: string;
  audioChunkDuration?: number;
  videoFrameInterval?: number;
  videoQuality?: number;
  onError?: (error: string) => void;
}

/**
 * Interface for tracking streaming statistics
 */
interface StreamStats {
  audioChunks: number;
  audioBytes: number;
  videoFrames: number;
  videoBytes: number;
  startTime: number;
  lastUpdate: number;
}

/**
 * Hook for streaming media from a video file to WebSockets
 */
export function useMediaStream({
  enabled,
  audioWS,
  videoWS,
  videoPath,
  audioChunkDuration = 250,
  videoFrameInterval = 200,
  videoQuality = 0.7,
  onError
}: MediaStreamOptions) {
  // State and refs
  const [isStreaming, setIsStreaming] = useState(false);
  const instanceId = useRef(`media-stream-${Math.random().toString(36).substring(2, 9)}`);
  const videoElementRef = useRef<HTMLVideoElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const frameIntervalRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const cleanupFunctionsRef = useRef<Array<() => void>>([]);
  const isInitializedRef = useRef(false);
  const isCleaningUpRef = useRef(false);
  const lastErrorRef = useRef<string | null>(null);
  
  // Track data transmission statistics
  const statsRef = useRef<StreamStats>({
    audioChunks: 0,
    audioBytes: 0,
    videoFrames: 0,
    videoBytes: 0,
    startTime: Date.now(),
    lastUpdate: Date.now()
  });

  /**
   * Log streaming statistics
   */
  const logStreamingStats = useCallback(() => {
    const now = Date.now();
    const stats = statsRef.current;
    const elapsedSeconds = (now - stats.startTime) / 1000;
    
    if (elapsedSeconds < 1) return; // Don't log if less than 1 second has passed
    
    console.log(`[${instanceId.current}] Media Streaming Stats:`, {
      duration: `${elapsedSeconds.toFixed(1)}s`,
      audioChunks: stats.audioChunks,
      audioBytes: `${(stats.audioBytes / 1024).toFixed(1)} KB`,
      audioRate: `${(stats.audioBytes / elapsedSeconds / 1024).toFixed(1)} KB/s`,
      videoFrames: stats.videoFrames,
      videoBytes: `${(stats.videoBytes / 1024).toFixed(1)} KB`,
      videoRate: `${(stats.videoBytes / elapsedSeconds / 1024).toFixed(1)} KB/s`,
      videoFPS: (stats.videoFrames / elapsedSeconds).toFixed(1),
      audioWS: audioWS ? `Connected (${audioWS.readyState})` : 'Not connected',
      videoWS: videoWS ? `Connected (${videoWS.readyState})` : 'Not connected'
    });
    
    stats.lastUpdate = now;
  }, [audioWS, videoWS]);
  
  /**
   * Send audio data through WebSocket
   */
  const sendAudioData = useCallback((data: ArrayBuffer): boolean => {
    if (!audioWS || audioWS.readyState !== WebSocket.OPEN) {
      return false;
    }
    
    try {
      audioWS.send(data);
      statsRef.current.audioChunks++;
      statsRef.current.audioBytes += data.byteLength;
      return true;
    } catch (err) {
      console.error(`[${instanceId.current}] Error sending audio data:`, err);
      return false;
    }
  }, [audioWS]);
  
  /**
   * Send video data through WebSocket
   */
  const sendVideoData = useCallback((data: ArrayBuffer): boolean => {
    if (!videoWS || videoWS.readyState !== WebSocket.OPEN) {
      return false;
    }
    
    try {
      videoWS.send(data);
      statsRef.current.videoFrames++;
      statsRef.current.videoBytes += data.byteLength;
      return true;
    } catch (err) {
      console.error(`[${instanceId.current}] Error sending video data:`, err);
      return false;
    }
  }, [videoWS]);
  
  /**
   * Handle errors during streaming
   */
  const handleStreamingError = useCallback((error: unknown) => {
    const errorMessage = error instanceof Error ? error.message : String(error);
    
    // Avoid reporting the same error multiple times
    if (lastErrorRef.current === errorMessage) {
      return;
    }
    
    console.error(`[${instanceId.current}] Streaming error:`, error);
    lastErrorRef.current = errorMessage;
    onError?.(errorMessage);
  }, [onError]);
  
  /**
   * Clean up all media resources
   */
  const cleanupMedia = useCallback(() => {
    // Prevent multiple simultaneous cleanups
    if (isCleaningUpRef.current) {
      return;
    }
    
    isCleaningUpRef.current = true;
    console.log(`[${instanceId.current}] Cleaning up media resources`);
    setIsStreaming(false);
    
    // Log final stats if we were streaming
    if (statsRef.current.startTime > 0 && statsRef.current.audioChunks + statsRef.current.videoFrames > 0) {
      logStreamingStats();
    }
    
    // Run all registered cleanup functions
    cleanupFunctionsRef.current.forEach(cleanup => {
      try {
        cleanup();
      } catch (err) {
        console.warn(`[${instanceId.current}] Error in cleanup function:`, err);
      }
    });
    cleanupFunctionsRef.current = [];
    
    // Stop media recorder
    if (mediaRecorderRef.current) {
      try {
        if (mediaRecorderRef.current.state !== 'inactive') {
          mediaRecorderRef.current.stop();
        }
      } catch (err) {
        console.warn(`[${instanceId.current}] Error stopping MediaRecorder:`, err);
      }
      mediaRecorderRef.current = null;
    }
    
    // Clear frame interval
    if (frameIntervalRef.current !== null) {
      window.clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }
    
    // Stop all tracks in the stream
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => {
        try {
          track.stop();
        } catch (err) {
          console.warn(`[${instanceId.current}] Error stopping track:`, err);
        }
      });
      streamRef.current = null;
    }
    
    // Remove canvas
    if (canvasRef.current) {
      try {
        document.body.removeChild(canvasRef.current);
      } catch (e) {
        // Canvas might have been already removed
      }
      canvasRef.current = null;
    }
    
    // Remove video element
    if (videoElementRef.current) {
      try {
        videoElementRef.current.pause();
        videoElementRef.current.removeAttribute('src');
        videoElementRef.current.load();
        videoElementRef.current.srcObject = null;
        
        try {
          document.body.removeChild(videoElementRef.current);
        } catch (e) {
          // Element might have been already removed
        }
      } catch (err) {
        console.warn(`[${instanceId.current}] Error cleaning up video element:`, err);
      }
      videoElementRef.current = null;
    }
    
    // Reset flags
    isInitializedRef.current = false;
    isCleaningUpRef.current = false;
    lastErrorRef.current = null;
  }, [logStreamingStats]);
  
  /**
   * Initialize and start media streaming
   */
  const startMediaStreaming = useCallback(async (): Promise<boolean> => {
    if (isInitializedRef.current) {
      console.log(`[${instanceId.current}] Streaming already initialized, skipping`);
      return true;
    }
    
    if (!audioWS || !videoWS || 
        audioWS.readyState !== WebSocket.OPEN || 
        videoWS.readyState !== WebSocket.OPEN) {
      console.warn(`[${instanceId.current}] Cannot start streaming - WebSockets not open`);
      return false;
    }
    
    try {
      console.log(`[${instanceId.current}] Starting media streaming initialization...`);
      isInitializedRef.current = true;
      
      // Reset statistics
      statsRef.current = {
        audioChunks: 0,
        audioBytes: 0,
        videoFrames: 0,
        videoBytes: 0,
        startTime: Date.now(),
        lastUpdate: Date.now()
      };
      
      // Test WebSocket connections with small packets
      const testAudio = sendAudioData(new Uint8Array([1, 2, 3, 4]).buffer);
      const testVideo = sendVideoData(new Uint8Array([5, 6, 7, 8]).buffer);
      
      if (!testAudio || !testVideo) {
        throw new Error('WebSocket connection test failed');
      }
      
      // Create video element for the sample video
      console.log(`[${instanceId.current}] Creating video element for sample file:`, videoPath);
      const videoElement = document.createElement('video');
      videoElement.src = videoPath;
      videoElement.muted = true;
      videoElement.loop = true;
      videoElement.crossOrigin = 'anonymous';
      videoElement.style.display = 'none';
      videoElement.preload = 'auto';
      document.body.appendChild(videoElement);
      videoElementRef.current = videoElement;
      
      // Setup video error handler
      const handleVideoError = (e: Event) => {
        const error = videoElement.error;
        const message = error ? 
          `Video error: ${error.code} ${error.message || ''}` : 
          'Unknown video error';
        handleStreamingError(message);
      };
      
      videoElement.addEventListener('error', handleVideoError);
      cleanupFunctionsRef.current.push(() => {
        videoElement.removeEventListener('error', handleVideoError);
      });
      
      // Wait for video to be ready
      if (videoElement.readyState < 2) {
        console.log(`[${instanceId.current}] Waiting for video to load...`);
        await new Promise<void>((resolve, reject) => {
          const loadHandler = () => {
            videoElement.removeEventListener('loadeddata', loadHandler);
            videoElement.removeEventListener('error', errorHandler);
            resolve();
          };
          
          const errorHandler = () => {
            videoElement.removeEventListener('loadeddata', loadHandler);
            videoElement.removeEventListener('error', errorHandler);
            reject(new Error(`Failed to load video: ${videoElement.error?.message || 'Unknown error'}`));
          };
          
          videoElement.addEventListener('loadeddata', loadHandler);
          videoElement.addEventListener('error', errorHandler);
          
          // Add timeout to prevent hanging
          const timeoutId = setTimeout(() => {
            videoElement.removeEventListener('loadeddata', loadHandler);
            videoElement.removeEventListener('error', errorHandler);
            reject(new Error('Video loading timed out'));
          }, 10000);
          
          cleanupFunctionsRef.current.push(() => {
            clearTimeout(timeoutId);
            videoElement.removeEventListener('loadeddata', loadHandler);
            videoElement.removeEventListener('error', errorHandler);
          });
        });
      }
      
      // Start video playback
      console.log(`[${instanceId.current}] Starting video playback...`);
      await videoElement.play();
      
      console.log(`[${instanceId.current}] Video playing, dimensions:`, 
        videoElement.videoWidth, 'x', videoElement.videoHeight);
      
      // Create canvas for video frame capture
      const canvas = document.createElement('canvas');
      canvas.width = videoElement.videoWidth || 640;
      canvas.height = videoElement.videoHeight || 480;
      canvas.style.display = 'none';
      document.body.appendChild(canvas);
      canvasRef.current = canvas;
      
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        throw new Error('Could not get canvas context');
      }
      
      // Capture stream from the video element
      const stream = videoElement.captureStream();
      if (!stream) {
        throw new Error('Failed to capture video stream');
      }
      
      streamRef.current = stream;
      console.log(`[${instanceId.current}] Stream captured, tracks:`, 
        stream.getTracks().map(t => `${t.kind} (${t.enabled ? 'enabled' : 'disabled'})`));
      
      // Setup audio recording
      if (typeof MediaRecorder === 'undefined') {
        throw new Error('MediaRecorder API not supported');
      }
      
      const mimeType = getSupportedMimeType(stream);
      console.log(`[${instanceId.current}] Using MIME type for recording:`, mimeType);
      
      // Create and start audio recorder
      const recorder = new MediaRecorder(stream, { 
        mimeType: mimeType || undefined,
        audioBitsPerSecond: 128000
      });
      
      recorder.ondataavailable = async (event) => {
        if (!event.data || event.data.size === 0) return;
        
        try {
          const buffer = await event.data.arrayBuffer();
          if (buffer.byteLength > 0) {
            sendAudioData(buffer);
          }
        } catch (err) {
          console.error(`[${instanceId.current}] Error processing audio:`, err);
        }
      };
      
      recorder.start(audioChunkDuration);
      mediaRecorderRef.current = recorder;
      
      // Handle recorder events
      const handleRecorderError = () => {
        handleStreamingError('MediaRecorder error');
      };
      
      recorder.addEventListener('error', handleRecorderError);
      cleanupFunctionsRef.current.push(() => {
        recorder.removeEventListener('error', handleRecorderError);
      });
      
      // Setup video frame capture interval
      console.log(`[${instanceId.current}] Setting up video capture interval:`, videoFrameInterval, 'ms');
      
      frameIntervalRef.current = window.setInterval(() => {
        if (!videoWS || videoWS.readyState !== WebSocket.OPEN) return;
        
        try {
          // Skip if video is paused or ended
          if (videoElement.paused || videoElement.ended) return;
          
          // Draw current video frame to canvas
          ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
          
          // Convert to JPEG and send
          canvas.toBlob(async (blob) => {
            if (!blob || !videoWS || videoWS.readyState !== WebSocket.OPEN) return;
            
            try {
              const buffer = await blob.arrayBuffer();
              sendVideoData(buffer);
            } catch (err) {
              console.error(`[${instanceId.current}] Error sending video frame:`, err);
            }
          }, 'image/jpeg', videoQuality);
        } catch (err) {
          console.error(`[${instanceId.current}] Error capturing video frame:`, err);
        }
      }, videoFrameInterval);
      
      // Setup WebSocket close event handlers
      const handleSocketClose = () => {
        console.log(`[${instanceId.current}] WebSocket closed, cleaning up media`);
        cleanupMedia();
      };
      
      audioWS.addEventListener('close', handleSocketClose);
      videoWS.addEventListener('close', handleSocketClose);
      
      cleanupFunctionsRef.current.push(() => {
        audioWS.removeEventListener('close', handleSocketClose);
        videoWS.removeEventListener('close', handleSocketClose);
      });
      
      // Everything initialized successfully
      setIsStreaming(true);
      console.log(`[${instanceId.current}] Media streaming initialized successfully`);
      return true;
      
    } catch (err) {
      isInitializedRef.current = false;
      handleStreamingError(err);
      cleanupMedia();
      return false;
    }
  }, [
    audioWS,
    videoWS,
    videoPath,
    audioChunkDuration,
    videoFrameInterval,
    videoQuality,
    sendAudioData,
    sendVideoData,
    handleStreamingError,
    cleanupMedia
  ]);
  
  /**
   * Main effect to manage streaming lifecycle
   */
  useEffect(() => {
    console.log(`[${instanceId.current}] Media stream effect triggered, enabled:`, enabled);
    
    // Clean up if disabled
    if (!enabled) {
      console.log(`[${instanceId.current}] Media streaming disabled, cleaning up`);
      cleanupMedia();
      return;
    }
    
    // Don't start streaming until both WebSockets are fully connected
    if (!audioWS || !videoWS || 
        audioWS.readyState !== WebSocket.OPEN || 
        videoWS.readyState !== WebSocket.OPEN) {
      console.log(`[${instanceId.current}] Waiting for WebSocket connections:`, {
        audioWS: audioWS?.readyState,
        videoWS: videoWS?.readyState
      });
      
      // Setup check function
      const checkAndStartStreaming = () => {
        if (audioWS?.readyState === WebSocket.OPEN && videoWS?.readyState === WebSocket.OPEN) {
          console.log(`[${instanceId.current}] Both WebSockets open, starting media stream soon...`);
          // Use setTimeout to avoid React errors from synchronous state updates
          setTimeout(() => {
            if (enabled) { // Check again in case component unmounted
              startMediaStreaming().catch(err => {
                handleStreamingError(err);
              });
            }
          }, 500);
        }
      };
      
      // Setup WebSocket open handlers
      const handleSocketOpen = () => {
        console.log(`[${instanceId.current}] WebSocket opened, checking if we can start streaming`);
        checkAndStartStreaming();
      };
      
      // Add listeners
      if (audioWS) audioWS.addEventListener('open', handleSocketOpen);
      if (videoWS) videoWS.addEventListener('open', handleSocketOpen);
      
      // Check current state (in case they're already open)
      checkAndStartStreaming();
      
      return () => {
        // Remove listeners on cleanup
        if (audioWS) audioWS.removeEventListener('open', handleSocketOpen);
        if (videoWS) videoWS.removeEventListener('open', handleSocketOpen);
        cleanupMedia();
      };
    }
    
    // Both WebSockets are open, start streaming
    console.log(`[${instanceId.current}] WebSockets ready, starting media streaming`);
    startMediaStreaming().catch(err => {
      handleStreamingError(err);
    });
    
    return () => {
      cleanupMedia();
    };
  }, [enabled, audioWS, videoWS, startMediaStreaming, cleanupMedia, handleStreamingError]);
  
  /**
   * Set up periodic stats logging
   */
  useEffect(() => {
    if (!isStreaming) return;
    
    const interval = setInterval(() => {
      logStreamingStats();
    }, 5000);
    
    return () => clearInterval(interval);
  }, [isStreaming, logStreamingStats]);
  
  return {
    isStreaming,
    cleanupMedia,
    stats: statsRef.current
  };
}