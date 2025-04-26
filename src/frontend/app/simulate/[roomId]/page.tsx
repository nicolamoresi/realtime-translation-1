'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useMediaStream } from '@/hooks/useMediaStream'
import { useUserMedia } from '@/hooks/useUserMedia'  // Import our new hook
import { attachMediaSource } from '@/utils/mediaUtils'

interface TranscriptEntry {
  id: string;
  original: string;
  translated: string;
  timestamp: Date;
}

export default function SimulatorPage() {
  const { roomId } = useParams<{ roomId: string }>();
  const [token, setToken] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<string>("Initializing...");
  const [useRealMedia, setUseRealMedia] = useState(false);  // State to toggle between simulation and real media
  const [browserCompatible, setBrowserCompatible] = useState(true);

  // Media element refs
  const backVideoRef = useRef<HTMLVideoElement>(null);
  const remoteAudioRef = useRef<HTMLAudioElement>(null);
  const localVideoRef = useRef<HTMLVideoElement>(null);  // For local camera preview
  
  // Get auth token from localStorage
  useEffect(() => {
    console.log("Checking for auth token...");
    const storedToken = localStorage.getItem('token');
    if (!storedToken) {
      console.log("No token found in localStorage");
      setError('Authentication token not found. Please sign in first.');
      setIsLoading(false);
      return;
    }
    
    console.log("Token retrieved successfully");
    setToken(storedToken);
    setConnectionStatus("Token retrieved, initializing connections...");
    
    const handleStorageChange = () => {
      const updatedToken = localStorage.getItem('token');
      setToken(updatedToken);
    };
    
    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, []);

  useEffect(() => {
    // Check if getUserMedia is supported
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      console.error("getUserMedia not supported in this browser");
      setBrowserCompatible(false);
      setError("Your browser doesn't support camera and microphone access. Please try Chrome, Firefox, or Edge.");
    }
  }, []);

  // Initialize WebSocket connections
  const { 
    connection: audioWS,
    isConnected: isAudioConnected,
    error: audioError
  } = useWebSocket(
    token ? `/ws/voice/${roomId}` : null,
    token,
    (msg) => {
      if (msg.transcript) {
        setTranscripts(prev => [
          ...prev, 
          {
            id: crypto.randomUUID(),
            original: msg.transcript!,
            translated: msg.translated || '',
            timestamp: new Date()
          }
        ]);
      }
    }
  );

  const { 
    connection: videoWS,
    isConnected: isVideoConnected,
    error: videoError
  } = useWebSocket(
    token ? `/ws/video/${roomId}` : null,
    token
  );

  // Handle WebSocket errors and connection status
  useEffect(() => {
    console.log("Connection status:", {
      audioConnected: isAudioConnected,
      videoConnected: isVideoConnected,
      audioError,
      videoError
    });

    if (audioError) {
      console.error("Audio WebSocket error:", audioError);
      setError(`Audio connection error: ${audioError}`);
    }
    
    if (videoError) {
      console.error("Video WebSocket error:", videoError);
      setError(`Video connection error: ${videoError}`);
    }
    
    // Set connection status messages
    if (!token) {
      setConnectionStatus("Waiting for authentication token...");
    } else if (!isAudioConnected && !isVideoConnected) {
      setConnectionStatus("Establishing WebSocket connections...");
    } else if (isAudioConnected && !isVideoConnected) {
      setConnectionStatus("Audio connected, waiting for video connection...");
    } else if (!isAudioConnected && isVideoConnected) {
      setConnectionStatus("Video connected, waiting for audio connection...");
    } else {
      setConnectionStatus("All connections established!");
    }
    
    // Only set connected when both WebSockets are connected
    setIsConnected(isAudioConnected && isVideoConnected);
    
    // Complete loading when everything is connected or if there's an error
    if ((isAudioConnected && isVideoConnected) || audioError || videoError) {
      setIsLoading(false);
    }
  }, [audioError, videoError, isAudioConnected, isVideoConnected, token]);

  // Safety timeout to prevent infinite loading
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (isLoading) {
        console.log("Loading timeout reached, forcing completion");
        setIsLoading(false);
        if (!error) {
          setError("Connection timed out. The server might be unavailable or your token may be invalid.");
        }
      }
    }, 15000); // 15 seconds timeout
    
    return () => clearTimeout(timeoutId);
  }, [isLoading, error]);

  // Setup media source extensions for received data
  useEffect(() => {
    if (!isConnected || !audioWS || !videoWS) return;
    
    console.log("Setting up media sources for connected WebSockets");
    try {
      if (remoteAudioRef.current) {
        attachMediaSource(remoteAudioRef.current, audioWS, 'audio/webm;codecs=opus');
      }
      
      if (backVideoRef.current) {
        attachMediaSource(backVideoRef.current, videoWS, 'video/webm;codecs=vp9');
      }
    } catch (err) {
      console.error("Media source setup error:", err);
      setError(`Failed to initialize media streams: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [audioWS, videoWS, isConnected]);

  // Setup simulation from sample video (when not using real media)
  const { cleanupMedia: cleanupSimulation } = useMediaStream({
    enabled: isConnected && !!audioWS && !!videoWS && !useRealMedia,
    audioWS,
    videoWS,
    videoPath: '/sample-data/presentation.mp4',
    audioChunkDuration: 250,
    videoFrameInterval: 200,
    onError: (err) => {
      console.error("Media streaming error:", err);
      setError(`Media streaming error: ${err}`);
    }
  });

  // Setup real user media
  const { 
    isStreaming: isStreamingUserMedia,
    hasPermissions,
    cleanupMedia: cleanupUserMedia,
    stream: userMediaStream
  } = useUserMedia({
    enabled: isConnected && !!audioWS && !!videoWS && useRealMedia,
    audioWS,
    videoWS,
    audioConstraints: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    },
    videoConstraints: {
      width: { ideal: 640 },
      height: { ideal: 480 },
      frameRate: { ideal: 15 }
    },
    onError: (err) => {
      console.error("User media error:", err);
      setError(`Camera/mic error: ${err}`);
    }
  });

  // Set local video stream
  useEffect(() => {
    if (localVideoRef.current && userMediaStream) {
      localVideoRef.current.srcObject = userMediaStream;
    }
  }, [userMediaStream]);

  // Cleanup function
  useEffect(() => {
    return () => {
      console.log("Cleaning up media resources");
      cleanupSimulation();
      cleanupUserMedia();
    };
  }, [cleanupSimulation, cleanupUserMedia]);

  // Function to retry connection
  const handleRetry = () => {
    setError(null);
    console.log("Manually retrying connections...");
    
    // Use a short timeout to allow React to update the UI first
    setTimeout(() => {
      // Force revalidation of token
      const token = localStorage.getItem('token');
      if (token) {
        console.log("Re-initializing with existing token");
        setToken(null); // Clear token first
        setTimeout(() => setToken(token), 100); // Set it again after a brief delay
      } else {
        console.log("No token available for retry");
        setError("Authentication token is missing. Please sign in again.");
      }
    }, 200);
  };

  // Toggle between simulation and real media
  const toggleMediaMode = () => {
    console.log("TOGGLE: Media mode changing from", useRealMedia ? "real media" : "simulation", "to", useRealMedia ? "simulation" : "real media");
    console.log("TOGGLE: WebSocket states:", {
      audioWS: audioWS?.readyState,
      videoWS: videoWS?.readyState,
      isConnected
    });

    if (useRealMedia) {
      console.log("TOGGLE: Cleaning up user media");
      cleanupUserMedia();
    } else {
      console.log("TOGGLE: Cleaning up simulation");
      cleanupSimulation();
    }

    setUseRealMedia(!useRealMedia);
  }

  // Render loading state
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center">
          <p>Connecting to room {roomId}...</p>
          <p className="text-sm text-gray-500 mt-2">{connectionStatus}</p>
          <button 
            onClick={handleRetry}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
      {error && (
        <div className="col-span-full mb-4 p-4 bg-red-100 text-red-800 rounded">
          <p className="font-bold">Error</p>
          <p>{error}</p>
          <button
            onClick={handleRetry}
            className="mt-2 px-3 py-1 bg-red-800 text-white rounded hover:bg-red-900"
          >
            Retry Connection
          </button>
        </div>
      )}
      <div className="col-span-full mb-2 text-sm items-center text-center">
        <p>Connection Status: 
          <span className={isAudioConnected ? "text-green-600" : "text-red-600"}>
            {" "}Audio: {audioWS ? ["Connecting", "Open", "Closing", "Closed"][audioWS.readyState] : "Not initialized"}
          </span>
          {" | "}
          <span className={isVideoConnected ? "text-green-600" : "text-red-600"}>
            Video: {videoWS ? ["Connecting", "Open", "Closing", "Closed"][videoWS.readyState] : "Not initialized"}
          </span>
        </p>
      </div>

      {useRealMedia && !browserCompatible && (
        <div className="col-span-full mb-4 p-3 bg-red-100 text-red-800 rounded text-center">
          <p>Your browser does not support camera and microphone access.</p>
          <p className="text-sm mt-1">Please try using Chrome, Firefox, or Edge instead.</p>
        </div>
      )}

      {/* Mode toggle */}
      <div className="col-span-full mb-4">
        <div className="flex items-center justify-center">
          <span className={`mr-2 ${!useRealMedia ? 'font-bold' : ''}`}>Sample Video</span>
          <button 
            onClick={toggleMediaMode}
            className="relative inline-flex items-center h-6 rounded-full w-11 bg-gray-300"
          >
            <span 
              className={`inline-block w-4 h-4 transform transition rounded-full bg-white ${useRealMedia ? 'translate-x-6' : 'translate-x-1'}`}
            />
          </button>
          <span className={`ml-2 ${useRealMedia ? 'font-bold' : ''}`}>Camera & Mic</span>
        </div>
      </div>

      {useRealMedia && hasPermissions === false && (
        <div className="col-span-full mt-2 mb-4 p-3 bg-yellow-100 text-yellow-800 rounded text-center">
          <p>Camera and microphone access is required for this feature.</p>
          <button
            onClick={() => {
              console.log("Explicitly requesting media permissions");
              navigator.mediaDevices.getUserMedia({
                audio: true,
                video: true
              }).then(stream => {
                console.log("Got permissions, tracks:", stream.getTracks().map(t => t.kind));
                // Stop these tracks immediately, the hook will request them again
                stream.getTracks().forEach(track => track.stop());
                // Force re-render
                setUseRealMedia(false);
                setTimeout(() => setUseRealMedia(true), 100);
              }).catch(err => {
                console.error("Permission error:", err);
                setError(`Camera/mic permission error: ${err.message}`);
              });
            }}
            className="mt-2 px-3 py-1 bg-yellow-600 text-white rounded hover:bg-yellow-700"
          >
            Request Camera & Mic Access
          </button>
        </div>
      )}
      
      {/* Local video preview (only when using real media) */}
      {useRealMedia && (
        <div>
          <h2 className="font-bold mb-2" id="local-video-heading">Your Camera</h2>
          <video 
            ref={localVideoRef} 
            autoPlay 
            muted 
            className="w-full rounded bg-gray-200"
            aria-labelledby="local-video-heading"
          />
          {hasPermissions === false && (
            <div className="mt-2 p-2 bg-yellow-100 text-yellow-800 rounded text-sm">
              Camera/microphone access denied. Please check your browser permissions.
            </div>
          )}
        </div>
      )}
      
      <div>
        <h2 className="font-bold mb-2" id="remote-video-heading">
          {useRealMedia ? 'Server Processed Video' : 'Sample Video'}
        </h2>
        <video 
          ref={backVideoRef} 
          autoPlay 
          muted 
          className="w-full rounded bg-gray-200"
          aria-labelledby="remote-video-heading"
        />
      </div>
      
      <div>
        <h2 className="font-bold mb-2" id="remote-audio-heading">Translated Audio</h2>
        <audio 
          ref={remoteAudioRef} 
          controls 
          className="w-full" 
          aria-labelledby="remote-audio-heading"
        />
      </div>
      
      <div className="col-span-full">
        <h2 className="font-bold mb-2" id="transcripts-heading">Transcripts</h2>
        <div 
          className="h-48 overflow-y-auto bg-gray-100 p-2 rounded"
          aria-labelledby="transcripts-heading"
          role="log"
          aria-live="polite"
        >
          {transcripts.length === 0 ? (
            <p className="text-gray-500 text-center p-4">
              {useRealMedia ? 'No transcripts yet. Start speaking to see translations.' : 'No transcripts yet from the sample video.'}
            </p>
          ) : (
            transcripts.map(entry => (
              <div key={entry.id} className="mb-2 p-2 bg-white rounded shadow-sm">
                <p className="text-sm font-medium">{entry.original}</p>
                <p className="text-sm text-gray-600">(en) {entry.translated}</p>
                <time className="text-xs text-gray-400">
                  {entry.timestamp.toLocaleTimeString()}
                </time>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="col-span-full mt-2 mb-4 flex justify-center">
        <button
          onClick={() => {
            console.log("🔍 DIRECT TEST: Testing direct streaming...");
            
            navigator.mediaDevices.getUserMedia({
              audio: true,
              video: true
            })
            .then(stream => {
              console.log("✅ DIRECT TEST: Got media stream");
              
              // Create a video preview
              const videoEl = document.createElement('video');
              videoEl.srcObject = stream;
              videoEl.autoplay = true;
              videoEl.muted = true;
              videoEl.style.position = 'fixed';
              videoEl.style.bottom = '10px';
              videoEl.style.right = '10px';
              videoEl.style.width = '200px';
              videoEl.style.zIndex = '9999';
              document.body.appendChild(videoEl);
              
              // Add stop button
              const stopBtn = document.createElement('button');
              stopBtn.textContent = 'Stop Test';
              stopBtn.style.position = 'fixed';
              stopBtn.style.bottom = '215px';
              stopBtn.style.right = '10px';
              stopBtn.style.zIndex = '9999';
              stopBtn.style.padding = '5px';
              stopBtn.style.backgroundColor = 'red';
              stopBtn.style.color = 'white';
              document.body.appendChild(stopBtn);
              
              stopBtn.onclick = () => {
                stream.getTracks().forEach(t => t.stop());
                document.body.removeChild(videoEl);
                document.body.removeChild(stopBtn);
                alert("Test stopped");
              };
              
              alert("Test stream active! Check browser console for logs.\nA preview is now showing in the corner.");
            })
            .catch(err => {
              console.error("❌ Error accessing media:", err);
              alert(`Error: ${err.message}`);
            });
          }}
          className="ml-2 px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600"
        >
          Direct Stream Test
        </button>
        <button
          onClick={() => {
            console.log("🧪 TEST: Verifying WebSocket connection to backend");
            
            // Test if WebSocket can send data
            if (audioWS?.readyState === WebSocket.OPEN) {
              try {
                // Try sending a small test message
                const testData = new Uint8Array([0x54, 0x45, 0x53, 0x54]); // "TEST" in ASCII
                audioWS.send(testData.buffer);
                console.log("✅ TEST: Sent test data to audio WebSocket");
                
                // Send a small JSON message too to check text transmission
                audioWS.send(JSON.stringify({ type: "test", time: Date.now() }));
                console.log("✅ TEST: Sent JSON test to audio WebSocket");
              } catch (err) {
                console.error("❌ TEST: Failed to send to audio WebSocket:", err);
              }
            } else {
              console.error("❌ TEST: Audio WebSocket not open", audioWS?.readyState);
            }
            
            if (videoWS?.readyState === WebSocket.OPEN) {
              try {
                const testData = new Uint8Array([0x54, 0x45, 0x53, 0x54]); // "TEST" in ASCII
                videoWS.send(testData.buffer);
                console.log("✅ TEST: Sent test data to video WebSocket");
              } catch (err) {
                console.error("❌ TEST: Failed to send to video WebSocket:", err);
              }
            } else {
              console.error("❌ TEST: Video WebSocket not open", videoWS?.readyState);
            }
          }}
          className="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700"
        >
          Test WebSocket
        </button>
      </div>
    </div>
  );
}