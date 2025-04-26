import Link from 'next/link'

export default function Home() {
  return (
    <main className="h-screen flex flex-col items-center justify-center">
      <h1 className="text-3xl font-bold mb-6">Welcome</h1>
      <div className="flex space-x-4">
        <Link href="/signup">
          <button className="px-4 py-2 bg-green-500 text-white rounded">Sign Up</button>
        </Link>
        <Link href="/signin">
          <button className="px-4 py-2 bg-blue-500 text-white rounded">Sign In</button>
        </Link>
      </div>
    </main>
  )
}