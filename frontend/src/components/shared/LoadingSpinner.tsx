export function LoadingSpinner({ text = "Loading..." }: { text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-64 gap-4">
      <div className="w-12 h-12 rounded-full border-2 border-sg-outline border-t-sg-primary animate-spin" />
      <span className="text-sm text-sg-text-muted tracking-wide">{text}</span>
    </div>
  );
}
