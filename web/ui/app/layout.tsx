import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Image from "next/image";
import Link from "next/link";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "comprev — MF compliance review",
  description: "Review mutual-fund marketing videos for regulatory compliance.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="bg-background text-foreground min-h-full flex flex-col">
        <header className="border-border bg-background/80 sticky top-0 z-10 border-b backdrop-blur">
          <div className="mx-auto flex h-12 w-full max-w-3xl items-center gap-2 px-6 sm:px-12">
            <Link href="/" className="flex items-center gap-2 font-semibold">
              <Image
                src="/logo.png"
                alt="Stable Money"
                width={22}
                height={22}
                className="rounded-[5px]"
                priority
              />
              comprev
            </Link>
            <span className="text-muted-foreground hidden text-sm sm:inline">
              MF video compliance review
            </span>
            <nav className="ml-auto flex items-center gap-4 text-sm">
              <Link
                href="/"
                className="text-muted-foreground hover:text-foreground"
              >
                Reports
              </Link>
              <Link
                href="/policies"
                className="text-muted-foreground hover:text-foreground"
              >
                Policies
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10 sm:px-12">
          {children}
        </main>
        <Toaster richColors position="top-center" />
      </body>
    </html>
  );
}
