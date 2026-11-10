"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { apiFetch } from "../../auth";
import { Badge } from "../../badge";
import {
  type FacebookCandidatePage,
  type FacebookConnection,
  getChannelErrorMessage,
} from "./channels";

// Secondary actions read as link-on-light: one filled button per page (DESIGN.md).
const LINK_BUTTON = "font-medium underline";

export default function ChannelsPage() {
  const t = useTranslations("channels");
  const locale = useLocale();

  const [connection, setConnection] = useState<FacebookConnection | null>(null);
  const [candidates, setCandidates] = useState<FacebookCandidatePage[] | null>(null);
  const [selectedPageId, setSelectedPageId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    const params = new URLSearchParams(window.location.search);
    return getChannelErrorMessage(t, params.get("error"));
  });
  const [selectingPage, setSelectingPage] = useState(() => {
    if (typeof window === "undefined") return false;
    const params = new URLSearchParams(window.location.search);
    return params.get("select_page") === "1";
  });
  const [version, setVersion] = useState(0);

  const reload = () => setVersion((v) => v + 1);
  const formatDateTime = (iso: string) => new Date(iso).toLocaleString(locale);

  useEffect(() => {
    let active = true;
    apiFetch("/api/auth/me").then(async (response) => {
      if (!active) return;
      if (response.status === 401) {
        window.location.replace("/login");
        return;
      }
      if (response.ok) {
        const me = await response.json();
        if (me.role !== "COMPANY_ADMIN") {
          setForbidden(true);
        }
      } else {
        setForbidden(true);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    apiFetch("/api/channels/facebook").then(async (response) => {
      if (!active) return;
      if (response.status === 401) {
        window.location.replace("/login");
        return;
      }
      if (response.status === 403) {
        setForbidden(true);
        setLoading(false);
        return;
      }
      if (response.ok) {
        const data = await response.json();
        setConnection(data);
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [version]);

  useEffect(() => {
    if (!selectingPage) return;
    let active = true;
    apiFetch("/api/channels/facebook/pages").then(async (response) => {
      if (!active) return;
      if (response.ok) {
        const data = await response.json();
        setCandidates(data);
        if (data.length > 0) {
          setSelectedPageId(data[0].id);
        }
      } else {
        setErrorMsg(t("invalidSelection"));
        setSelectingPage(false);
      }
    });
    return () => {
      active = false;
    };
  }, [selectingPage, t]);

  async function startConnect() {
    setConnecting(true);
    setErrorMsg(null);
    const res = await apiFetch("/api/channels/facebook/auth-url");
    if (res.status === 401) {
      window.location.replace("/login");
      return;
    }
    if (res.status === 403) {
      setForbidden(true);
      setConnecting(false);
      return;
    }
    if (res.status === 503) {
      setErrorMsg(t("configMissing"));
      setConnecting(false);
      return;
    }
    if (res.ok) {
      const data = await res.json();
      window.location.href = data.auth_url;
    } else {
      setErrorMsg(t("oauthFailed"));
      setConnecting(false);
    }
  }

  async function handleSelectSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedPageId) return;
    const res = await apiFetch("/api/channels/facebook/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page_id: selectedPageId }),
    });
    if (res.ok) {
      window.history.replaceState({}, "", "/settings/channels");
      setSelectingPage(false);
      reload();
    } else {
      setErrorMsg(t("invalidSelection"));
    }
  }

  async function disconnect() {
    if (!window.confirm(t("confirmDisconnect"))) return;
    const res = await apiFetch("/api/channels/facebook", { method: "DELETE" });
    if (res.status === 403) {
      setForbidden(true);
      return;
    }
    if (res.ok) {
      setConnection(null);
      reload();
    } else {
      setErrorMsg(t("oauthFailed"));
    }
  }

  if (forbidden) {
    return (
      <main className="mx-auto max-w-3xl p-6">
        <p role="alert" className="border-l-4 border-accent-pink pl-3 text-sm">
          {t("forbidden")}
        </p>
      </main>
    );
  }

  return (
    <main className="flex-1">
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        {/* Navigation tabs */}
        <div className="flex gap-4 border-b border-hairline-cloud pb-2 text-sm">
          <Link href="/settings/members" className="text-accent-violet-mid hover:text-ink-deep">
            {t("navMembers")}
          </Link>
          <span className="-mb-2 border-b-2 border-primary pb-2 font-semibold text-ink-deep">
            {t("navChannels")}
          </span>
        </div>

        <div className="flex flex-col gap-1">
          <h1 className="heading-display text-3xl font-semibold">{t("title")}</h1>
          <p className="text-sm text-accent-violet-mid">{t("description")}</p>
        </div>

        {errorMsg && (
          <div
            role="alert"
            className="border-l-4 border-accent-pink bg-surface-canvas-light py-1 pl-3 text-sm"
          >
            <p className="font-medium text-ink-deep">{errorMsg}</p>
          </div>
        )}

        {loading ? (
          <div aria-busy="true" aria-label={t("loading")} className="flex flex-col gap-3">
            <div className="h-8 animate-pulse rounded-md bg-hairline-cloud" />
            <div className="h-40 animate-pulse rounded-md bg-hairline-cloud" />
          </div>
        ) : selectingPage ? (
          /* Multi-page selection dialog / form */
          <div className="flex flex-col gap-4 rounded-lg border border-hairline-cloud bg-surface-canvas-light p-6">
            <h2 className="text-xl font-semibold">{t("selectPageTitle")}</h2>
            <p className="text-sm text-ink-deep">{t("selectPageDesc")}</p>
            {!candidates ? (
              <p className="text-sm text-accent-violet-mid">{t("loading")}</p>
            ) : (
              <form onSubmit={handleSelectSubmit} className="flex flex-col gap-4">
                <select
                  className="max-w-md text-input"
                  value={selectedPageId}
                  onChange={(e) => setSelectedPageId(e.target.value)}
                >
                  {candidates.map((page) => (
                    <option key={page.id} value={page.id}>
                      {page.name} ({page.id})
                    </option>
                  ))}
                </select>
                <div className="flex items-center gap-4 pt-2">
                  <button type="submit" className="button-primary">
                    {t("selectPageSubmit")}
                  </button>
                  <button
                    type="button"
                    className={LINK_BUTTON}
                    onClick={() => {
                      window.history.replaceState({}, "", "/settings/channels");
                      setSelectingPage(false);
                    }}
                  >
                    {t("selectPageCancel")}
                  </button>
                </div>
              </form>
            )}
          </div>
        ) : connection ? (
          /* Connected page card */
          <div className="flex flex-col gap-4 rounded-lg border border-hairline-cloud bg-surface-canvas-light p-6">
            <div className="flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-xl font-semibold">
                {connection.name}
                <Badge>{t("badge")}</Badge>
              </h2>
              <div className="flex items-center gap-4">
                <button
                  type="button"
                  className={LINK_BUTTON}
                  onClick={startConnect}
                  disabled={connecting}
                >
                  {t("reconnect")}
                </button>
                <button type="button" className={LINK_BUTTON} onClick={disconnect}>
                  {t("disconnect")}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 pt-2 text-sm text-ink-deep md:grid-cols-2">
              <div>
                <span className="block text-accent-violet-mid">{t("pageId")}</span>
                <span className="font-mono text-xs">{connection.external_id}</span>
              </div>
              <div>
                <span className="block text-accent-violet-mid">{t("connectedBy")}</span>
                <span>{connection.connected_by_name}</span>
              </div>
              <div>
                <span className="block text-accent-violet-mid">{t("connectedAt")}</span>
                <span>{formatDateTime(connection.connected_at)}</span>
              </div>
            </div>
          </div>
        ) : (
          /* Empty / Not connected state */
          <div className="flex flex-col items-center gap-4 rounded-lg border border-hairline-cloud bg-surface-canvas-light p-8 text-center">
            <div className="flex max-w-md flex-col gap-2">
              <h2 className="text-xl font-semibold">{t("notConnectedTitle")}</h2>
              <p className="text-sm text-accent-violet-mid">{t("notConnectedDesc")}</p>
            </div>
            <button
              type="button"
              className="mt-2 button-primary"
              onClick={startConnect}
              disabled={connecting}
            >
              {connecting ? t("loading") : t("connect")}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
