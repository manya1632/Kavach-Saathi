import "./globals.css";

export const metadata = {
  title: "Kavach Saathi Shop",
  description: "An agent-powered social commerce storefront.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
