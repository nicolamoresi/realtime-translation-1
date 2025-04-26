'use client'
import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { signup } from '@/utils/api'

export default function SignupPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    
    try {
      // Pass email to signup function
      await signup(username, email, password)
      router.push('/signin')
    } catch (err) {
      console.error('Signup error:', err)
      setError(err instanceof Error ? err.message : 'Failed to create account')
    }
  }

  return (
    <div className="h-screen flex items-center justify-center">
      <form onSubmit={handleSubmit} className="p-6 bg-white rounded shadow w-80">
        <h2 className="text-2xl mb-4">Sign Up</h2>
        
        {error && (
          <div className="mb-4 p-2 text-red-700 bg-red-100 rounded">
            {error}
          </div>
        )}
        
        <input
          className="w-full mb-3 px-3 py-2 border rounded"
          placeholder="Username"
          value={username}
          onChange={e => setUsername(e.target.value)}
          required
        />
        
        <input
          className="w-full mb-3 px-3 py-2 border rounded"
          type="email"
          placeholder="Email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          required
        />
        
        <input
          className="w-full mb-4 px-3 py-2 border rounded"
          type="password"
          placeholder="Password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          required
        />
        
        <button type="submit" className="w-full bg-green-500 text-white py-2 rounded">
          Create Account
        </button>
        
        <div className="mt-4 text-center text-sm">
          Already have an account?{' '}
          <a href="/signin" className="text-blue-500 hover:underline">
            Sign In
          </a>
        </div>
      </form>
    </div>
  )
}