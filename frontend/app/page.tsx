"use client"

import type React from "react"
import { useState, useRef, useEffect } from "react"
import { Terminal, ChevronUp, ChevronDown } from "lucide-react"
import { Navbar } from './components/Navbar'
import { useNotification } from './components/NotificationContainer'

export default function Home() {
  const [isBrowserFocused, setIsBrowserFocused] = useState(false)
  const [isStreamActive, setIsStreamActive] = useState(true)
  const [coordinates, setCoordinates] = useState({ x: 0, y: 0, browserX: 0, browserY: 0 })
  const [url, setUrl] = useState("")
  const [consoleMessages, setConsoleMessages] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [isTerminalOpen, setIsTerminalOpen] = useState(false)
  const [statusMessage, setStatusMessage] = useState<{ text: string; isError: boolean } | null>(null)
  const [screenshotData, setScreenshotData] = useState<string | null>(null)
  const [performanceMode, setPerformanceMode] = useState<'high' | 'medium' | 'low'>('high')
  const [isBrowserRunning, setIsBrowserRunning] = useState(false)

  const screenshotRef = useRef<HTMLImageElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const keyboardInputRef = useRef<HTMLInputElement>(null)
  const directStreamIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const scrollAccumulatorRef = useRef<{ deltaX: number; deltaY: number }>({ deltaX: 0, deltaY: 0 })
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  
  const { showNotification } = useNotification()

  const STREAM_INTERVALS = {
    high: 50,
    medium: 100,
    low: 200
  }

  // Setup backend API URL
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000'

  useEffect(() => {
    // Check browser status on component mount
    checkBrowserStatus()
    return () => {
      // Clean up streaming on unmount
      if (directStreamIntervalRef.current) {
        clearInterval(directStreamIntervalRef.current)
      }
    }
  }, [])

  // Adjust overlay when screenshot loads
  const handleScreenshotLoad = () => {
    if (screenshotRef.current && overlayRef.current) {
      const imgRect = screenshotRef.current.getBoundingClientRect()
      const imgNaturalWidth = screenshotRef.current.naturalWidth
      const imgNaturalHeight = screenshotRef.current.naturalHeight
      
      console.log(`Image loaded:
          Display size: ${imgRect.width} x ${imgRect.height}
          Natural size: ${imgNaturalWidth} x ${imgNaturalHeight}
      `)
      
      // Ensure overlay matches image exactly
      const parentRect = screenshotRef.current.parentElement?.getBoundingClientRect() || imgRect
      overlayRef.current.style.top = '0px'
      overlayRef.current.style.left = '0px'
      overlayRef.current.style.width = `${imgRect.width}px`
      overlayRef.current.style.height = `${imgRect.height}px`
    }
  }

  const logToConsole = (message: string, isError = false) => {
    const timestamp = new Date().toLocaleTimeString()
    setConsoleMessages((prev) => [...prev, `${timestamp}: ${message}`])
  }

  const showStatus = (message: string, isError = false) => {
    // Still update the status message for backward compatibility
    setStatusMessage({ text: message, isError })
    setTimeout(() => setStatusMessage(null), 5000)
    
    // But also show a notification
    showNotification(
      isError ? 'error' : 'success',
      isError ? 'Error' : 'Status',
      message
    )
    
    logToConsole(message, isError)
  }

  const checkBrowserStatus = async () => {
    try {
      logToConsole("Checking browser status...")
      setLoading(true)
      
      const response = await fetch(`${API_URL}/browser_status`)
      const data = await response.json()
      
      setIsBrowserRunning(data.running)
      const status = data.running ? "Browser is running" : "Browser is not running"
      showStatus(status)
      
      if (data.running && isStreamActive) {
        startDirectStreaming()
      }
      
      setLoading(false)
    } catch (error) {
      setLoading(false)
      showStatus(`Error checking browser status: ${error}`, true)
    }
  }

  const startBrowser = async () => {
    try {
      logToConsole("Starting browser...")
      setLoading(true)
      
      const response = await fetch(`${API_URL}/start_browser`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      
      const data = await response.json()
      setLoading(false)
      
      if (data.status === 'success') {
        setIsBrowserRunning(true)
        showStatus(data.message)
        if (isStreamActive) {
          startDirectStreaming()
        }
      } else {
        showStatus(data.message, true)
      }
    } catch (error) {
      setLoading(false)
      showStatus(`Error starting browser: ${error}`, true)
    }
  }

  const stopBrowser = async () => {
    try {
      logToConsole("Stopping browser...")
      setLoading(true)
      
      const response = await fetch(`${API_URL}/stop_browser`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      })
      
      const data = await response.json()
      setLoading(false)
      
      if (data.status === 'success') {
        setIsBrowserRunning(false)
        showStatus(data.message)
        stopDirectStreaming()
      } else {
        showStatus(data.message, true)
      }
    } catch (error) {
      setLoading(false)
      showStatus(`Error stopping browser: ${error}`, true)
    }
  }

  const navigate = async () => {
    if (!url.trim()) {
      showStatus('Please enter a URL', true)
      return
    }
    
    try {
      logToConsole(`Navigating to: ${url}`)
      setLoading(true)
      
      const response = await fetch(`${API_URL}/navigate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() })
      })
      
      const data = await response.json()
      setLoading(false)
      
      if (data.status === 'success') {
        showStatus(data.message)
      } else {
        showStatus(data.message, true)
      }
    } catch (error) {
      setLoading(false)
      showStatus(`Error navigating to URL: ${error}`, true)
    }
  }

  const startDirectStreaming = () => {
    stopDirectStreaming()
    
    logToConsole("Starting direct streaming...")
    
    directStreamIntervalRef.current = setInterval(async () => {
      try {
        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 500)
        
        const response = await fetch(`${API_URL}/get_screenshot_data`, { 
          signal: controller.signal 
        })
        
        clearTimeout(timeoutId)
        const data = await response.json()
        
        if (data.data) {
          setScreenshotData(data.data)
        }
      } catch (error) {
        if (error instanceof Error && error.name !== 'AbortError') {
          console.error('Error fetching screenshot:', error)
        }
      }
    }, STREAM_INTERVALS[performanceMode])
    
    setIsStreamActive(true)
  }

  const stopDirectStreaming = () => {
    if (directStreamIntervalRef.current) {
      clearInterval(directStreamIntervalRef.current)
      directStreamIntervalRef.current = null
      logToConsole("Stopped direct streaming")
      setIsStreamActive(false)
    }
  }

  const performClick = async (x: number, y: number) => {
    try {
      logToConsole(`Clicking at coordinates: (${x}, ${y})`)
      setLoading(true)
      
      const response = await fetch(`${API_URL}/click`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ x, y })
      })
      
      const data = await response.json()
      setLoading(false)
      
      if (data.status === 'success') {
        showStatus(data.message)
      } else {
        showStatus(data.message, true)
      }
    } catch (error) {
      setLoading(false)
      showStatus(`Error performing click: ${error}`, true)
    }
  }

  const handleKeyInput = async (text: string) => {
    if (!text) return
    
    try {
      logToConsole(`Sending text input: "${text}"`)
      
      const response = await fetch(`${API_URL}/type_text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      })
      
      const data = await response.json()
      
      if (data.status !== 'success') {
        showStatus(data.message, true)
      }
    } catch (error) {
      showStatus(`Error sending text input: ${error}`, true)
    }
  }

  const handleSpecialKey = async (key: string, shift: boolean = false) => {
    try {
      const keyToSend = key === 'Enter' ? 'ENTER' : 'BACK_SPACE'
      logToConsole(`Sending special key: ${keyToSend}`)
      
      const response = await fetch(`${API_URL}/send_key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          key: keyToSend,
          modifiers: { shift }
        })
      })
      
      const data = await response.json()
      
      if (data.status !== 'success') {
        showStatus(data.message, true)
      }
    } catch (error) {
      showStatus(`Error sending key: ${error}`, true)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === 'Backspace') {
      e.preventDefault()
      handleSpecialKey(e.key, e.shiftKey)
    }
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const text = e.target.value
    if (text) {
      handleKeyInput(text)
      e.target.value = ''
    }
  }

  const handleMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!screenshotRef.current) return

    const rect = screenshotRef.current.getBoundingClientRect()
    const canvasWidth = rect.width
    const canvasHeight = rect.height
    const browserWidth = 1920
    const browserHeight = 1080

    // Calculate scale factors
    const scaleX = browserWidth / canvasWidth 
    const scaleY = browserHeight / canvasHeight

    // Get local coordinates relative to the canvas
    const localX = Math.round(event.clientX - rect.left)
    const localY = Math.round(event.clientY - rect.top)

    // Scale coordinates to browser dimensions
    const browserX = Math.round(localX * scaleX)
    const browserY = Math.round(localY * scaleY)

    setCoordinates({ 
      x: localX, 
      y: localY / 2, 
      browserX, 
      browserY 
    })
  }

  const handleOverlayClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!screenshotRef.current) return
    
    setIsBrowserFocused(true)
    if (keyboardInputRef.current) {
      keyboardInputRef.current.focus()
    }
    
    const rect = screenshotRef.current.getBoundingClientRect()
    const canvasWidth = rect.width // 966.86
    const canvasHeight = rect.height // 474.44
    
    // Calculate click location in local coordinates
    const localX = Math.round(event.clientX - rect.left)
    const localY = Math.round(event.clientY - rect.top)
    
    // Calculate the percentages across the canvas
    const percentX = localX / canvasWidth
    const percentY = localY / canvasHeight
    
    // Apply percentages to the actual browser dimensions
    // Assuming the headless browser is actually 1920×1080
    const browserX = Math.round(percentX * 1920)
    const browserY = Math.round(percentY * 966)
    
    console.log('Click coordinates:', { 
      canvasWidth, canvasHeight,
      localX, localY, 
      percentX, percentY,
      browserX, browserY 
    })
    
    performClick(browserX, browserY)
    
  }

  const handleScroll = async (deltaX: number, deltaY: number) => {
    try {
      logToConsole(`Scrolling by: (${deltaX}, ${deltaY})`)
      console.log(`Sending scroll request to ${API_URL}/scroll with:`, { deltaX, deltaY })
      
      const response = await fetch(`${API_URL}/scroll`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deltaX, deltaY })
      })
      
      console.log('Scroll API response status:', response.status)
      const data = await response.json()
      console.log('Scroll API response data:', data)
      
      if (data.status === 'success') {
        logToConsole(`Scroll position: (${data.position[0]}, ${data.position[1]})`)
      } else {
        showStatus(data.message, true)
      }
    } catch (error) {
      console.error('Scroll API error:', error)
      showStatus(`Error performing scroll: ${error}`, true)
    }
  }

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    // Prevent default behavior
    event.preventDefault()
    
    // Debug output
    console.log('Wheel event detected:', { 
      deltaX: event.deltaX,
      deltaY: event.deltaY,
      isBrowserFocused
    })
    
    // Only process if browser is focused
    if (!isBrowserFocused) {
      console.log('Ignoring wheel event - browser not focused')
      return
    }
    
    // Accumulate scroll deltas
    const scrollAccumulator = scrollAccumulatorRef.current
    scrollAccumulator.deltaX += event.deltaX
    scrollAccumulator.deltaY += event.deltaY
    
    console.log('Accumulated scroll:', scrollAccumulator)
    
    // Clear any existing timeout
    if (scrollTimeoutRef.current) {
      clearTimeout(scrollTimeoutRef.current)
    }
    
    // Set a new timeout to send the accumulated scroll after a brief delay
    scrollTimeoutRef.current = setTimeout(() => {
      if (scrollAccumulator.deltaX !== 0 || scrollAccumulator.deltaY !== 0) {
        console.log('Sending scroll request with:', scrollAccumulator)
        handleScroll(scrollAccumulator.deltaX, scrollAccumulator.deltaY)
        // Reset accumulator after sending
        scrollAccumulatorRef.current = { deltaX: 0, deltaY: 0 }
      }
    }, 50) // 150ms debounce - adjust as needed
  }

  // Clean up the timeout on component unmount
  useEffect(() => {
    return () => {
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current)
      }
    }
  }, [])

  return (
    <div className="cyberContainer">
      <Navbar 
        consoleMessages={consoleMessages}
        isTerminalOpen={isTerminalOpen}
        setIsTerminalOpen={setIsTerminalOpen}
      />

      <div className="asciiHeader">
        <pre className="asciiArt">
          {`
 ┌───────────────────────────────────────────────────────────────────────────┐
 │  ██████╗ ██████╗ ██╗███████╗███╗   ███╗ █████╗ ████████╗██╗ ██████╗ █████╗│
 │  ██╔══██╗██╔══██╗██║██╔════╝████╗ ████║██╔══██╗╚══██╔══╝██║██╔════╝██╔══██║
 │  ██████╔╝██████╔╝██║███████╗██╔████╔██║███████║   ██║   ██║██║     ███████║
 │  ██╔═══╝ ██╔══██╗██║╚════██║██║╚██╔╝██║██╔══██║   ██║   ██║██║     ██╔══██║
 │  ██║     ██║  ██║██║███████║██║ ╚═╝ ██║██║  ██║   ██║   ██║╚██████╗██║  ██║
 │  ╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝╚═╝  ╚═╝
 └───────────────────────────────────────────────────────────────────────────┘
    `}
        </pre>
        <div className="prismaticEffect"></div>
      </div>

      <div className="mainInterface">
        <div className="monitorFrame">
          <div className="browserHeader">
            <div className="controlPanel">
              <div className="controlRow">
                <button 
                  className="cyberButton" 
                  onClick={startBrowser}
                  disabled={isBrowserRunning}
                >
                  <span className="buttonGlow"></span>
                  <span>Start Browser</span>
                </button>
                <button 
                  className="cyberButton" 
                  onClick={stopBrowser}
                  disabled={!isBrowserRunning}
                >
                  <span className="buttonGlow"></span>
                  <span>Stop Browser</span>
                </button>
                <button 
                  className="cyberButton" 
                  onClick={checkBrowserStatus}
                >
                  <span className="buttonGlow"></span>
                  <span>Check Status</span>
                </button>
                <div className="streamControls">
                  <button
                    className={`cyberButton ${isStreamActive ? "active" : ""}`}
                    onClick={() => isStreamActive ? stopDirectStreaming() : startDirectStreaming()}
                  >
                    <span className="buttonGlow"></span>
                    <span>Toggle Stream</span>
                  </button>
                  <div className={`streamStatus ${isStreamActive ? "connected" : "disconnected"}`}>
                    <span className="statusDot"></span>
                    <span>Stream: {isStreamActive ? "ACTIVE" : "PAUSED"}</span>
                  </div>
                </div>
                <div className="coordinates">
                  <span className="coordLabel">LOCAL:</span> [{coordinates.x}, {coordinates.y}]
                  <span className="coordLabel">REMOTE:</span> [{coordinates.browserX}, {coordinates.browserY}]
                </div>
              </div>

              <div className="urlControl">
                <div className="urlInputWrapper">
                  <Terminal size={16} className="urlIcon" />
                  <input
                    type="text"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="Enter URL to navigate"
                    className="urlInput"
                    onKeyDown={(e) => e.key === 'Enter' && navigate()}
                  />
                </div>
                <button 
                  className="cyberButton"
                  onClick={navigate}
                >
                  <span className="buttonGlow"></span>
                  <span>Navigate</span>
                </button>
              </div>

             

          

            </div>
          </div>
          <div className={`browserView ${isBrowserFocused ? "focused" : ""}`}>
            {loading && (
              <div className="loading">
                <div className="loadingText">LOADING...</div>
                <div className="loadingBar">
                  <div className="loadingProgress"></div>
                </div>
              </div>
            )}
            <img
              ref={screenshotRef}
              className="screenshot"
              src={screenshotData ? `data:image/png;base64,${screenshotData}` : "/placeholder.svg?height=1080&width=1920"}
              alt="Browser Screenshot"
              onLoad={handleScreenshotLoad}
            />
            <div 
              ref={overlayRef}
              className="overlay" 
              onMouseMove={handleMouseMove} 
              onClick={handleOverlayClick}
              onWheel={handleWheel}
            />
            <input 
              ref={keyboardInputRef}
              type="text" 
              className="keyboardInput" 
              autoComplete="off"
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

