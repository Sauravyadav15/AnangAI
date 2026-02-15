import { useState, useCallback } from 'react'

// Get API base URL from environment variable
// Empty string = use Vite proxy (for local development)
// Set to Vercel URL for production
const API_BASE_URL = (import.meta.env.VITE_API_URL || '').trim()

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
      // Create an AbortController for timeout handling
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 45000) // 45 second timeout
      
      // Use relative URL if API_BASE_URL is empty (for Vite proxy), otherwise use full URL
      // Ensure we don't double up on /api if API_BASE_URL already includes it
      let url
      if (!API_BASE_URL) {
        // Local development: use Vite proxy
        url = '/api/chat'
      } else {
        // Production: use full URL
        const base = API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL
        url = `${base}/api/chat`
      }
      
      console.log('Making request to:', url, { question: userPrompt, language })
      
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ question: userPrompt, language: language }),
        signal: controller.signal,
      })
      
      clearTimeout(timeoutId)
      
      console.log('Response status:', response.status, response.statusText)

      if (!response.ok) {
        // Handle 404 specifically
        if (response.status === 404) {
          const isProduction = window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1'
          if (isProduction) {
            throw new Error('API endpoint not found. The backend service may not be properly deployed.')
          } else {
            throw new Error('API endpoint not found. Please make sure the backend is running on http://localhost:8000')
          }
        }
        
        const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }))
        console.error('API Error:', errorData)
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      console.log('Response data received:', data)
      
      if (!data || !data.answer) {
        console.error('Invalid response format:', data)
        return 'Sorry, I received an empty response.'
      }
      
      return data.answer
    } catch (err) {
      const msg = err.message ?? 'Something went wrong.'
      setError(msg)
      // Return user-friendly error message
      if (err.name === 'AbortError' || msg.includes('aborted')) {
        return 'Sorry, the request took too long. Please try again with a simpler question or check your internet connection.'
      }
      if (msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('CORS')) {
        // Check if we're in production
        const isProduction = window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1'
        if (isProduction) {
          return 'Sorry, I couldn\'t connect to the API. The backend service may be temporarily unavailable. Please try again later.'
        } else {
          return 'Sorry, I couldn\'t connect to the server. Please make sure the backend is running on http://localhost:8000 and check the browser console for CORS errors.'
        }
      }
      if (msg.includes('CORS') || err.message?.includes('CORS')) {
        console.error('CORS Error detected. Make sure:');
        console.error('1. Backend is running on http://localhost:8000');
        console.error('2. Vite proxy is configured correctly in vite.config.js');
        console.error('3. You are accessing the frontend via http://localhost:5173 (not file://)');
        return 'CORS error: Please check that the backend is running and the Vite proxy is configured correctly.'
      }
      return `Sorry, I couldn't process that. ${msg}`
    } finally {
      setIsThinking(false)
    }
  }, [])

  return { ask, isThinking, error }
}
