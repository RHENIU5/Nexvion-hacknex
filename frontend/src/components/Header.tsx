export default function Header({ onMenu, search, onSearch }: {
  onMenu: () => void;
  search: string;
  onSearch: (value: string) => void;
}) {
  return (
    <header className="glass-header mx-3 mt-3 flex items-center justify-between gap-3 px-4 py-3 sm:mx-4 sm:mt-4 sm:px-5">
      <div className="flex items-center gap-3">
        <button onClick={onMenu} aria-label="Documents" className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 lg:hidden">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
        </button>
        <div className="brand-mark" aria-hidden>
          <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M7 3.75h7l4 4V20a.75.75 0 0 1-.75.75h-10.5A.75.75 0 0 1 6 20V4.5a.75.75 0 0 1 .75-.75Z" />
            <path d="M14 4v4h4M9 12h6M9 15.5h6" />
          </svg>
        </div>
        <div className="min-w-0">
          <div className="truncate text-base font-bold leading-tight sm:text-lg">DocMind</div>
          <div className="hidden text-xs text-slate-500 sm:block">Multimodal Document Intelligence</div>
        </div>
      </div>
      <label className="search-field">
        <svg aria-hidden width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.3 4.3" />
        </svg>
        <input value={search} onChange={event => onSearch(event.target.value)} placeholder="Search documents…" aria-label="Search documents" />
      </label>
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-violet-600 text-sm font-semibold text-white shadow-md shadow-blue-500/20">U</div>
    </header>
  );
}
