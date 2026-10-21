"use client";

import { type DragEvent, type FormEvent, useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import { useProgressEvents } from "../../events";
import {
  type Card,
  type Filter,
  SOURCE_NAMES,
  STAGES,
  STAGE_NAMES,
  type Source,
  type Stage,
  ask,
  bulkTargets,
  moveError,
  targets,
  visible,
} from "../pipeline";

/** A move waiting for its reason: optional to reject, required to reopen. */
type Asking = { card: Card; to: Stage; kind: "reject" | "reopen" };

const total = (value: number | null) =>
  value === null ? "—" : value.toLocaleString("vi-VN", { maximumFractionDigits: 2 });

/** The Job's Applications on a Kanban Board, one column per Stage (FR-A3.2). Cards move by
 * drag-and-drop, by their own Stage menu, or several at once; a Reviewer only reads. */
export function Pipeline({
  jobId,
  editable,
  onApplications,
}: {
  jobId: string;
  /** Whether cards may move: not for a Reviewer, nor on an archived Job. */
  editable: boolean;
  /** Told how many Applications the Job has, after each load. */
  onApplications: (count: number) => void;
}) {
  const [cards, setCards] = useState<Card[] | null>(null);
  // Bumped to reload the board.
  const [version, setVersion] = useState(0);
  const [filter, setFilter] = useState<Filter>({ source: "", min: "", max: "" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkTo, setBulkTo] = useState<Stage | "">("");
  const [asking, setAsking] = useState<Asking | null>(null);
  const [over, setOver] = useState<Stage | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch(`/api/jobs/${jobId}/applications`).then(async (r) => {
      if (!r.ok) return;
      const list: Card[] = await r.json();
      setCards(list);
      onApplications(list.length);
    });
  }, [jobId, version, onApplications]);
  const reload = () => setVersion((v) => v + 1);
  const reloadForJob = (data: unknown) => {
    if ((data as { job_id: string }).job_id === jobId) reload();
  };
  // A parsed CV adds a card; a scored one changes its Total.
  useProgressEvents("upload.item", reloadForJob, reload);
  useProgressEvents("scoring.result", reloadForJob);

  /** Send a move; every outcome reloads the board, which a refused one also needs (409). */
  async function send(path: string, method: string, body: object): Promise<boolean> {
    setPending(true);
    const response = await apiFetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setPending(false);
    if (response.status === 401) {
      window.location.replace("/login");
      return false;
    }
    setError(response.ok ? null : moveError(response.status));
    reload();
    return response.ok;
  }

  function moveOne(card: Card, to: Stage, reason?: string, kind?: Asking["kind"]) {
    return send(`/api/applications/${card.id}/stage`, "PATCH", {
      to_stage: to,
      version: card.version,
      ...(kind === "reopen" && { note: reason }),
      ...(kind === "reject" && reason && { rejected_reason: reason }),
    });
  }

  /** Move card to to, first asking for the reason the move needs. */
  function request(card: Card, to: Stage) {
    if (card.stage === to) return;
    if (!targets(card.stage).includes(to)) {
      setError(`Không chuyển được từ ${STAGE_NAMES[card.stage]} sang ${STAGE_NAMES[to]}.`);
      return;
    }
    const kind = ask(card.stage, to);
    if (kind) setAsking({ card, to, kind });
    else moveOne(card, to);
  }

  async function moveSelected() {
    if (!cards || bulkTo === "") return;
    const chosen = cards.filter((c) => selected.has(c.id));
    const moved = await send(`/api/jobs/${jobId}/applications/stage`, "POST", {
      applications: chosen.map((c) => ({ id: c.id, version: c.version })),
      to_stage: bulkTo,
    });
    if (moved) {
      setSelected(new Set());
      setBulkTo("");
    }
  }

  function onDrop(event: DragEvent<HTMLElement>, to: Stage) {
    event.preventDefault();
    setOver(null);
    const card = cards?.find((c) => c.id === event.dataTransfer.getData("text/plain"));
    if (card) request(card, to);
  }

  if (!cards) {
    return (
      <div aria-busy="true" aria-label="Đang tải Kanban" className="flex gap-3 overflow-hidden">
        {STAGES.slice(0, 4).map((stage) => (
          <div
            key={stage}
            className="h-48 w-56 shrink-0 animate-pulse rounded-lg bg-hairline-cloud"
          />
        ))}
      </div>
    );
  }
  const shown = visible(cards, filter);
  const chosen = cards.filter((c) => selected.has(c.id));
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <section className="flex flex-col gap-4 border-t border-hairline-cloud pt-6">
      <h2 className="heading-display text-2xl font-semibold">Pipeline ({cards.length})</h2>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm font-medium">
          Nguồn
          <select
            value={filter.source}
            onChange={(e) => setFilter({ ...filter, source: e.target.value as Source | "" })}
            className="text-input"
          >
            <option value="">Tất cả</option>
            {Object.entries(SOURCE_NAMES).map(([source, name]) => (
              <option key={source} value={source}>
                {name}
              </option>
            ))}
          </select>
        </label>
        {(["min", "max"] as const).map((bound) => (
          <label key={bound} className="flex w-28 flex-col gap-1 text-sm font-medium">
            {bound === "min" ? "Total từ" : "Total đến"}
            <input
              type="number"
              min={0}
              max={100}
              value={filter[bound]}
              onChange={(e) => setFilter({ ...filter, [bound]: e.target.value })}
              className="text-input"
            />
          </label>
        ))}
      </div>

      {editable && chosen.length > 0 && (
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-sm font-medium">
            Đổi stage {chosen.length} thẻ đã chọn sang
            <select
              value={bulkTo}
              onChange={(e) => setBulkTo(e.target.value as Stage | "")}
              className="text-input"
            >
              <option value="">Chọn stage</option>
              {bulkTargets(chosen).map((stage) => (
                <option key={stage} value={stage}>
                  {STAGE_NAMES[stage]}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            disabled={pending || bulkTo === ""}
            onClick={moveSelected}
            className="button-outline"
          >
            Đổi stage
          </button>
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="font-medium underline"
          >
            Bỏ chọn
          </button>
        </div>
      )}
      {editable && chosen.length > 0 && bulkTargets(chosen).length === 0 && (
        <p className="text-sm">
          Không có stage chung cho các thẻ đã chọn. Thẻ Hired không chuyển được; thẻ Rejected mở lại
          từng thẻ một vì cần lý do.
        </p>
      )}
      {error && <p role="alert">{error}</p>}

      <div className="flex gap-3 overflow-x-auto pb-2">
        {STAGES.map((stage) => {
          const column = shown.filter((c) => c.stage === stage);
          return (
            <section
              key={stage}
              aria-label={STAGE_NAMES[stage]}
              onDragOver={
                editable
                  ? (e) => {
                      e.preventDefault();
                      setOver(stage);
                    }
                  : undefined
              }
              onDragLeave={() => setOver(null)}
              onDrop={editable ? (e) => onDrop(e, stage) : undefined}
              className={`flex w-56 shrink-0 flex-col gap-2 rounded-lg border p-3 ${
                over === stage
                  ? "border-ink-deep bg-surface-press-light"
                  : "border-hairline-cloud bg-surface-canvas-light"
              }`}
            >
              <h3 className="text-sm font-semibold tracking-[0.2px] uppercase">
                {STAGE_NAMES[stage]} ({column.length})
              </h3>
              {column.map((card) => (
                <KanbanCard
                  key={`${card.id}-${card.version}`}
                  card={card}
                  editable={editable}
                  selected={selected.has(card.id)}
                  onSelect={() => toggle(card.id)}
                  onMove={(to) => request(card, to)}
                  asking={asking?.card.id === card.id ? asking : null}
                  onAnswer={async (reason) => {
                    if (!asking) return;
                    setAsking(null);
                    await moveOne(asking.card, asking.to, reason, asking.kind);
                  }}
                  onCancel={() => setAsking(null)}
                />
              ))}
            </section>
          );
        })}
      </div>
    </section>
  );
}

function KanbanCard({
  card,
  editable,
  selected,
  onSelect,
  onMove,
  asking,
  onAnswer,
  onCancel,
}: {
  card: Card;
  editable: boolean;
  selected: boolean;
  onSelect: () => void;
  onMove: (to: Stage) => void;
  asking: Asking | null;
  onAnswer: (reason: string) => void;
  onCancel: () => void;
}) {
  const name = card.full_name ?? "Chưa rõ tên";
  const moves = targets(card.stage);
  return (
    <article
      draggable={editable}
      onDragStart={(e) => e.dataTransfer.setData("text/plain", card.id)}
      className={`flex flex-col gap-2 rounded-md border bg-surface-canvas-light p-2 text-sm ${
        selected ? "border-ink-deep" : "border-hairline-cloud"
      } ${editable ? "cursor-grab" : ""}`}
    >
      <div className="flex items-start gap-2">
        {editable && (
          <input
            type="checkbox"
            aria-label={`Chọn ${name}`}
            checked={selected}
            onChange={onSelect}
            className="mt-1"
          />
        )}
        <span className="flex min-w-0 flex-col">
          <span className="font-medium">{name}</span>
          {card.email && <span className="truncate">{card.email}</span>}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span>
          Total <span className="font-mono">{total(card.total_score)}</span>
        </span>
        <Badge>{SOURCE_NAMES[card.source]}</Badge>
      </div>
      {card.rejected_reason && <p className="text-sm">Lý do: {card.rejected_reason}</p>}
      {editable && moves.length > 0 && !asking && (
        <select
          aria-label={`Chuyển ${name} sang stage`}
          value=""
          onChange={(e) => onMove(e.target.value as Stage)}
          className="text-input text-sm"
        >
          <option value="">{card.stage === "REJECTED" ? "Mở lại sang…" : "Chuyển sang…"}</option>
          {moves.map((stage) => (
            <option key={stage} value={stage}>
              {STAGE_NAMES[stage]}
            </option>
          ))}
        </select>
      )}
      {asking && <ReasonForm asking={asking} onAnswer={onAnswer} onCancel={onCancel} />}
    </article>
  );
}

/** The reason a move asks for, inline on its card. */
function ReasonForm({
  asking,
  onAnswer,
  onCancel,
}: {
  asking: Asking;
  onAnswer: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const reopen = asking.kind === "reopen";
  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onAnswer(reason.trim());
  }
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label className="flex flex-col gap-1 font-medium">
        {reopen ? `Lý do mở lại sang ${STAGE_NAMES[asking.to]}` : "Lý do từ chối (không bắt buộc)"}
        <textarea
          required={reopen}
          maxLength={2000}
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="text-input text-sm"
        />
      </label>
      <div className="flex gap-3">
        <button
          type="submit"
          disabled={reopen && reason.trim() === ""}
          className="button-outline px-3 py-2"
        >
          {reopen ? "Mở lại" : "Từ chối"}
        </button>
        <button type="button" onClick={onCancel} className="font-medium underline">
          Hủy
        </button>
      </div>
    </form>
  );
}
