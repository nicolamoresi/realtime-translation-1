export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'

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