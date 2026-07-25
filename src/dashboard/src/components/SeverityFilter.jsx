const LEVELS = ["LOW", "MEDIUM", "HIGH"];

export function SeverityFilter({ active, onToggle }) {
  return (
    <div className="severity-filter" role="group" aria-label="Filter by severity">
      {LEVELS.map((level) => (
        <button
          key={level}
          type="button"
          className={active.has(level) ? `filter-btn on sev-${level}` : "filter-btn"}
          aria-pressed={active.has(level)}
          onClick={() => onToggle(level)}
        >
          {level}
        </button>
      ))}
    </div>
  );
}
