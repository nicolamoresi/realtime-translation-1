'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { API_BASE } from '@/utils/api'


interface DataStats {
  audioSent: number;
  videoSent: number;
  audioReceived: number;
  videoReceived: number;
  audioPlayed?: number;  // Track successfully played audio
  videoFrames?: number;  // Track successfully rendered frames
}
// Extend HTMLVideoElement type to allow for custom properties
declare global {
  interface HTMLVideoElement {
    _canvas?: HTMLCanvasElement;
    _container?: HTMLDivElement;
  }
}

export default function SimplifiedSimulatorPage() {
  const { roomId } = useParams<{ roomId: string }>();
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState('Initializing...');
  const [dataStats, setDataStats] = useState<DataStats>({
    audioSent: 0,
    videoSent: 0,
    audioReceived: 0,
    videoReceived: 0
  });

  // WebSocket refs
  const audioWS = useRef<WebSocket | null>(null);
  const videoWS = useRef<WebSocket | null>(null);

  // Media element refs
  const localVideoRef = useRef<HTMLVideoElement>(null);
  const remoteVideoRef = useRef<HTMLVideoElement>(null);
  const remoteAudioRef = useRef<HTMLAudioElement>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  
  // Canvas for video processing
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const remoteCanvasRef = useRef<HTMLCanvasElement | null>(null);
  
  // Intervals for media transmission
  const videoIntervalRef = useRef<number | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  
  // Audio processing references
  const audioBufferQueue = useRef<ArrayBuffer[]>([]);
  const isProcessingAudio = useRef<boolean>(false);
  const nextPlayTime = useRef<number>(0);

  const audioAnalyserRef = useRef<AnalyserNode | null>(null);
  const audioVisualizerCanvasRef = useRef<HTMLCanvasElement | null>(null);
  
  // Get auth token from localStorage
  useEffect(() => {
    const storedToken = localStorage.getItem('token');
    if (!storedToken) {
      setError('Authentication token not found. Please sign in first.');
      setIsLoading(false);
      return;
    }
    
    setToken(storedToken);
    setConnectionStatus('Token retrieved, establishing connections...');
  }, []);

  // Set up WebSocket connections
  useEffect(() => {
    if (!token) return;
    
    // Create a function to wrap WebSocket setup with monitoring
    // Replace your WebSocket setup with this Azure-optimized implementation

    const setupMonitoredWebSocket = (path: string, type: 'audio' | 'video') => {
      // Add audio_only=true parameter to optimize backend processing
      const wsUrl = `${API_BASE.replace('http:', 'ws:').replace('https:', 'wss:')}/ws/${path}/${roomId}?token=${token}&audio_only=true`;
      console.log(`Creating ${type} WebSocket connection to: ${wsUrl}`);
      
      const ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      
      // Store the original send method
      const originalSend = ws.send.bind(ws);
      
      // Add Azure recommended WebSocket send method with state checking
      ws.send = function(data: string | ArrayBufferLike | Blob | ArrayBufferView) {
        try {
          // Check connection state before sending (Azure best practice)
          if (ws.readyState !== WebSocket.OPEN) {
            console.warn(`Cannot send ${type} data: WebSocket not in OPEN state (${ws.readyState})`);
            return false;
          }
          
          // Log data being sent
          const byteLength = data instanceof ArrayBuffer ? data.byteLength : 
                            data instanceof Blob ? data.size : 
                            ArrayBuffer.isView(data) ? data.byteLength : 
                            data.length;
                            
          console.log(`Sending ${type} data: ${byteLength} bytes`);
          
          // Update statistics
          setDataStats(prev => ({
            ...prev,
            [type === 'audio' ? 'audioSent' : 'videoSent']: prev[type === 'audio' ? 'audioSent' : 'videoSent'] + byteLength
          }));
          
          // Call the original send method
          return originalSend(data);
        } catch (err) {
          console.error(`Error sending ${type} data:`, err);
          return false;
        }
      };
      
      // Azure WebSocket health monitoring
      ws.onopen = () => {
        console.log(`${type} WebSocket connected!`);
        // Send initial health check
        setTimeout(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping', client_info: navigator.userAgent }));
          }
        }, 500);
        updateConnectionStatus();
      };
      
      // Add detailed close information
      ws.onclose = (event) => {
        console.log(`${type} WebSocket closed: code=${event.code}, reason=${event.reason || 'No reason provided'}, clean=${event.wasClean}`);
        updateConnectionStatus();
      };
      
      ws.onerror = (event) => {
        console.error(`${type} WebSocket error:`, event);
        setError(`${type} connection error. Check console for details.`);
      };
      
      // Enhanced message handler with explicit type detection
      ws.onmessage = (event) => {
        // Handle received data
        if (event.data instanceof ArrayBuffer) {
          const byteLength = event.data.byteLength;
          console.log(`Received ${type} binary data: ${byteLength} bytes`);
          
          // Update statistics
          setDataStats(prev => ({
            ...prev,
            [type === 'audio' ? 'audioReceived' : 'videoReceived']: 
              prev[type === 'audio' ? 'audioReceived' : 'videoReceived'] + byteLength
          }));
          
          // For media data, process according to type with detailed logging
          if (type === 'audio') {
            console.log(`Processing audio data (${byteLength} bytes) at ${new Date().toISOString()}`);
            handleIncomingAudioData(event.data);
          } else if (type === 'video') {
            console.log(`Processing video data (${byteLength} bytes) at ${new Date().toISOString()}`);
            handleIncomingVideoData(event.data);
          }
        } else if (typeof event.data === 'string') {
          console.log(`Received ${type} text message:`, event.data.substring(0, 100));
          try {
            const data = JSON.parse(event.data);
            
            // Handle different message types
            if (data.type === 'ping') {
              // Respond to server pings with pongs
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'pong', timestamp: Date.now() }));
              }
            } else if (data.type === 'config') {
              console.log(`Received config update:`, data);
            } else if (data.transcript) {
              console.log(`Transcript: "${data.transcript}" → "${data.translated || ''}"`);
            }
          } catch (e) {
            console.warn(`Error parsing ${type} message:`, e);
          }
        } else {
          console.warn(`Received unknown ${type} data type:`, typeof event.data);
        }
      };
      
      return ws;
    };
    
    // Set up the connections
    audioWS.current = setupMonitoredWebSocket('voice', 'audio');
    videoWS.current = setupMonitoredWebSocket('video', 'video');
    
    // Function to update overall connection status
    function updateConnectionStatus() {
      const audioState = audioWS.current?.readyState || -1;
      const videoState = videoWS.current?.readyState || -1;
      
      if (audioState === WebSocket.OPEN && videoState === WebSocket.OPEN) {
        setConnectionStatus('All connections established!');
        setIsLoading(false);
        startMediaCapture();
      } else if (audioState === WebSocket.OPEN) {
        setConnectionStatus('Audio connected, waiting for video connection...');
      } else if (videoState === WebSocket.OPEN) {
        setConnectionStatus('Video connected, waiting for audio connection...');
      } else {
        setConnectionStatus('Establishing WebSocket connections...');
      }
    }
    
    // Clean up WebSocket connections on unmount
    return () => {
      if (audioWS.current && audioWS.current.readyState < 2) {
        audioWS.current.close();
      }
      
      if (videoWS.current && videoWS.current.readyState < 2) {
        videoWS.current.close();
      }
      
      stopMediaCapture();
    };
  }, [roomId, token]);
  
  // Safety timeout to prevent infinite loading
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (isLoading) {
        setIsLoading(false);
        if (!error) {
          setError("Connection timed out. The server might be unavailable or your token may be invalid.");
        }
      }
    }, 10000); // 10 seconds timeout
    
    return () => clearTimeout(timeoutId);
  }, [isLoading, error]);
  
  // Initialize audio context on first user interaction
  useEffect(() => {
    const initAudioContext = () => {
      if (!audioContextRef.current) {
        try {
          audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
          console.log("AudioContext initialized on user interaction");
          document.removeEventListener('click', initAudioContext);
        } catch (err) {
          console.error("Failed to initialize AudioContext:", err);
        }
      }
    };
    
    document.addEventListener('click', initAudioContext);
    return () => document.removeEventListener('click', initAudioContext);
  }, []);
  
  // Create canvas for remote video on component mount
  useEffect(() => {
    if (!remoteCanvasRef.current && remoteVideoRef.current) {
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      canvas.style.width = '100%';
      canvas.style.height = '100%';
      canvas.style.objectFit = 'cover';
      
      // Insert canvas into DOM
      const videoContainer = remoteVideoRef.current.parentElement;
      if (videoContainer) {
        videoContainer.insertBefore(canvas, remoteVideoRef.current);
        remoteVideoRef.current.style.display = 'none';
        remoteCanvasRef.current = canvas;
      }
    }
    
    return () => {
      // Clean up canvas on unmount
      if (remoteCanvasRef.current) {
        try {
          remoteCanvasRef.current.parentElement?.removeChild(remoteCanvasRef.current);
        } catch (e) {
          console.error("Error removing canvas:", e);
        }
        remoteCanvasRef.current = null;
      }
    };
  }, []);
  
  // Audio processing function - handles incoming audio data with Web Audio API
  function handleIncomingAudioData(data: ArrayBuffer) {
    // Log detailed info about received data
    console.log(`Processing audio data: ${data.byteLength} bytes`);
    
    // Minimum viable size check - Azure media packets should be substantial
    if (data.byteLength < 16) {
      console.warn(`Audio packet too small: ${data.byteLength} bytes, skipping`);
      return;
    }
    
    // Attempt direct audio element playback first (most reliable approach)
    if (remoteAudioRef.current) {
      try {
        // Create blob and URL
        const blob = new Blob([data], { type: 'audio/wav' });
        const url = URL.createObjectURL(blob);
        
        // Track previous URL for cleanup
        const prevUrl = remoteAudioRef.current.src;
        if (prevUrl.startsWith('blob:')) {
          URL.revokeObjectURL(prevUrl);
        }
        
        // Set new source and play
        remoteAudioRef.current.src = url;
        
        // When loaded, play and handle errors
        remoteAudioRef.current.onloadedmetadata = () => {
          remoteAudioRef.current?.play()
            .then(() => {
              console.log("Audio playback started via audio element");
              // Update stats to indicate successful playback
              setDataStats(prev => ({
                ...prev,
                audioPlayed: (prev.audioPlayed || 0) + data.byteLength
              }));
            })
            .catch(err => {
              console.error("Error playing audio via audio element:", err);
              // Fall back to Web Audio API
              audioBufferQueue.current.push(data);
              if (!isProcessingAudio.current) {
                processAudioQueue();
              }
            });
        };
        
        remoteAudioRef.current.onerror = () => {
          console.warn("Audio element error, falling back to Web Audio API");
          URL.revokeObjectURL(url);
          // Fall back to Web Audio API
          audioBufferQueue.current.push(data);
          if (!isProcessingAudio.current) {
            processAudioQueue();
          }
        };
        
        return;
      } catch (directPlayError) {
        console.warn("Direct audio playback failed:", directPlayError);
        // Continue to buffer-based playback
      }
    }
    
    // Add to processing queue for Web Audio API processing
    audioBufferQueue.current.push(data);
    
    // Start processing if not already in progress
    if (!isProcessingAudio.current) {
      processAudioQueue();
    }
  }
  
  // Process audio queue for continuous playback
  async function processAudioQueue() {
    if (audioBufferQueue.current.length === 0) {
      isProcessingAudio.current = false;
      return;
    }
    
    isProcessingAudio.current = true;
    
    try {
      // Initialize audio context if needed
      if (!audioContextRef.current) {
        console.log("Creating new AudioContext");
        audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
        
        // Create an analyzer for visualization
        audioAnalyserRef.current = audioContextRef.current.createAnalyser();
        audioAnalyserRef.current.fftSize = 256;
        audioAnalyserRef.current.connect(audioContextRef.current.destination);
        
        // Start visualization if canvas exists
        if (audioVisualizerCanvasRef.current) {
          visualizeAudio();
        }
        
        // Initialize playback time
        nextPlayTime.current = audioContextRef.current.currentTime;
      }
      
      const context = audioContextRef.current;
      
      // Ensure context is running (required by browsers)
      if (context.state !== 'running') {
        console.log(`AudioContext not running (${context.state}), attempting to resume...`);
        
        // Attempt to resume context - this requires user interaction in many browsers
        await context.resume();
        
        // If still suspended after attempted resume, wait for user interaction
        if (context.state === 'suspended') {
          console.warn("AudioContext still suspended after resume attempt");
          document.addEventListener('click', function resumeOnClick() {
            context.resume().then(() => {
              console.log("AudioContext resumed by user interaction");
              document.removeEventListener('click', resumeOnClick);
              // Retry processing after resume
              setTimeout(processAudioQueue, 100);
            });
          }, { once: true });
          
          isProcessingAudio.current = false;
          return;
        }
        
        console.log(`AudioContext state after resume: ${context.state}`);
      }
      
      // Get next chunk from queue
      const audioData = audioBufferQueue.current.shift();
      if (!audioData) {
        isProcessingAudio.current = false;
        return;
      }
      
      // Detect audio format based on data characteristics
      // Azure often sends WAV or raw PCM
      const isWav = new Uint8Array(audioData, 0, 4).every((byte, i) => 
        byte === [0x52, 0x49, 0x46, 0x46][i]); // "RIFF" header
      
      try {
        let audioBuffer;
        
        if (isWav) {
          // Process WAV data
          console.log("Processing WAV audio format");
          audioBuffer = await context.decodeAudioData(audioData.slice(0));
        } else {
          // Assume 16-bit PCM at 16kHz mono (Azure default for speech)
          console.log("Processing PCM audio data");
          
          const pcmData = new Int16Array(audioData);
          const sampleRate = 16000; // Azure default
          
          // Create buffer
          audioBuffer = context.createBuffer(1, pcmData.length, sampleRate);
          
          // Fill channel with normalized data
          const channelData = audioBuffer.getChannelData(0);
          for (let i = 0; i < pcmData.length; i++) {
            // Normalize from Int16 (-32768 to 32767) to Float32 (-1.0 to 1.0)
            channelData[i] = Math.max(-1, Math.min(1, pcmData[i] / 32768.0));
          }
        }
        
        console.log(`Audio buffer created: ${audioBuffer.duration.toFixed(2)}s, ${audioBuffer.length} samples, ${audioBuffer.numberOfChannels} channels, ${audioBuffer.sampleRate}Hz`);
        
        // Create source node
        const source = context.createBufferSource();
        source.buffer = audioBuffer;
        
        // Add a gain node for volume control (prevents clipping)
        const gainNode = context.createGain();
        gainNode.gain.value = 0.8; // 80% volume to prevent clipping
        
        // Connect to visualizer if available
        source.connect(gainNode);
        if (audioAnalyserRef.current) {
          gainNode.connect(audioAnalyserRef.current);
        } else {
          gainNode.connect(context.destination);
        }
        
        // Minimum playback delay to prevent stuttering
        const MIN_SCHEDULE_AHEAD_TIME = 0.1; // 100ms buffer
        
        // Schedule playback - use more conservative approach
        const currentTime = context.currentTime;
        let playTime;
        
        if (nextPlayTime.current <= currentTime) {
          // If we're behind, play ASAP but with minimum buffer
          playTime = currentTime + MIN_SCHEDULE_AHEAD_TIME;
          // Reset scheduling for future chunks
          nextPlayTime.current = playTime;
        } else {
          // Schedule at next available slot
          playTime = nextPlayTime.current;
        }
        
        console.log(`Scheduling audio: current=${currentTime.toFixed(3)}s, playing at=${playTime.toFixed(3)}s, duration=${audioBuffer.duration.toFixed(3)}s`);
        
        // Start playback
        source.start(playTime);
        
        // Update next play time
        nextPlayTime.current = playTime + audioBuffer.duration;
        
        // Track playback completion
        let playbackCompleted = false;
        
        // Visual indicator - update UI immediately to show processing
        setDataStats(prev => ({
          ...prev,
          audioPlayed: (prev.audioPlayed || 0) + audioData.byteLength
        }));
        
        // Schedule next chunk processing
        source.onended = () => {
          playbackCompleted = true;
          // Process next chunk after this one ends
          setTimeout(processAudioQueue, 0);
        };
        
        // Fallback if onended doesn't fire (common issue with Web Audio API)
        const expectedDuration = audioBuffer.duration * 1000; // ms
        setTimeout(() => {
          if (!playbackCompleted) {
            console.warn(`Audio onended never fired after ${expectedDuration.toFixed(0)}ms, using fallback`);
            processAudioQueue();
          }
        }, expectedDuration + 200); // Add 200ms buffer
        
      } catch (error) {
        console.error("Error processing audio chunk:", error);
        
        // Skip problematic buffer but continue processing
        setTimeout(processAudioQueue, 50);
      }
    } catch (error) {
      console.error("Fatal error in audio processing:", error);
      
      // Reset processing state to allow retry
      isProcessingAudio.current = false;
    }
  }

  function visualizeAudio() {
    if (!audioAnalyserRef.current || !audioVisualizerCanvasRef.current) return;
    
    const analyser = audioAnalyserRef.current;
    const canvas = audioVisualizerCanvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    
    function draw() {
      requestAnimationFrame(draw);
      
      analyser.getByteFrequencyData(dataArray);
      
      ctx.fillStyle = 'rgb(15, 15, 15)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      
      const barWidth = (canvas.width / bufferLength) * 2.5;
      let barHeight;
      let x = 0;
      
      for (let i = 0; i < bufferLength; i++) {
        barHeight = dataArray[i] / 2;
        
        // Only draw if there's actual data
        if (barHeight > 0) {
          ctx.fillStyle = `rgb(50, ${barHeight + 100}, 50)`;
          ctx.fillRect(x, canvas.height - barHeight, barWidth, barHeight);
        }
        
        x += barWidth + 1;
      }
    }
    
    draw();
  }
  
  // Video processing function - renders incoming video frames to canvas
  function handleIncomingVideoData(data: ArrayBuffer) {
    console.log(`Processing video data: ${data.byteLength} bytes`);
    
    if (data.byteLength < 100) {
      console.warn(`Video data too small: ${data.byteLength} bytes, skipping`);
      return; // Skip small packets
    }
    
    // Debug - check for JPEG header
    const header = new Uint8Array(data, 0, 4);
    const isJpeg = header[0] === 0xFF && header[1] === 0xD8;
    if (!isJpeg) {
      console.warn(`Received non-JPEG data, first bytes: [${Array.from(header).map(b => b.toString(16).padStart(2, '0')).join(' ')}]`);
    }
    
    try {
      // Create blob URL from the data
      const blob = new Blob([data], { type: 'image/jpeg' });
      const url = URL.createObjectURL(blob);
      console.log(`Created blob URL: ${url}`);
      
      // Load image from blob URL
      const img = new Image();
      
      // Image loading monitoring
      const loadStartTime = Date.now();
      
      img.onload = () => {
        const loadTime = Date.now() - loadStartTime;
        console.log(`Image loaded in ${loadTime}ms: ${img.width}x${img.height} pixels`);
        
        // Draw to canvas if available
        if (remoteCanvasRef.current) {
          const ctx = remoteCanvasRef.current.getContext('2d');
          if (ctx) {
            // Cache original dimensions
            const originalWidth = remoteCanvasRef.current.width;
            const originalHeight = remoteCanvasRef.current.height;
            
            // Ensure canvas dimensions match image (if they don't already)
            if (remoteCanvasRef.current.width !== img.width || remoteCanvasRef.current.height !== img.height) {
              if (img.width > 0 && img.height > 0) {
                console.log(`Adjusting canvas size to match image: ${img.width}x${img.height}`);
                remoteCanvasRef.current.width = img.width;
                remoteCanvasRef.current.height = img.height;
              }
            }
            
            // Clear canvas and draw new frame
            try {
              ctx.clearRect(0, 0, remoteCanvasRef.current.width, remoteCanvasRef.current.height);
              ctx.drawImage(img, 0, 0, remoteCanvasRef.current.width, remoteCanvasRef.current.height);
              console.log(`Successfully rendered frame to canvas ${remoteCanvasRef.current.width}x${remoteCanvasRef.current.height}`);
              
              // Visual indicator update
              setDataStats(prev => ({
                ...prev,
                videoFrames: (prev.videoFrames || 0) + 1
              }));
            } catch (drawError) {
              console.error(`Error drawing to canvas: ${drawError}`);
              // Restore original dimensions on error
              remoteCanvasRef.current.width = originalWidth;
              remoteCanvasRef.current.height = originalHeight;
            }
          } else {
            console.error("Failed to get canvas context for video rendering");
          }
        } else {
          console.warn("Remote canvas reference not available for video rendering");
        }
        
        // Clean up URL
        URL.revokeObjectURL(url);
      };
      
      img.onerror = (err) => {
        console.error("Failed to load video frame:", err);
        URL.revokeObjectURL(url);
      };
      
      // Add a timeout for load attempts
      const imageLoadTimeout = setTimeout(() => {
        console.warn(`Image load timed out after 5 seconds`);
        URL.revokeObjectURL(url);
      }, 5000);
      
      // Set source to trigger loading
      img.src = url;
      
      // Clear timeout when loaded or on error
      img.onload = (e) => {
        clearTimeout(imageLoadTimeout);
        const loadTime = Date.now() - loadStartTime;
        console.log(`Image loaded in ${loadTime}ms: ${img.width}x${img.height} pixels`);
        
        // Rest of your image loading code...
        // [previous implementation]
      };
      
      img.onerror = (err) => {
        clearTimeout(imageLoadTimeout);
        console.error("Failed to load video frame:", err);
        URL.revokeObjectURL(url);
      };
      
    } catch (error) {
      console.error("Error processing video data:", error);
    }
  }
  
  // Start capturing and sending media
  async function startMediaCapture() {
    try {
      // Request camera and microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480 },
        audio: true
      });
      
      console.log("Media access granted:", stream.getTracks().map(t => `${t.kind}: ${t.label}`));
      
      // Store the stream and connect to video element
      localStreamRef.current = stream;
      
      if (localVideoRef.current) {
        localVideoRef.current.srcObject = stream;
        
        // Log when video is actually playing
        localVideoRef.current.onplaying = () => {
          console.log("Local video is now playing");
        };
      }
      
      // Start sending video frames
      startVideoTransmission(stream);
      
      // Start sending audio data
      startAudioTransmission(stream);
      
    } catch (err) {
      console.error("Error accessing media devices:", err);
      setError(`Camera/microphone error: ${err instanceof Error ? err.message : String(err)}`);
    }
  }
  
  function startVideoTransmission(stream: MediaStream) {
    // Create canvas for video frame capture if needed
    if (!canvasRef.current) {
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 480;
      canvas.style.display = 'none';
      document.body.appendChild(canvas);
      canvasRef.current = canvas;
    }
    
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    
    if (!ctx) {
      console.error("Could not get canvas context");
      return;
    }
    
    // Clear any existing interval
    if (videoIntervalRef.current) {
      clearInterval(videoIntervalRef.current);
    }
    
    // Set up interval to capture and send video frames
    videoIntervalRef.current = window.setInterval(() => {
      if (!videoWS.current || videoWS.current.readyState !== WebSocket.OPEN) {
        return;
      }
      
      try {
        // Draw current video frame to canvas
        if (localVideoRef.current) {
          ctx.drawImage(localVideoRef.current, 0, 0, canvas.width, canvas.height);
          
          // Convert to JPEG and send
          canvas.toBlob((blob) => {
            if (blob && videoWS.current && videoWS.current.readyState === WebSocket.OPEN) {
              blob.arrayBuffer().then(buffer => {
                videoWS.current?.send(buffer);
              });
            }
          }, 'image/jpeg', 0.7); // 70% quality
        }
      } catch (err) {
        console.error("Error capturing video frame:", err);
      }
    }, 200); // ~5 fps
  }
  
  function startAudioTransmission(stream: MediaStream) {
    // Set up audio processing using AudioWorklet when available
    try {
      const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      audioContextRef.current = audioContext;
      
      // Auto-resume audio context (browsers require user interaction)
      if (audioContext.state === 'suspended') {
        const resumeAudio = () => {
          audioContext.resume().then(() => {
            console.log("AudioContext resumed successfully");
            document.removeEventListener('click', resumeAudio);
          });
        };
        
        document.addEventListener('click', resumeAudio);
      }
      
      const source = audioContext.createMediaStreamSource(stream);
      
      // Use modern AudioWorklet if available
      if ('audioWorklet' in audioContext) {
        console.log("Using modern AudioWorklet API");
        setupAudioWorklet(audioContext, source);
      } else {
        // Fall back to ScriptProcessor for older browsers
        console.log("AudioWorklet not available, using ScriptProcessor");
        setupScriptProcessor(audioContext, source);
      }
    } catch (err) {
      console.error("Error setting up audio processing:", err);
    }
  }
  
  // Modern audio processing with AudioWorklet
  function setupAudioWorklet(audioContext: AudioContext, source: MediaStreamAudioSourceNode) {
    // Define the processor code
    const processorCode = `
      class AudioProcessor extends AudioWorkletProcessor {
        process(inputs, outputs, parameters) {
          // Get input data
          const input = inputs[0];
          if (input.length === 0 || input[0].length === 0) return true;
          
          const inputChannel = input[0];
          
          // Convert to 16-bit PCM
          const pcmData = new Int16Array(inputChannel.length);
          for (let i = 0; i < inputChannel.length; i++) {
            pcmData[i] = Math.max(-1, Math.min(1, inputChannel[i])) * 0x7FFF;
          }
          
          // Send to main thread
          this.port.postMessage({
            audioData: pcmData.buffer
          }, [pcmData.buffer]);
          
          // Keep processor alive
          return true;
        }
      }
      
      registerProcessor('audio-processor', AudioProcessor);
    `;
    
    // Create a blob URL for the processor code
    const blob = new Blob([processorCode], { type: 'application/javascript' });
    const workletUrl = URL.createObjectURL(blob);
    
    // Add the module to the audio context
    audioContext.audioWorklet.addModule(workletUrl).then(() => {
      // Clean up URL
      URL.revokeObjectURL(workletUrl);
      
      // Create the AudioWorkletNode
      const workletNode = new AudioWorkletNode(audioContext, 'audio-processor');
      
      // Connect the nodes
      source.connect(workletNode);
      workletNode.connect(audioContext.destination);
      
      // Process data from the worklet
      workletNode.port.onmessage = (event) => {
        if (!audioWS.current || audioWS.current.readyState !== WebSocket.OPEN) return;
        
        if (event.data && event.data.audioData) {
          audioWS.current.send(event.data.audioData);
        }
      };
      
      console.log("AudioWorklet setup complete");
      
    }).catch(err => {
      console.error("Failed to setup AudioWorklet:", err);
      // Fall back to ScriptProcessor
      setupScriptProcessor(audioContext, source);
    });
  }
  
  // Legacy audio processing with ScriptProcessor
  function setupScriptProcessor(audioContext: AudioContext, source: MediaStreamAudioSourceNode) {
    const processor = audioContext.createScriptProcessor(2048, 1, 1);
    
    // Connect the audio processing graph
    source.connect(processor);
    processor.connect(audioContext.destination);
    
    // Process and send audio data
    processor.onaudioprocess = (e) => {
      if (!audioWS.current || audioWS.current.readyState !== WebSocket.OPEN) {
        return;
      }
      
      try {
        const inputData = e.inputBuffer.getChannelData(0);
        
        // Convert to 16-bit PCM
        const pcmData = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          pcmData[i] = Math.max(-1, Math.min(1, inputData[i])) * 0x7FFF;
        }
        
        // Send the audio data
        audioWS.current.send(pcmData.buffer);
      } catch (err) {
        console.error("Error processing audio:", err);
      }
    };
  }
  
  function stopMediaCapture() {
    // Stop video transmission
    if (videoIntervalRef.current) {
      clearInterval(videoIntervalRef.current);
      videoIntervalRef.current = null;
    }
    
    // Clean up canvas
    if (canvasRef.current) {
      try {
        document.body.removeChild(canvasRef.current);
      } catch (e) {
        console.error("Error removing canvas:", e);
      }
      canvasRef.current = null;
    }
    
    // Stop audio context
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().catch(e => console.error("Error closing audio context:", e));
      audioContextRef.current = null;
    }
    
    // Stop all media tracks
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => {
        track.stop();
      });
      localStreamRef.current = null;
    }
    
    // Clear audio buffer queue
    audioBufferQueue.current = [];
    isProcessingAudio.current = false;
  }

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <p>Connecting to room {roomId}...</p>
          <p className="text-sm text-gray-500 mt-2">{connectionStatus}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Error message */}
      {error && (
        <div className="col-span-full mb-4 p-4 bg-red-100 text-red-800 rounded">
          <p className="font-bold">Error</p>
          <p>{error}</p>
        </div>
      )}
      
      {/* Connection status */}
      <div className="col-span-full mb-4 p-3 bg-gray-100 rounded">
        <h3 className="font-bold">Connection Status: {connectionStatus}</h3>
        <div className="grid grid-cols-2 gap-4 mt-2">
          <div>
            <h4 className="font-semibold">Audio WebSocket:</h4>
            <div className={`mt-1 px-3 py-1 rounded ${
              audioWS.current?.readyState === WebSocket.OPEN ? 
                "bg-green-100 text-green-800" : 
                "bg-red-100 text-red-800"
            }`}>
              {audioWS.current ? 
                ["Connecting", "Open ✅", "Closing", "Closed ❌"][audioWS.current.readyState] : 
                "Not initialized"}
            </div>
          </div>
          <div>
            <h4 className="font-semibold">Video WebSocket:</h4>
            <div className={`mt-1 px-3 py-1 rounded ${
              videoWS.current?.readyState === WebSocket.OPEN ? 
                "bg-green-100 text-green-800" : 
                "bg-red-100 text-red-800"
            }`}>
              {videoWS.current ? 
                ["Connecting", "Open ✅", "Closing", "Closed ❌"][videoWS.current.readyState] : 
                "Not initialized"}
            </div>
          </div>
        </div>
      </div>

      {/* Data transmission statistics */}
      <div className="col-span-full mb-4 p-3 bg-gray-100 rounded">
        <h3 className="font-bold">Data Transmission</h3>
        <div className="grid grid-cols-2 gap-4 mt-2">
          <div>
            <p>Audio sent: {(dataStats.audioSent / 1024).toFixed(1)} KB</p>
            <p>Video sent: {(dataStats.videoSent / 1024).toFixed(1)} KB</p>
          </div>
          <div>
            <p>Audio received: {(dataStats.audioReceived / 1024).toFixed(1)} KB 
              {dataStats.audioPlayed ? 
                <span className="text-green-600 ml-2">
                  ({(dataStats.audioPlayed / 1024).toFixed(1)} KB played)
                </span> : 
                <span className="text-red-600 ml-2">(Not playing)</span>
              }
            </p>
            <p>Video received: {(dataStats.videoReceived / 1024).toFixed(1)} KB
              {dataStats.videoFrames ? 
                <span className="text-green-600 ml-2">
                  ({dataStats.videoFrames} frames rendered)
                </span> : 
                <span className="text-red-600 ml-2">(Not rendering)</span>
              }
            </p>
          </div>
        </div>
      </div>
      
      {/* Local video (left side) */}
      <div>
        <h2 className="font-bold mb-2">Your Camera</h2>
        <video 
          ref={localVideoRef} 
          autoPlay 
          playsInline
          muted 
          className="w-full rounded bg-gray-200 h-[320px] object-cover"
        />
        <p className="text-sm mt-1 text-center">Audio and video are sent to the server as you speak</p>
      </div>
      
      {/* Remote video (right side) */}
      <div>
        <h2 className="font-bold mb-2">Server Response</h2>
        <div className="relative w-full rounded bg-gray-200 h-[320px] overflow-hidden">
          {/* Video element is hidden but still needed for reference */}
          <video 
            ref={remoteVideoRef} 
            autoPlay 
            playsInline
            className="w-full h-full object-cover" 
            style={{display: 'none'}}
          />
          {/* Canvas will be dynamically inserted here */}
        </div>
        <div className="mt-2">
          <audio 
            ref={remoteAudioRef} 
            autoPlay 
            controls 
            className="w-full" 
          />
          {/* Audio visualizer canvas */}
          <canvas 
            ref={audioVisualizerCanvasRef}
            className="w-full h-[50px] mt-1 bg-gray-900 rounded"
            width={300}
            height={50}
          />
        </div>
      </div>
      
      {/* Test buttons */}
      <div className="col-span-full mt-4 flex justify-center space-x-4">
        <button 
          onClick={() => {
            // Send test packets to verify connection
            if (audioWS.current?.readyState === WebSocket.OPEN) {
              const testAudio = new Uint8Array(100);
              for (let i = 0; i < 100; i++) testAudio[i] = i % 256;
              audioWS.current.send(testAudio.buffer);
              console.log("Sent test audio packet");
            }
            
            if (videoWS.current?.readyState === WebSocket.OPEN) {
              const testVideo = new Uint8Array(100);
              for (let i = 0; i < 100; i++) testVideo[i] = (i + 128) % 256;
              videoWS.current.send(testVideo.buffer);
              console.log("Sent test video packet");
            }
          }}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
        >
          Send Test Packets
        </button>
        
        <button 
          onClick={() => {
            stopMediaCapture();
            startMediaCapture();
          }}
          className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
        >
          Restart Media Capture
        </button>

        <button 
          onClick={() => {
            // Force audio context to resume
            if (audioContextRef.current && audioContextRef.current.state === 'suspended') {
              audioContextRef.current.resume().then(() => {
                console.log("AudioContext resumed by button click");
              });
            }
            
            // Also try to play any audio element
            if (remoteAudioRef.current) {
              remoteAudioRef.current.play().catch(e => 
                console.warn("Couldn't force play audio element:", e)
              );
            }
          }}
          className="px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700"
        >
          Force Audio Resume
        </button>
      </div>
    </div>
  );
}