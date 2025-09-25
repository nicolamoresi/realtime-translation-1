import type { Metadata } from "next";
import "./globals.css";
import { Inter, Roboto_Mono } from "next/font/google";

// Manteniamo i nomi delle variabili CSS usate nel progetto
const geistSans = Inter({
  subsets: ["latin"],
  variable: "--font-geist-sans",
  display: "swap",
});

const geistMono = Roboto_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});

// Se il tuo file usava export const metadata = {...} lascialo com’è

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        {children}
      </body>
    </html>
  );
}