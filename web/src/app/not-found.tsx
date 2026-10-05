import Link from "next/link";
export default function NotFound() {
  return (
    <div className="page">
      <div className="empty-state">
        <h1>Page not found</h1>
        <p>This research location does not exist.</p>
        <Link className="button button-primary" href="/">
          Back to research
        </Link>
      </div>
    </div>
  );
}
