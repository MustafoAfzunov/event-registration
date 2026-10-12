const btn = "px-2.5 py-1 rounded bg-surface-container text-on-surface-variant hover:text-on-surface disabled:opacity-40 disabled:hover:text-on-surface-variant";

/** "Showing 1–10 of 186" + Previous / page numbers / Next (client-side paging of the loaded list). */
export function Pagination({
  page,
  pageSize,
  total,
  noun,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  noun: string;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  // window of page numbers around the current page, always including first and last
  const numbers = [...new Set([1, page - 1, page, page + 1, pages])].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  return (
    <div className="p-space-md bg-surface-container-low/40 flex flex-col sm:flex-row items-center justify-between gap-space-sm font-body-sm text-body-sm text-on-surface-variant">
      <span>
        Showing <strong className="text-on-surface font-semibold">{from}–{to}</strong> of{" "}
        <strong className="text-on-surface font-semibold">{total}</strong> {noun}
      </span>
      {pages > 1 && (
        <nav aria-label="Pagination" className="flex items-center gap-space-xs">
          <button type="button" className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
          {numbers.map((n, i) => (
            <span key={n} className="flex items-center gap-space-xs">
              {i > 0 && n - (numbers[i - 1] ?? n) > 1 && <span className="px-1 text-outline">…</span>}
              <button
                type="button"
                aria-current={n === page ? "page" : undefined}
                className={n === page ? "px-2.5 py-1 rounded bg-primary text-on-primary font-semibold" : btn}
                onClick={() => onPage(n)}
              >
                {n}
              </button>
            </span>
          ))}
          <button type="button" className={btn} disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
        </nav>
      )}
    </div>
  );
}
