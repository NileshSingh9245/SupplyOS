"use client";

import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { choicesQuery, type PricingScope } from "@/lib/pricing";

export function PricingPicker({ scope, kind, value, onChange, disabled = false }: {
  scope: PricingScope; kind: "customers" | "products"; value: string; onChange: (id: string) => void; disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const q = useDeferredValue(search.trim());
  const query = useQuery(choicesQuery(scope, kind, page, q));
  const rows = query.data;
  return <div className="space-y-2" data-testid={`pricing-${kind}-picker`}>
    <label className="data-label" htmlFor={`pricing-search-${kind}`}>Search {kind}</label>
    <input id={`pricing-search-${kind}`} className="input" maxLength={100} value={search} disabled={disabled}
      onChange={(event) => { setSearch(event.target.value); setPage(1); onChange(""); }} />
    {query.isFetching ? <p role="status" className="text-sm">Loading {kind}...</p> : null}
    {query.isError ? <div className="space-y-2"><p role="alert">The {kind} directory could not be loaded.</p>
      <button type="button" className="btn-ghost" onClick={() => void query.refetch()}>Retry {kind}</button></div> : rows && !query.isFetching ? <>
      <label className="data-label" htmlFor={`pricing-select-${kind}`}>Choose {kind === "customers" ? "customer" : "product"}</label>
      <select id={`pricing-select-${kind}`} className="input" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
        <option value="">Select from this page</option>
        {rows.items.map((row) => <option key={row.id} value={row.id}>{row.label}</option>)}
      </select>
      {!rows.items.length ? <p role="status">No {kind} match this search.</p> : null}
      <nav className="flex flex-wrap items-center gap-2" aria-label={`Pricing ${kind} pages`}>
        <button type="button" className="btn-ghost" disabled={disabled || page === 1} onClick={() => { setPage(page - 1); onChange(""); }}>Previous {kind}</button>
        <p className="text-xs">Page {page} / {rows.total} {kind}</p>
        <button type="button" className="btn-ghost" disabled={disabled || page * 50 >= rows.total} onClick={() => { setPage(page + 1); onChange(""); }}>Next {kind}</button>
      </nav>
    </> : null}
  </div>;
}
