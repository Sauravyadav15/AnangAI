import { useState, useCallback } from 'react'

const API_BASE_URL = import.meta.env.VITE_API_URL || '' 

/**
 * Hook for connecting to backend chat API.
 * Handles trip queries using RAG with restaurants, places, and events data.
 * @returns {{ ask: (prompt: string, language?: string) => Promise<string>, isThinking: boolean, error: string | null }}
 */
export function useGemini() {
  const [isThinking, setIsThinking] = useState(false)
  const [error, setError] = useState(null)

  const ask = useCallback(async (userPrompt, language = 'en') => {
    setIsThinking(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE_URL}/api/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ question: userPrompt, language: language }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      return data.answer || 'Sorry, I received an empty response.'
    } catch (err) {
      const msg = err.message ?? 'Something went wrong.'
      setError(msg)
      // Return user-friendly error message
      if (msg.includes('Failed to fetch') || msg.includes('NetworkError')) {
        return 'Sorry, I couldn\'t connect to the server. Please make sure the backend is running on http://localhost:8000'
      }
      return `Sorry, I couldn't process that. ${msg}`
    } finally {
      setIsThinking(false)
    }
  }, [])

  return { ask, isThinking, error }
}
