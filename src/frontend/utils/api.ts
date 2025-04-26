export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'

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

// OAuth2 compatible token endpoint (for compatibility with some libraries)
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

// Function to get a demo token for testing
export async function getDemoToken() {
  const res = await fetch(`${API_BASE}/demo-token`)
  
  if (!res.ok) {
    throw new Error('Failed to get demo token');
  }
  
  return res.json()
}

// Function to get user profile
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