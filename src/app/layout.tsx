import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fieldnote · Codex Fleet",
  description: "Private multi-homed Codex app-server and agent operations dashboard.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
