// Implement a fix for the voice endpoint connection stability

import { useEffect, useRef, useState, useCallback } from 'react';
import { API_BASE } from '@/utils/api';

// Create the WebSocket base URL from the API_BASE
const WS_BASE = API_BASE.replace(/^http/, 'ws');

export interface WSMessage {
  transcript?: string;
  translated?: string;
  heartbeat?: boolean;
  [key: string]: any;
}

interface UseWebSocketReturn {
  connection: WebSocket | null;
  sendMessage: (data: string | ArrayBuffer) => boolean;
  isConnected: boolean;
  error: string | null;
}

export function useWebSocket(
  url: string | null,
  token: string | null,
  onMessage?: (message: WSMessage) => void,
  reconnectInterval = 5000,
  maxReconnectAttempts = 3
): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const lastActivityRef = useRef<number>(Date.now());
  const isVoiceEndpoint = url?.includes('/voice/');
  const isConnectingRef = useRef(false);
  const effectCleanupRef = useRef(false);
  const unmountingRef = useRef(false);
  const connectionStabilityTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const mountTimestampRef = useRef<number>(Date.now());
  
  // Add a component instance ID to help with debugging
  const instanceIdRef = useRef<string>(`ws-${Math.random().toString(36).substring(2, 9)}`);
  
  // Track effect runs to detect rapid re-renders
  const effectRunCountRef = useRef(0);
  
  // Create WebSocket connection
  const connectWebSocket = useCallback(() => {
    if (!url || !token) {
      console.log(`[${instanceIdRef.current}] Cannot connect WebSocket - missing URL or token`);
      return;
    }
    
    // Prevent multiple simultaneous connection attempts
    if (isConnectingRef.current) {
      console.log(`[${instanceIdRef.current}] Connection attempt already in progress, skipping`);
      return;
    }
    
    // Don't attempt to connect if unmounting or cleanup has been triggered
    if (unmountingRef.current || effectCleanupRef.current) {
      console.log(`[${instanceIdRef.current}] Unmounting or cleanup triggered, skipping new connection`);
      return;
    }
    
    isConnectingRef.current = true;
    
    // Calculate time since mount - prevent connections during rapid remounts
    const timeSinceMount = Date.now() - mountTimestampRef.current;
    if (timeSinceMount < 1000) {
      console.log(`[${instanceIdRef.current}] Recently mounted (${timeSinceMount}ms ago), adding delay before connection`);
      
      if (connectionStabilityTimeoutRef.current) {
        clearTimeout(connectionStabilityTimeoutRef.current);
      }
      
      connectionStabilityTimeoutRef.current = setTimeout(() => {
        connectionStabilityTimeoutRef.current = null;
        if (!unmountingRef.current && !effectCleanupRef.current) {
          console.log(`[${instanceIdRef.current}] Proceeding with delayed connection`);
          connectWebSocketInternal();
        }
      }, 1000);
      
      return;
    }
    
    connectWebSocketInternal();
    
    function connectWebSocketInternal() {
      try {
        // Clear any existing intervals
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }
        
        // Special handling for voice endpoint - more conservative approach
        if (isVoiceEndpoint) {
          console.log(`[${instanceIdRef.current}] Voice endpoint detected - using conservative connection handling`);
          
          // For voice endpoint, always close any existing connection and wait longer
          if (wsRef.current) {
            try {
              if (wsRef.current.readyState < 2) {
                console.log(`[${instanceIdRef.current}] Closing existing voice connection`);
                wsRef.current.close();
              }
              wsRef.current = null;
            } catch (err) {
              console.error(`[${instanceIdRef.current}] Error closing existing voice connection:`, err);
            }
            
            // Use a longer delay for voice endpoint to ensure proper cleanup
            setTimeout(() => {
              if (!unmountingRef.current && !effectCleanupRef.current) {
                createNewConnection();
              }
            }, 1000);
          } else {
            // If no existing connection, create a new one with slight delay
            setTimeout(() => {
              if (!unmountingRef.current && !effectCleanupRef.current) {
                createNewConnection();
              }
            }, 300);
          }
          return;
        }
        
        // For non-voice endpoints, standard approach
        if (wsRef.current && wsRef.current.readyState < 2) {
          console.log(`[${instanceIdRef.current}] Closing existing WebSocket connection: ${url}`);
          wsRef.current.close();
          setTimeout(() => {
            if (!unmountingRef.current && !effectCleanupRef.current) {
              createNewConnection();
            }
          }, 300);
        } else {
          createNewConnection();
        }
      } catch (err) {
        console.error(`[${instanceIdRef.current}] Failed to connect to ${url}:`, err);
        setError(`Failed to connect: ${err instanceof Error ? err.message : String(err)}`);
        setIsConnected(false);
        isConnectingRef.current = false;
      }
    }
    
    function createNewConnection() {
      try {
        // One final check before creating the connection
        if (unmountingRef.current || effectCleanupRef.current) {
          console.log(`[${instanceIdRef.current}] Unmounting or cleanup detected during connection creation, aborting`);
          isConnectingRef.current = false;
          return;
        }
        
        // Create new WebSocket connection with token as query parameter
        const baseUrl = url.startsWith('ws') ? url : `${WS_BASE}${url}`;
        const fullUrl = `${baseUrl}?token=${encodeURIComponent(token)}`;
        console.log(`[${instanceIdRef.current}] Connecting to WebSocket: ${fullUrl}`);
        
        const socket = new WebSocket(fullUrl);
        socket.binaryType = 'arraybuffer';
        
        // Set a property to track this socket instance
        (socket as any).__wsInstanceId = instanceIdRef.current;
        
        // Update last activity timestamp
        const updateActivity = () => {
          lastActivityRef.current = Date.now();
        };
        
        // Set reference early to prevent race conditions
        wsRef.current = socket;
        
        // Configure event handlers
        socket.onopen = () => {
          console.log(`[${instanceIdRef.current}] WebSocket connection established: ${url}`);
          
          // Check if unmounting or cleanup occurred during connection
          if (unmountingRef.current || effectCleanupRef.current) {
            console.log(`[${instanceIdRef.current}] Component unmounting/cleanup during connection, closing socket`);
            try {
              socket.close();
            } catch {}
            return;
          }
          
          setIsConnected(true);
          setError(null);
          reconnectAttemptsRef.current = 0;
          updateActivity();
          isConnectingRef.current = false;
          
          if (!isVoiceEndpoint) {
            // Start keep-alive pings for non-voice endpoints
            startPingInterval(socket, updateActivity);
          }
        };
        
        socket.onmessage = (event) => {
          updateActivity();
          
          // Check if this is the current socket
          if (wsRef.current !== socket) {
            console.log(`[${instanceIdRef.current}] Received message for old socket, ignoring`);
            return;
          }
          
          try {
            // Handle text messages
            if (typeof event.data === 'string' && onMessage) {
              const logData = event.data.length > 100 ? 
                `${event.data.substring(0, 100)}...` : event.data;
              console.log(`[${instanceIdRef.current}] Received text message from ${url}: ${logData}`);
                
              try {
                const parsedData = JSON.parse(event.data);
                
                // Ignore heartbeat messages for callback
                if (!parsedData.heartbeat || Object.keys(parsedData).length > 1) {
                  onMessage(parsedData);
                }
              } catch (parseErr) {
                console.error(`[${instanceIdRef.current}] Error parsing message:`, parseErr);
              }
            } else if (event.data instanceof ArrayBuffer) {
              console.log(`[${instanceIdRef.current}] Received binary message: ${event.data.byteLength} bytes`);
            }
          } catch (err) {
            console.error(`[${instanceIdRef.current}] Error processing message:`, err);
          }
        };
        
        socket.onclose = (event) => {
          console.log(`[${instanceIdRef.current}] WebSocket connection closed:`, {
            url,
            code: event.code,
            reason: event.reason,
            wasClean: event.wasClean,
            unmounting: unmountingRef.current
          });
          
          // Clear ping interval
          if (pingIntervalRef.current) {
            clearInterval(pingIntervalRef.current);
            pingIntervalRef.current = null;
          }
          
          // Only update state if this is still the current socket
          if (wsRef.current === socket) {
            setIsConnected(false);
            wsRef.current = null;  // Clear reference
          }
          
          isConnectingRef.current = false;
          
          // Don't attempt to reconnect if unmounting or cleanup triggered
          if (unmountingRef.current || effectCleanupRef.current) {
            console.log(`[${instanceIdRef.current}] Skipping reconnection - component cleanup triggered`);
            return;
          }
          
          // Handle reconnection logic
          if (!event.wasClean) {
            if (isVoiceEndpoint) {
              // For voice, limit retries
              if (reconnectAttemptsRef.current < 1) {
                reconnectAttemptsRef.current += 1;
                console.log(`[${instanceIdRef.current}] Voice endpoint reconnection attempt`);
                
                if (reconnectTimeoutRef.current) {
                  clearTimeout(reconnectTimeoutRef.current);
                }
                
                reconnectTimeoutRef.current = setTimeout(() => {
                  reconnectTimeoutRef.current = null;
                  if (!unmountingRef.current && !effectCleanupRef.current) {
                    connectWebSocket();
                  }
                }, 3000);
              } else {
                console.log(`[${instanceIdRef.current}] Voice maximum retries reached`);
                setError(`Voice connection failed after retry. Try refreshing the page.`);
              }
            } else {
              // Standard reconnection for other endpoints
              if (reconnectAttemptsRef.current < maxReconnectAttempts) {
                reconnectAttemptsRef.current += 1;
                
                const delay = reconnectInterval * Math.pow(1.5, reconnectAttemptsRef.current - 1);
                console.log(`[${instanceIdRef.current}] Reconnecting in ${delay}ms (${reconnectAttemptsRef.current}/${maxReconnectAttempts})`);
                
                if (reconnectTimeoutRef.current) {
                  clearTimeout(reconnectTimeoutRef.current);
                }
                
                reconnectTimeoutRef.current = setTimeout(() => {
                  reconnectTimeoutRef.current = null;
                  if (!unmountingRef.current && !effectCleanupRef.current) {
                    connectWebSocket();
                  }
                }, delay);
              } else {
                setError(`Connection failed after ${maxReconnectAttempts} attempts.`);
              }
            }
          }
        };
        
        socket.onerror = (event) => {
          console.error(`[${instanceIdRef.current}] WebSocket error:`, event);
          isConnectingRef.current = false;
          
          if (!isVoiceEndpoint) {
            setError(`WebSocket connection error`);
          }
        };
      } catch (err) {
        console.error(`[${instanceIdRef.current}] Failed to create connection:`, err);
        isConnectingRef.current = false;
      }
    }
  }, [url, token, maxReconnectAttempts, onMessage, reconnectInterval, isVoiceEndpoint]);
  
  // Function to set up ping interval
  const startPingInterval = useCallback((socket: WebSocket, updateActivity: () => void) => {
    // Send a ping every 15 seconds to keep the connection alive
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
    }
    
    // For voice endpoint, use a longer interval and no actual pings
    const pingInterval = isVoiceEndpoint ? 30000 : 15000;
    
    pingIntervalRef.current = setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) {
        // Check for inactivity
        const inactiveTime = Date.now() - lastActivityRef.current;
        if (inactiveTime > 60000) {
          console.log(`[${instanceIdRef.current}] Connection inactive for ${inactiveTime}ms, sending ping`);
        }
        
        try {
          if (isVoiceEndpoint) {
            // For voice endpoint, don't send pings - just update activity
            updateActivity();
          } else {
            // For other endpoints, send small ping message
            const pingData = new Uint8Array([1]);
            socket.send(pingData);
            updateActivity();
          }
        } catch (err) {
          console.error(`[${instanceIdRef.current}] Error sending ping:`, err);
        }
      } else if (socket.readyState !== WebSocket.CONNECTING) {
        console.log(`[${instanceIdRef.current}] WebSocket not open (state: ${socket.readyState}), clearing ping interval`);
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
          pingIntervalRef.current = null;
        }
      }
    }, pingInterval);
  }, [url, isVoiceEndpoint]);
  
  // Send message through WebSocket
  const sendMessage = useCallback((data: string | ArrayBuffer) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.warn(`[${instanceIdRef.current}] Cannot send message - WebSocket not open`);
      return false;
    }
    
    try {
      wsRef.current.send(data);
      lastActivityRef.current = Date.now(); // Update activity timestamp
      return true;
    } catch (err) {
      console.error(`[${instanceIdRef.current}] Error sending message:`, err);
      return false;
    }
  }, []);
  
  // Initialize connection when dependencies change
  useEffect(() => {
    const effectId = ++effectRunCountRef.current;
    console.log(`[${instanceIdRef.current}] WebSocket effect run #${effectId} for ${url}`);
    
    // Reset cleanup flags
    effectCleanupRef.current = false;
    unmountingRef.current = false;
    
    // Track rapid effect runs
    const currentTime = Date.now();
    const timeSinceMount = currentTime - mountTimestampRef.current;
    
    if (timeSinceMount < 500 && effectRunCountRef.current > 1) {
      console.log(`[${instanceIdRef.current}] Rapid effect re-runs detected (${effectRunCountRef.current} runs in ${timeSinceMount}ms)`);
    }
    
    // Use a more controlled connection approach
    let shouldConnect = false;
    let connectionDelay = 100;
    
    // Clear any previous connection attempt
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    
    if (connectionStabilityTimeoutRef.current) {
      clearTimeout(connectionStabilityTimeoutRef.current);
      connectionStabilityTimeoutRef.current = null;
    }
    
    if (url && token) {
      if (wsRef.current) {
        // For voice endpoints with existing connection, be more conservative
        if (isVoiceEndpoint && wsRef.current.readyState === WebSocket.OPEN) {
          console.log(`[${instanceIdRef.current}] Voice endpoint already has open connection, keeping it`);
          shouldConnect = false; // Skip reconnection
        } else if (wsRef.current.readyState < 2) {
          console.log(`[${instanceIdRef.current}] Closing existing connection (state: ${wsRef.current.readyState})`);
          try {
            wsRef.current.close();
          } catch (err) {
            console.error(`[${instanceIdRef.current}] Error closing connection:`, err);
          }
          wsRef.current = null;
          shouldConnect = true;
          connectionDelay = 800; // Longer delay after closing
        } else {
          shouldConnect = true;
        }
      } else {
        shouldConnect = true;
      }
    } else {
      // Clean up existing connections
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
      
      if (wsRef.current) {
        console.log(`[${instanceIdRef.current}] Closing connection due to missing url/token`);
        try {
          if (wsRef.current.readyState < 2) {
            wsRef.current.close();
          }
        } catch (err) {
          console.error(`[${instanceIdRef.current}] Error closing connection:`, err);
        }
        wsRef.current = null;
      }
    }
    
    // Set up connection with appropriate delay
    let connectionTimeout: NodeJS.Timeout | null = null;
    
    if (shouldConnect) {
      // For voice endpoint, use an even more conservative approach
      if (isVoiceEndpoint && effectRunCountRef.current > 1) {
        connectionDelay = Math.max(connectionDelay, 1500); // Longer delay for voice after first effect
      }
      
      console.log(`[${instanceIdRef.current}] Scheduling connection in ${connectionDelay}ms`);
      
      connectionTimeout = setTimeout(() => {
        connectionTimeout = null;
        if (!effectCleanupRef.current && !unmountingRef.current) {
          console.log(`[${instanceIdRef.current}] Executing scheduled connection`);
          connectWebSocket();
        } else {
          console.log(`[${instanceIdRef.current}] Skipping scheduled connection - cleanup triggered`);
        }
      }, connectionDelay);
    }
    
    return () => {
      unmountingRef.current = true;
      effectCleanupRef.current = true;
      
      console.log(`[${instanceIdRef.current}] Effect cleanup for run #${effectId}`, { url });
      
      // Clear timeouts
      if (connectionTimeout) {
        clearTimeout(connectionTimeout);
        connectionTimeout = null;
      }
      
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      
      if (connectionStabilityTimeoutRef.current) {
        clearTimeout(connectionStabilityTimeoutRef.current);
        connectionStabilityTimeoutRef.current = null;
      }
      
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = null;
      }
      
      // Only close if this is still a valid connection
      if (wsRef.current) {
        const socketState = wsRef.current.readyState;
        console.log(`[${instanceIdRef.current}] Closing WebSocket on cleanup (state: ${socketState})`, { url });
        
        try {
          if (socketState < 2) {
            wsRef.current.close();
          }
        } catch (err) {
          console.error(`[${instanceIdRef.current}] Error closing WebSocket:`, err);
        }
        
        wsRef.current = null;
      }
      
      // Reset connection state
      isConnectingRef.current = false;
    };
  }, [connectWebSocket, url, token, isVoiceEndpoint]);
  
  return {
    connection: wsRef.current,
    sendMessage,
    isConnected,
    error
  };
}