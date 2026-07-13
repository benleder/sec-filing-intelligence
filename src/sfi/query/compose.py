"""P0 composition: a deterministic template over evidence fields (J3).
Checked by construction — no audit needed. The LLM composer + numeral audit
pair ships in P1.2."""

from __future__ import annotations


def render_template(ev: dict) -> str:
    lines: list[str] = []
    interpreted = ev["interpreted_question"]["restatement"]
    lines.append(f"Interpreted as: {interpreted}")
    lines.append("")

    if "refusal" in ev:
        r = ev["refusal"]
        lines.append(f"REFUSED ({r['kind']}): {r['reason']}")
        for alt in r["alternatives"]:
            lines.append(f"  alternative: {alt}")
        return "\n".join(lines)

    if ev.get("verification_status") == "CONFLICTING" and "calculation" not in ev:
        lines.append("CONFLICT: two filings print different values; both shown below. "
                     "No computation was performed.")
    else:
        result = ev["calculation"]["result"]
        lines.append(f"Answer: {result['formatted']}   (exact: {result['value']} {result['unit']})")

    lines.append("")
    lines.append("Facts used:")
    for i, f in enumerate(ev["facts_used"], 1):
        p = f["period"]
        span = p["end"] if p["start"] is None else f"{p['start']} -> {p['end']}"
        corroboration = (
            f" (+{f['corroborating_rows']} corroborating row(s))"
            if f.get("corroborating_rows")
            else ""
        )
        lines.append(
            f"  [{i}] {f['company']} {f['concept'] or f['raw_label']}: printed "
            f"\"{f['raw_label']}\" = {f['value_raw']} -> {f['value_normalized']} {f['unit']}"
        )
        lines.append(
            f"      {f['filing']['form_type']} {f['filing']['accession_no']} "
            f"filed {f['filing']['filing_date']}, {f['statement']} p.{f['page']}, "
            f"{p['fiscal_label']} ({span}, {p['duration_type']}) "
            f"[{f['verification_status']}]{corroboration}"
        )

    if "calculation" in ev:
        lines.append("")
        lines.append("Calculation:")
        for s in ev["calculation"]["steps"]:
            lines.append(f"  {s['n']}. {s['describe']} = {s['value']}")
        if "table" in ev["calculation"]:
            lines.append("  ranked by |delta|:")
            for row in ev["calculation"]["table"]:
                growth = f", growth {row['growth']}" if row["growth"] else ""
                lines.append(
                    f"    {row['concept']} (\"{row['raw_label']}\"): "
                    f"{row['older']} -> {row['newer']}, delta {row['delta']}{growth}"
                )

    if ev.get("caveats"):
        lines.append("")
        lines.append("Caveats:")
        for c in ev["caveats"]:
            lines.append(f"  - {c['code']}: {c['text']}")
    return "\n".join(lines)
