export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8082'
export const ORCHESTRATOR = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8081'

// Authentication functions - keep existing ones

export async function signup(username: string, email: string, password: string) {
  const res = await fetch(`${API_BASE}/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, email, password })
  })
  
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({
      detail: 'An unknown error occurred'
    }));
    throw new Error(errorData.detail || 'Failed to create account');
  }
  
  return res.json()
}

export async function signin(username: string, password: string) {
  const res = await fetch(`${API_BASE}/signin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
  
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({
      detail: 'Invalid credentials'
    }));
    throw new Error(errorData.detail || 'Failed to sign in');
  }
  
  return res.json()
}

export async function getAnonymousAccess(roomId: string) {
  const response = await fetch(`${API_BASE}/anonymous-access/${roomId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json'
    }
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to get anonymous access');
  }
  
  return response.json();
}

// OAuth2 token endpoint
export async function getToken(username: string, password: string) {
  const res = await fetch(`${API_BASE}/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      username,
      password,
      grant_type: 'password'
    })
  })
  
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({
      detail: 'Authentication failed'
    }));
    throw new Error(errorData.detail || 'Failed to get token');
  }
  
  return res.json()
}

// User profile
export async function getUserProfile(token: string) {
  const res = await fetch(`${API_BASE}/me`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  })
  
  if (!res.ok) {
    throw new Error('Failed to get user profile');
  }
  
  return res.json()
}

// ---- NEW CHAT API ENDPOINTS ----

// Start a new chat session
export async function startChatSession(token: string) {
  const res = await fetch(`${API_BASE}/chat/start`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  });
  
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({
      detail: 'Failed to start chat session'
    }));
    throw new Error(errorData.detail);
  }
  
  return res.json();
}

// Send a text message
export async function sendChatMessage(
  sessionId: string,
  content?: string,
  audioBase64?: string
) {
  /* build JSON body – only one of the two keys */
  const body: Record<string, string> = {}
  if (content) body.content = content
  if (audioBase64) body.audio = audioBase64

  const res = await fetch(`${API_BASE}/chat/message`, {
    method: 'POST',
    headers: {
      'X-Session-ID': sessionId,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to send chat message')
  }
  return res.json()
}

// Stop a chat session
export async function stopChatSession(sessionId: string) {
  const res = await fetch(`${API_BASE}/chat/stop`, {
    method: 'POST',
    headers: {
      'X-Session-ID': sessionId,
      'Content-Type': 'application/json'
    }
  });
  
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({
      detail: 'Failed to stop chat session'
    }));
    throw new Error(errorData.detail);
  }
  
  return res.json();
}

// ROOM API (Azure Communication Rooms)

// Room participant type
export interface RoomParticipant {
  id: string;
  role: string;
  join_time?: string;
}

// Create a new room
// Only pass participants with valid ACS IDs (created via /acs/users)
export async function createRoom(validForMinutes: number, participants: Array<{ id: string; role: string }>) {
  // Optionally, validate ACS ID format here as well
  const acsIdRegex = /^8:[a-z]+:[\w-]+$/;
  for (const p of participants) {
    if (!acsIdRegex.test(p.id)) {
      throw new Error(`Invalid ACS ID: ${p.id}. Use /acs/users to create valid ACS users.`);
    }
  }
  try {
    const response = await fetch(`${API_BASE}/rooms`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        valid_for_minutes: validForMinutes,
        participants,
      }),
    });

    if (!response.ok) {
      throw new Error(`Failed to create room: ${response.statusText}`);
    }

    return await response.json(); // Returns the created room details
  } catch (error) {
    console.error('Error creating room:', error);
    throw error;
  }
}

// Get room details
export async function getRoom(roomId: string) {
  const res = await fetch(`${API_BASE}/rooms/${roomId}`)
  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || 'Failed to get room')
  }
  return res.json()
}

// List all rooms
export async function listRooms() {
  const res = await fetch(`${API_BASE}/rooms`)
  if (!res.ok) {
    throw new Error('Failed to list rooms')
  }
  return res.json()
}

// Get ACS token and userId for a room (for joining)
export async function getRoomToken(roomId: string) {
  const res = await fetch(`${API_BASE}/rooms/${roomId}/token`, { credentials: 'include' })
  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || 'Failed to get room token')
  }
  return res.json()
}

// Add or update participants in a room
export async function addOrUpdateParticipants(roomId: string, participants: RoomParticipant[]) {
  const res = await fetch(`${API_BASE}/rooms/${roomId}/participants`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participants })
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || 'Failed to add/update participants')
  }
  return res.json()
}

// Remove participants from a room
export async function removeParticipants(roomId: string, participantIds: string[]) {
  const res = await fetch(`${API_BASE}/rooms/${roomId}/participants/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participant_ids: participantIds })
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || 'Failed to remove participants')
  }
  return res.json()
}

// List participants in a room
export async function listParticipants(roomId: string) {
  const res = await fetch(`${API_BASE}/rooms/${roomId}/participants`)
  if (!res.ok) {
    throw new Error('Failed to list participants')
  }
  return res.json()
}