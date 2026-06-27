"use client";

type Props = {
  config: { text: string };
};

// Minimal markdown: render plain text with line breaks. Avoid pulling in
// a markdown library for the MVP — admin-approved content only.
export default function Markdown({ config }: Props) {
  return (
    <div className="h-full p-4 overflow-auto whitespace-pre-wrap text-sm leading-relaxed">
      {config.text}
    </div>
  );
}
