import type { Metadata } from "next";

import "./styles.css";

export const metadata: Metadata = {
  title: "VisualOps Enterprise",
  description: "Facilities and property operations foundation",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
