import { html } from "../core/dom.js";
import { PHASE_LABEL, PHASE_ORDER, normalizePhase } from "../core/format.js";

export function ProgressBar({ percent = 0, phase = "", label = "", extra = "" } = {}) {
  const pct = Math.max(0, Math.min(100, Number(percent) || 0));
  const current = normalizePhase(phase);
  const idx = PHASE_ORDER.indexOf(current);
  return html`<div class="progress">
    <div class="progress-bar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" role="progressbar"><i style="width:${pct}%"></i></div>
    <div class="progress-meta"><strong>${pct}%</strong><span>${label}</span><span>${extra}</span></div>
    <ol class="phases" aria-label="下载阶段">
      ${PHASE_ORDER.map((key, i) => {
        const cls = key === current ? "is-on" : idx > 0 && i < idx ? "is-done" : "";
        return html`<li class="${cls}" data-phase="${key}">${PHASE_LABEL[key]}</li>`;
      })}
    </ol>
  </div>`;
}

export function progressExtra(rec = {}) {
  const bits = [];
  if (rec.items) bits.push(`${rec.item || 1}/${rec.items}`);
  if (rec.speed) bits.push(rec.speed);
  if (rec.eta) bits.push("剩余 " + rec.eta);
  if (rec.detail) bits.push(rec.detail);
  return bits.join("  ·  ");
}
