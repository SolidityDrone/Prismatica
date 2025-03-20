"use client"

import { useState, useEffect } from "react"
import { X } from "lucide-react"

export type NotificationType = "success" | "error" | "info"

interface NotificationProps {
  type: NotificationType
  title: string
  message: string
  duration?: number // in milliseconds, defaults to 5000
  onClose?: () => void
}

export function Notification({ 
  type, 
  title, 
  message, 
  duration = 5000, 
  onClose 
}: NotificationProps) {
  const [isVisible, setIsVisible] = useState(true)
  
  useEffect(() => {
    // Auto-close notification after duration
    const timeout = setTimeout(() => {
      handleClose()
    }, duration)
    
    return () => clearTimeout(timeout)
  }, [duration])
  
  const handleClose = () => {
    // First animate out
    setIsVisible(false)
    
    // Then call the onClose callback after animation completes
    setTimeout(() => {
      if (onClose) onClose()
    }, 300) // match animation duration
  }
  
  return (
    <div 
      className={`notificationDialog ${type}`}
      style={{ 
        animation: isVisible ? 'slideIn 0.3s ease-out forwards' : 'slideOut 0.3s ease-in forwards'
      }}
    >
      <div className="notificationHeader">
        <span className={`notificationTitle ${type}`}>{title}</span>
        <button className="notificationClose" onClick={handleClose}>
          <X size={18} />
        </button>
      </div>
      <div className="notificationContent">
        {message}
      </div>
    </div>
  )
} 