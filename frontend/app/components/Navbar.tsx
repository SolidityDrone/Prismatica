"use client"

import { useState } from "react"
import { Terminal, ChevronUp, ChevronDown } from "lucide-react"
import { Snapshot } from './snapshot'

interface NavbarProps {
  consoleMessages: string[]
  isTerminalOpen: boolean
  setIsTerminalOpen: (isOpen: boolean) => void
}

export function Navbar({ consoleMessages, isTerminalOpen, setIsTerminalOpen }: NavbarProps) {
  return (
    <div className="z-10 max-w-5xl w-full items-center justify-between font-mono text-sm lg:flex">
      <div className="fixed bottom-0 left-0 flex h-48 w-full items-end justify-center bg-gradient-to-t from-white via-white dark:from-black dark:via-black lg:static lg:h-auto lg:w-auto lg:bg-none">
        <button 
          className="terminalToggle" 
          onClick={() => setIsTerminalOpen(!isTerminalOpen)}
        >
          {isTerminalOpen ? <ChevronDown size={20} /> : <ChevronUp size={20} />}
        </button>

        <div className={`terminalPanel ${isTerminalOpen ? "open" : ""}`}>
          <div className="terminalHeader">
            <span>Terminal</span>
          </div>
          <div className="terminalContent">
            <div className="console">
              <div className="consoleHeader">
                <span className="consoleTitle">TERMINAL OUTPUT</span>
                <div className="consoleDots">
                  <span className="consoleDot"></span>
                  <span className="consoleDot"></span>
                  <span className="consoleDot"></span>
                </div>
              </div>
              <div className="consoleContent">
                {consoleMessages.length === 0 ? (
                  <div className="consoleWelcome">
                    <span className="consoleCursor">█</span> System ready. Awaiting input...
                  </div>
                ) : (
                  consoleMessages.map((message, index) => (
                    <div key={index} className="consoleMessage">
                      <span className="consolePrompt">&gt;</span> {message}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="fixed bottom-8 right-8">
        <Snapshot />
      </div>
    </div>
  )
} 