import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Operations Copilot — Evidence before action",
  description:
    "Ask your versioned documents, inspect page citations, and review proposed actions.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
