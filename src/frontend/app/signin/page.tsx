'use client'

import { useState, FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { signin, getToken } from '@/utils/api'

export default function SigninPage() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsLoading(true)
    try {
      const { access_token } = await signin(username, password)
      localStorage.setItem('token', access_token)
      const params = new URLSearchParams(window.location.search)
      const redirect = params.get('redirect')
      router.replace(redirect || '/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid credentials')
      setIsLoading(false)
    }
  }

  const handleDemoSignin = async () => {
    setError(null)
    setIsLoading(true)
    try {
      const { access_token } = await getToken('demo', 'demo')
      localStorage.setItem('token', access_token)
      const params = new URLSearchParams(window.location.search)
      const redirect = params.get('redirect')
      router.replace(redirect || '/room/demo')
    } catch (_err) {
      setError('Failed to sign in with demo account')
      setIsLoading(false)
    }
  }

  return (
    <div className="h-screen flex items-center justify-center">
      <div className="p-6 bg-white rounded shadow w-80">
        <h2 className="text-2xl mb-4">Sign In</h2>
        {error && (
          <div className="mb-4 p-2 text-red-700 bg-red-100 rounded">{error}</div>
        )}
        <form onSubmit={handleSubmit}>
          <input
            className="w-full mb-3 px-3 py-2 border rounded"
            placeholder="Username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            disabled={isLoading}
          />
          <input
            className="w-full mb-4 px-3 py-2 border rounded"
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            disabled={isLoading}
          />
          <button
            type="submit"
            className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700"
            disabled={isLoading}
          >
            {isLoading ? 'Signing In...' : 'Sign In'}
          </button>
        </form>
        <div className="mt-4 text-center">
          <span className="text-gray-500">or</span>
        </div>
        <button
          onClick={handleDemoSignin}
          className="w-full mt-4 bg-gray-200 text-gray-800 py-2 rounded hover:bg-gray-300"
          disabled={isLoading}
        >
          Try Demo Account
        </button>
        <div className="mt-4 text-center text-sm">
          Do not have an account?{' '}
          <a href="/signup" className="text-blue-500 hover:underline">
            Sign Up
          </a>
        </div>
      </div>
    </div>
  )
}