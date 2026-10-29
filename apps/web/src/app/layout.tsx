import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { SITE_NAME } from "@/lib/site";

import { Providers } from "./providers";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: SITE_NAME, template: `%s · ${SITE_NAME}` },
  description: "Accounting, payments, revenue attribution, salary and projects.",
  icons: {
    icon: [
      { url: "/icons/icon16.png", sizes: "16x16", type: "image/png" },
      { url: "/icons/icon48.png", sizes: "48x48", type: "image/png" },
      { url: "/icons/icon128.png", sizes: "128x128", type: "image/png" },
    ],
    apple: "/icons/icon128.png",
  },
};

// Applies the saved theme before first paint to avoid a light/dark flash.
const themeScript = `try{var t=localStorage.getItem("theme");if(t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
