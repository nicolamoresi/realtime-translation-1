import { useCallback, useEffect, useRef, useState } from 'react';

interface UserMediaOptions {
  enabled: boolean;
  audioWS: WebSocket | null;
  videoWS: WebSocket | null;
  audioConstraints?: MediaTrackConstraints;
  videoConstraints?: MediaTrackConstraints;
  videoFrameRate?: number;
  videoQuality?: number;
  onError?: (error: string) => void;
}

interface StreamStats {
  audioSamples: number;
  audioBytes: number;
  videoFrames: number;
  videoBytes: number;
  startTime: number;
}

/**
 * Hook for capturing and streaming user media (camera and microphone)
 * Uses direct streaming without MediaRecorder for better cross-browser compatibility
 */
export function useUserMedia({
  enabled,
  audioWS,
  videoWS,
  audioConstraints = {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  },
  videoConstraints = {
    width: { ideal: 640 },
    height: { ideal: 480 },
    frameRate: { ideal: 15 }
  },
  videoFrameRate = 15,
  videoQuality = 0.7,
  onError
}: UserMediaOptions) {
  // State
  const [isStreaming, setIsStreaming] = useState(false);
  const [hasPermissions, setHasPermissions] = useState<boolean | null>(null);
  
  // Refs
  const instanceId = useRef(`media-${Math.random().toString(36).slice(2, 8)}`);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const audioSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const frameIntervalRef = useRef<number | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const videoElementRef = useRef<HTMLVideoElement | null>(null);
  const cleanupFunctionsRef = useRef<Array<() => void>>([]);
  const isCleaningUpRef = useRef(false);
  
  // Statistics tracking
  const statsRef = useRef<StreamStats>({
    audioSamples: 0,
    audioBytes: 0,
    videoFrames: 0,
    videoBytes: 0,
    startTime: Date.now()
  });

  /**
   * Send audio data to WebSocket
   */
  const sendAudioData = useCallback((data: ArrayBuffer): boolean => {
    if (!audioWS || audioWS.readyState !== WebSocket.OPEN) {
      return false;
    }
    
    try {
      audioWS.send(data);
      statsRef.current.audioSamples++;
      statsRef.current.audioBytes += data.byteLength;
      return true;
    } catch (err) {
      console.error(`[${instanceId.current}] Error sending audio data:`, err);
      return false;
    }
  }, [audioWS]);
  
  /**
   * Send video frame data to WebSocket
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
   * Clean up all media resources
   */
  const cleanupMedia = useCallback(() => {
    // Prevent duplicate cleanups
    if (isCleaningUpRef.current) return;
    isCleaningUpRef.current = true;
    
    console.log(`[${instanceId.current}] Cleaning up media resources`);
    setIsStreaming(false);
    
    // Run all registered cleanup functions
    cleanupFunctionsRef.current.forEach(cleanup => {
      try {
        cleanup();
      } catch (err) {
        console.warn(`[${instanceId.current}] Error in cleanup function:`, err);
      }
    });
    cleanupFunctionsRef.current = [];
    
    // Clean up audio processing
    if (audioProcessorRef.current) {
      try {
        audioProcessorRef.current.disconnect();
      } catch (err) {
        console.warn(`[${instanceId.current}] Error disconnecting audio processor:`, err);
      }
      audioProcessorRef.current = null;
    }
    
    if (audioSourceRef.current) {
      try {
        audioSourceRef.current.disconnect();
      } catch (err) {
        console.warn(`[${instanceId.current}] Error disconnecting audio source:`, err);
      }
      audioSourceRef.current = null;
    }
    
    if (audioContextRef.current) {
      try {
        if (audioContextRef.current.state !== 'closed') {
          audioContextRef.current.close();
        }
      } catch (err) {
        console.warn(`[${instanceId.current}] Error closing audio context:`, err);
      }
      audioContextRef.current = null;
    }
    
    // Clear frame capture interval
    if (frameIntervalRef.current !== null) {
      window.clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }
    
    // Stop all media tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => {
        try {
          track.stop();
          console.log(`[${instanceId.current}] Stopped ${track.kind} track: ${track.label}`);
        } catch (err) {
          console.warn(`[${instanceId.current}] Error stopping track:`, err);
        }
      });
      mediaStreamRef.current = null;
    }
    
    // Remove canvas
    if (canvasRef.current) {
      try {
        document.body.removeChild(canvasRef.current);
      } catch (e) {
        // May already be removed
      }
      canvasRef.current = null;
    }
    
    // Remove video element
    if (videoElementRef.current) {
      try {
        videoElementRef.current.pause();
        videoElementRef.current.srcObject = null;
        document.body.removeChild(videoElementRef.current);
      } catch (e) {
        // May already be removed
      }
      videoElementRef.current = null;
    }
    
    // Reset flag
    isCleaningUpRef.current = false;
    
    // Log final stats
    const duration = (Date.now() - statsRef.current.startTime) / 1000;
    if (duration > 0) {
      console.log(`[${instanceId.current}] Streaming stats:`, {
        duration: `${duration.toFixed(1)}s`,
        audioSamples: statsRef.current.audioSamples,
        audioBytesTotal: `${(statsRef.current.audioBytes / 1024).toFixed(1)} KB`,
        audioBytesPerSecond: `${(statsRef.current.audioBytes / duration / 1024).toFixed(1)} KB/s`,
        videoFrames: statsRef.current.videoFrames,
        videoFPS: `${(statsRef.current.videoFrames / duration).toFixed(1)} fps`,
        videoBytesTotal: `${(statsRef.current.videoBytes / 1024).toFixed(1)} KB`,
        videoBytesPerSecond: `${(statsRef.current.videoBytes / duration / 1024).toFixed(1)} KB/s`,
      });
    }
  }, []);

  /**
   * Setup audio streaming using Web Audio API
   */
  const setupAudioStream = useCallback((stream: MediaStream): (() => void) => {
    const audioTracks = stream.getAudioTracks();
    if (audioTracks.length === 0) {
      console.warn(`[${instanceId.current}] No audio tracks available`);
      return () => {};
    }
    
    try {
      console.log(`[${instanceId.current}] Setting up audio streaming with Web Audio API`);
      
      // Create audio context
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      audioContextRef.current = audioContext;

      // Add this code:
      // Resume audio context (browsers require user interaction)
      if (audioContext.state === 'suspended') {
        console.log(`[${instanceId.current}] Audio context is suspended, attempting to resume...`);
        
        // Try to resume immediately
        audioContext.resume().then(() => {
          console.log(`[${instanceId.current}] Audio context resumed successfully`);
        }).catch(err => {
          console.error(`[${instanceId.current}] Failed to resume audio context:`, err);
        });
        
        // Add a button to the UI that can resume the context on click
        const resumeButton = document.createElement('button');
        resumeButton.textContent = 'Enable Audio';
        resumeButton.style.position = 'fixed';
        resumeButton.style.bottom = '10px';
        resumeButton.style.left = '10px';
        resumeButton.style.zIndex = '9999';
        resumeButton.style.padding = '10px 20px';
        resumeButton.style.backgroundColor = '#ff5500';
        resumeButton.style.color = 'white';
        resumeButton.style.border = 'none';
        resumeButton.style.borderRadius = '5px';
        resumeButton.style.fontWeight = 'bold';
        document.body.appendChild(resumeButton);
        
        resumeButton.onclick = () => {
          audioContext.resume().then(() => {
            console.log(`[${instanceId.current}] Audio context resumed via button click`);
            document.body.removeChild(resumeButton);
          });
        };
        
        cleanupFunctionsRef.current.push(() => {
          try {
            document.body.removeChild(resumeButton);
          } catch (e) {
            // Button might already be removed
          }
        });
      }
      audioContextRef.current = audioContext;
      
      // Create source from stream
      const source = audioContext.createMediaStreamSource(stream);
      audioSourceRef.current = source;
      
      // Buffer size must be a power of 2
      const bufferSize = 2048;
      
      // Create processor for handling audio data
      // Note: ScriptProcessorNode is deprecated but has better browser support than AudioWorklet
      const processor = audioContext.createScriptProcessor(bufferSize, 1, 1);
      audioProcessorRef.current = processor;
      
      // Connect the processing graph
      source.connect(processor);
      processor.connect(audioContext.destination);
      
      // Handle audio processing
      let sampleCounter = 0;
      processor.onaudioprocess = (e) => {
        try {
          if (!audioWS || audioWS.readyState !== WebSocket.OPEN) {
            return;
          }
          
          // Log audio processing periodically
          sampleCounter++;
          if (sampleCounter % 100 === 0) {
            console.log(`[${instanceId.current}] Audio processing active: ${sampleCounter} samples`);
          }
          
          // Use every sample instead of every other sample to ensure data is flowing
          const inputData = e.inputBuffer.getChannelData(0);
          
          // Skip silent audio (could indicate mic is muted)
          let maxSample = 0;
          for (let i = 0; i < inputData.length; i++) {
            maxSample = Math.max(maxSample, Math.abs(inputData[i]));
          }
          
          // Log if audio is too quiet
          if (sampleCounter % 100 === 0) {
            console.log(`[${instanceId.current}] Max audio level: ${maxSample.toFixed(4)}`);
          }
          
          // Convert to 16-bit PCM
          const pcmData = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i++) {
            pcmData[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
          }
          
          // Verify data has content
          if (pcmData.length === 0) {
            console.warn(`[${instanceId.current}] Empty PCM data`);
            return;
          }
          
          // Send with detailed logging
          const sent = sendAudioData(pcmData.buffer);
          if (sent && sampleCounter % 100 === 0) {
            console.log(`[${instanceId.current}] Sent ${pcmData.length} audio samples (${pcmData.buffer.byteLength} bytes)`);
          }
        } catch (err) {
          console.error(`[${instanceId.current}] Error in audio processing:`, err);
        }
      };
      
      console.log(`[${instanceId.current}] Audio processing started with buffer size ${bufferSize}`);
      
      // Return cleanup function
      return () => {
        processor.disconnect();
        source.disconnect();
        if (audioContext.state !== 'closed') {
          audioContext.close();
        }
      };
    } catch (err) {
      console.error(`[${instanceId.current}] Failed to setup audio processing:`, err);
      onError?.(`Failed to setup audio processing: ${err.message}`);
      return () => {};
    }
  }, [sendAudioData, onError]);
  
  /**
   * Setup video frame capture and transmission
   */
  const setupVideoStream = useCallback((stream: MediaStream): (() => void) => {
    const videoTracks = stream.getVideoTracks();
    if (videoTracks.length === 0) {
      console.warn(`[${instanceId.current}] No video tracks available`);
      return () => {};
    }
    
    try {
      console.log(`[${instanceId.current}] Setting up video frame capture`);
      
      // Create video element for local preview
      const videoElement = document.createElement('video');
      videoElement.srcObject = stream;
      videoElement.muted = true;
      videoElement.autoplay = true;
      videoElement.playsInline = true;
      videoElement.style.display = 'none';
      document.body.appendChild(videoElement);
      videoElementRef.current = videoElement;
      
      // Wait for video to start playing
      const videoReady = new Promise<void>((resolve) => {
        const checkReady = () => {
          if (videoElement.readyState >= 3) {
            resolve();
          } else {
            videoElement.addEventListener('canplay', () => resolve(), { once: true });
          }
        };
        checkReady();
      });
      
      videoReady.then(() => {
        // Create canvas for capturing frames
        const canvas = document.createElement('canvas');
        
        // Set size based on video tracks or default
        const videoSettings = videoTracks[0].getSettings();
        canvas.width = videoSettings.width || 640;
        canvas.height = videoSettings.height || 480;
        canvas.style.display = 'none';
        document.body.appendChild(canvas);
        canvasRef.current = canvas;
        
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          throw new Error('Could not get canvas context');
        }
        
        // Calculate interval based on desired frame rate
        const intervalMs = Math.round(1000 / videoFrameRate);
        console.log(`[${instanceId.current}] Starting video capture at ${videoFrameRate} FPS (${intervalMs}ms interval)`);
        
        // Set up frame capture interval
        frameIntervalRef.current = window.setInterval(() => {
          if (!videoWS || videoWS.readyState !== WebSocket.OPEN) return;
          
          try {
            // Skip if video element isn't ready
            if (videoElement.readyState < 2) return;
            
            // Draw the current video frame to canvas
            ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);
            
            // Convert to JPEG and send
            canvas.toBlob((blob) => {
              if (!blob || !videoWS || videoWS.readyState !== WebSocket.OPEN) return;
              
              blob.arrayBuffer().then(buffer => {
                sendVideoData(buffer);
              }).catch(err => {
                console.error(`[${instanceId.current}] Error converting blob:`, err);
              });
            }, 'image/jpeg', videoQuality);
          } catch (err) {
            console.error(`[${instanceId.current}] Error capturing video frame:`, err);
          }
        }, intervalMs);
      }).catch(err => {
        console.error(`[${instanceId.current}] Error waiting for video:`, err);
      });
      
      // Return cleanup function
      return () => {
        if (frameIntervalRef.current !== null) {
          clearInterval(frameIntervalRef.current);
          frameIntervalRef.current = null;
        }
        
        if (videoElement) {
          videoElement.pause();
          videoElement.srcObject = null;
          try {
            document.body.removeChild(videoElement);
          } catch (e) {}
        }
        
        if (canvasRef.current) {
          try {
            document.body.removeChild(canvasRef.current);
          } catch (e) {}
          canvasRef.current = null;
        }
      };
    } catch (err) {
      console.error(`[${instanceId.current}] Failed to setup video streaming:`, err);
      onError?.(`Failed to setup video streaming: ${err.message}`);
      return () => {};
    }
  }, [videoFrameRate, videoQuality, sendVideoData, onError]);
  
  /**
   * Setup WebSocket close handlers
   */
  const setupSocketHandlers = useCallback(() => {
    if (!audioWS && !videoWS) return () => {};
    
    const handleSocketClose = () => {
      console.log(`[${instanceId.current}] WebSocket closed, cleaning up media`);
      cleanupMedia();
    };
    
    if (audioWS) audioWS.addEventListener('close', handleSocketClose);
    if (videoWS) videoWS.addEventListener('close', handleSocketClose);
    
    return () => {
      if (audioWS) audioWS.removeEventListener('close', handleSocketClose);
      if (videoWS) videoWS.removeEventListener('close', handleSocketClose);
    };
  }, [audioWS, videoWS, cleanupMedia]);
  
  /**
   * Start media streaming with existing stream
   */
  const startStreamingWithStream = useCallback((stream: MediaStream) => {

    const debugPanel = document.createElement('div');
    debugPanel.style.position = 'fixed';
    debugPanel.style.top = '10px';
    debugPanel.style.right = '10px';
    debugPanel.style.width = '300px';
    debugPanel.style.padding = '10px';
    debugPanel.style.backgroundColor = 'rgba(0,0,0,0.7)';
    debugPanel.style.color = 'white';
    debugPanel.style.fontFamily = 'monospace';
    debugPanel.style.fontSize = '12px';
    debugPanel.style.zIndex = '9999';
    debugPanel.style.borderRadius = '5px';
    debugPanel.style.maxHeight = '300px';
    debugPanel.style.overflow = 'auto';
    debugPanel.style.boxShadow = '0 0 10px rgba(0,0,0,0.5)';
    debugPanel.innerHTML = '<h3>Media Debug</h3><div id="debug-content"></div>';
    document.body.appendChild(debugPanel);

    const updateDebug = () => {
      const content = document.getElementById('debug-content');
      if (!content) return;
      
      const now = Date.now();
      const elapsed = (now - statsRef.current.startTime) / 1000;
      
      content.innerHTML = `
        <div>Time: ${elapsed.toFixed(1)}s</div>
        <div>Audio samples: ${statsRef.current.audioSamples}</div>
        <div>Audio bytes: ${(statsRef.current.audioBytes / 1024).toFixed(1)} KB</div>
        <div>Video frames: ${statsRef.current.videoFrames}</div>
        <div>Video bytes: ${(statsRef.current.videoBytes / 1024).toFixed(1)} KB</div>
        <div>Audio WS: ${audioWS ? audioWS.readyState : 'null'}</div>
        <div>Video WS: ${videoWS ? videoWS.readyState : 'null'}</div>
        <div>AudioContext: ${audioContextRef.current ? audioContextRef.current.state : 'null'}</div>
      `;
    };

    const debugInterval = setInterval(updateDebug, 500);
    cleanupFunctionsRef.current.push(() => {
      clearInterval(debugInterval);
      try {
        document.body.removeChild(debugPanel);
      } catch (e) {
        // Panel might already be removed
      }
    });
    try {
      console.log(`[${instanceId.current}] Starting media streaming with stream:`, {
        audioTracks: stream.getAudioTracks().length,
        videoTracks: stream.getVideoTracks().length
      });
      
      // Reset statistics
      statsRef.current = {
        audioSamples: 0,
        audioBytes: 0,
        videoFrames: 0,
        videoBytes: 0,
        startTime: Date.now()
      };
      
      // Setup audio streaming
      const audioCleanup = setupAudioStream(stream);
      cleanupFunctionsRef.current.push(audioCleanup);
      
      // Setup video streaming
      const videoCleanup = setupVideoStream(stream);
      cleanupFunctionsRef.current.push(videoCleanup);
      
      // Setup WebSocket handlers
      const socketCleanup = setupSocketHandlers();
      cleanupFunctionsRef.current.push(socketCleanup);
      
      // Mark as streaming
      setIsStreaming(true);
      
      return true;
    } catch (err) {
      console.error(`[${instanceId.current}] Error starting streaming:`, err);
      onError?.(`Error starting streaming: ${err.message}`);
      cleanupMedia();
      return false;
    }
  }, [setupAudioStream, setupVideoStream, setupSocketHandlers, cleanupMedia, onError]);
  
  /**
   * Request user media permissions and start streaming
   */
  const startUserMedia = useCallback(async (): Promise<boolean> => {
    // Check WebSockets first
    if (!audioWS || !videoWS || 
        audioWS.readyState !== WebSocket.OPEN || 
        videoWS.readyState !== WebSocket.OPEN) {
      console.log(`[${instanceId.current}] WebSockets not ready, cannot start streaming`);
      return false;
    }
    
    try {
      // If we already have a stream, use it
      if (hasPermissions && mediaStreamRef.current) {
        return startStreamingWithStream(mediaStreamRef.current);
      }
      
      // Request new permissions
      console.log(`[${instanceId.current}] Requesting media permissions:`, {
        audio: audioConstraints,
        video: videoConstraints
      });
      
      // Try to get both audio and video
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: audioConstraints,
          video: videoConstraints
        });
        
        console.log(`[${instanceId.current}] Got full media access:`, 
          stream.getTracks().map(t => `${t.kind}: ${t.label}`));
      } catch (err) {
        console.warn(`[${instanceId.current}] Failed to get full media, trying audio only:`, err);
        
        // Fall back to audio only
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            audio: audioConstraints,
            video: false
          });
          
          console.log(`[${instanceId.current}] Got audio-only access:`, 
            stream.getTracks().map(t => `${t.kind}: ${t.label}`));
        } catch (audioErr) {
          console.error(`[${instanceId.current}] Failed to get any media access:`, audioErr);
          throw new Error(`Cannot access microphone or camera: ${audioErr.message}`);
        }
      }
      
      // Store stream and update permissions state
      mediaStreamRef.current = stream;
      setHasPermissions(true);
      
      // Start streaming with the new stream
      return startStreamingWithStream(stream);
    } catch (err) {
      console.error(`[${instanceId.current}] Media access error:`, err);
      
      // Handle specific permission errors
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setHasPermissions(false);
        onError?.('Camera and microphone access denied. Please allow access in your browser settings.');
      } else if (err.name === 'NotFoundError') {
        setHasPermissions(false);
        onError?.('No camera or microphone found. Please connect a device and try again.');
      } else if (err.name === 'NotSupportedError') {
        setHasPermissions(false);
        onError?.('Your browser does not support the requested media devices.');
      } else {
        onError?.(err.message || 'Error accessing camera or microphone');
      }
      
      cleanupMedia();
      return false;
    }
  }, [
    audioWS,
    videoWS,
    audioConstraints,
    videoConstraints,
    hasPermissions,
    startStreamingWithStream,
    cleanupMedia,
    onError
  ]);
  
  /**
   * Main effect to manage media lifecycle
   */
  useEffect(() => {
    console.log(`[${instanceId.current}] Media effect triggered, enabled: ${enabled}`);
    
    // Clean up if disabled
    if (!enabled) {
      cleanupMedia();
      return;
    }
    
    // Wait for WebSockets to be initialized
    if (!audioWS || !videoWS) {
      console.log(`[${instanceId.current}] WebSockets not yet initialized`);
      return;
    }
    
    // Wait for WebSockets to be connected
    if (audioWS.readyState !== WebSocket.OPEN || videoWS.readyState !== WebSocket.OPEN) {
      console.log(`[${instanceId.current}] Waiting for WebSockets to connect:`, {
        audio: audioWS.readyState,
        video: videoWS.readyState
      });
      
      // Set up listeners for WebSocket open events
      const handleOpen = () => {
        if (audioWS.readyState === WebSocket.OPEN && videoWS.readyState === WebSocket.OPEN) {
          console.log(`[${instanceId.current}] Both WebSockets connected, starting media`);
          startUserMedia().catch(err => {
            console.error(`[${instanceId.current}] Error starting user media:`, err);
          });
        }
      };
      
      audioWS.addEventListener('open', handleOpen);
      videoWS.addEventListener('open', handleOpen);
      
      // Check if they're already open
      if (audioWS.readyState === WebSocket.OPEN && videoWS.readyState === WebSocket.OPEN) {
        handleOpen();
      }
      
      return () => {
        audioWS.removeEventListener('open', handleOpen);
        videoWS.removeEventListener('open', handleOpen);
        cleanupMedia();
      };
    }
    
    // WebSockets are open, start user media
    console.log(`[${instanceId.current}] WebSockets ready, starting user media`);
    startUserMedia().catch(err => {
      console.error(`[${instanceId.current}] Error starting user media:`, err);
    });
    
    return () => {
      cleanupMedia();
    };
  }, [enabled, audioWS, videoWS, startUserMedia, cleanupMedia]);
  
  // Return hook API
  return {
    isStreaming,
    hasPermissions,
    cleanupMedia,
    stream: mediaStreamRef.current,
    stats: statsRef.current
  };
}