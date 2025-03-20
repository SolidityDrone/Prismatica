"use client"

import { useState, useEffect, createContext, useContext } from "react"
import { Notification, NotificationType } from "./Notification"

interface NotificationItem {
  id: string
  type: NotificationType
  title: string
  message: string
  duration?: number
}

interface NotificationContextType {
  showNotification: (type: NotificationType, title: string, message: string, duration?: number) => void
  clearNotifications: () => void
}

const NotificationContext = createContext<NotificationContextType>({
  showNotification: () => {},
  clearNotifications: () => {},
})

export const useNotification = () => useContext(NotificationContext)

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([])

  const showNotification = (
    type: NotificationType, 
    title: string, 
    message: string, 
    duration = 5000
  ) => {
    const id = Math.random().toString(36).substring(2, 9)
    setNotifications(prev => [...prev, { id, type, title, message, duration }])
  }

  const clearNotifications = () => {
    setNotifications([])
  }

  const removeNotification = (id: string) => {
    setNotifications(prev => prev.filter(notification => notification.id !== id))
  }

  return (
    <NotificationContext.Provider value={{ showNotification, clearNotifications }}>
      {children}
      <div className="notificationContainer">
        {notifications.map(notification => (
          <Notification
            key={notification.id}
            type={notification.type}
            title={notification.title}
            message={notification.message}
            duration={notification.duration}
            onClose={() => removeNotification(notification.id)}
          />
        ))}
      </div>
    </NotificationContext.Provider>
  )
} 