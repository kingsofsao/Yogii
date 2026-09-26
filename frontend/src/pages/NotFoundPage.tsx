import { Link } from "react-router-dom";
import { PageHeader } from "../components/ui";

export default function NotFoundPage() {
  return (
    <div>
      <PageHeader title="Page not found" subtitle="That page doesn't exist." />
      <Link to="/" className="font-semibold text-teal-700 underline">Go to your dashboard</Link>
    </div>
  );
}
