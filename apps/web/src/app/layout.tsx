import type { Metadata } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuroraShell } from "@/components/AuroraShell";
import { Brand } from "@/components/Brand";
import { PageTransition } from "@/components/PageTransition";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Integration-Agent",
  description:
    "Multi-agent schema mapping for AdventureWorks → AdventureWorksDW.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full text-white flex flex-col">
        <AuroraShell />
        <Brand />
        <PageTransition>{children}</PageTransition>
      </body>
    </html>
  );
}
