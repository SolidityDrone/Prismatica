import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { NotificationProvider } from './components/NotificationContainer'

const inter = Inter({ subsets: ['latin'] })
import { headers } from 'next/headers' // added
import ContextProvider from '../context' 

export const metadata: Metadata = {
  title: 'AppKit Example App',
  description: 'Powered by Reown'
}

export default async function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode
}>) {

  const headersObj = await headers();
  const cookies = headersObj.get('cookie')

  return (
    <html lang="en">
      <body className={inter.className}>
        <NotificationProvider>
          <ContextProvider cookies={cookies}>{children}</ContextProvider>
        </NotificationProvider>
      </body>
    </html>
  )
}