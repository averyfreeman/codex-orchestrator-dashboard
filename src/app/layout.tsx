import type { Metadata } from "next";
import "./globals.css";

/** Browser metadata shared by every dashboard route. */
export const metadata: Metadata = {
  title: "Fieldnote · Codex Fleet",
  description: "Private multi-homed Codex app-server and agent operations dashboard.",
};

/** Wrap dashboard routes in the document shell and global styles. */
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en" data-theme="dark"><body>{children}</body></html>;
}
