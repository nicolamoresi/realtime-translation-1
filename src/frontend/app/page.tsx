'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useRouter } from 'next/navigation'

export default function Home() {
  const [roomId, setRoomId] = useState('');
  const router = useRouter();

  const handleJoinRoom: React.FormEventHandler<HTMLFormElement> = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (roomId.trim()) {
      router.push(`/simulate/${roomId}?anonymous=true`);
    }
  };

  return (
    <main className="h-screen flex flex-col items-center justify-center bg-gradient-to-b from-blue-50 to-white">
      <h1 className="text-4xl font-bold mb-8 text-blue-700">Azure Real-time Translation</h1>
      
      <div className="w-full max-w-md p-8 bg-white rounded-lg shadow-lg border border-blue-100">
        <form onSubmit={handleJoinRoom} className="space-y-6">
          <div>
            <label htmlFor="roomId" className="block text-sm font-medium text-gray-700 mb-1">
              Enter Session Name
            </label>
            <input
              type="text"
              id="roomId"
              value={roomId}
              onChange={(e) => setRoomId(e.target.value)}
              className="block w-full px-4 py-3 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
              placeholder="my-session"
              required
            />
          </div>
          
          <button
            type="submit"
            className="w-full flex justify-center py-3 px-4 border border-transparent rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition duration-150"
          >
            Join as Guest
          </button>
        </form>
        
        <div className="mt-8 grid grid-cols-2 gap-4">
          <Link href="/signup" className="block">
            <button className="w-full py-3 px-4 bg-green-500 text-white rounded-md hover:bg-green-600 transition duration-150">
              Sign Up
            </button>
          </Link>
          <Link href="/signin" className="block">
            <button className="w-full py-3 px-4 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition duration-150">
              Sign In
            </button>
          </Link>
        </div>
        
        <div className="mt-6 text-center text-sm text-gray-500">
          <p>Azure-powered real-time translation service</p>
        </div>
      </div>
    </main>
  )
}