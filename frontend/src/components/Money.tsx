import { formatINR } from "../lib/format";

export default function Money({ amount, hidden, className }: { amount: string | number; hidden?: boolean; className?: string }) {
  if (hidden) return <span className={className} aria-label="Balance hidden">₹ ••••••</span>;
  return <span className={className}>{formatINR(amount)}</span>;
}
