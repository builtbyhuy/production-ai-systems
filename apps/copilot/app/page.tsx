"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  Approval,
  Citation,
  CopilotMessage,
  DocumentVersion,
  Health,
  Principal,
} from "@/lib/types";

type IconName =
  | "spark"
  | "chat"
  | "file"
  | "check"
  | "upload"
  | "arrow"
  | "plus"
  | "close"
  | "clock"
  | "shield"
  | "logout"
  | "link";
function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, React.ReactNode> = {
    spark: (
      <>
        <path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z" />
        <path d="m20 2 .6 1.4L22 4l-1.4.6L20 6l-.6-1.4L18 4l1.4-.6L20 2Z" />
      </>
    ),
    chat: <path d="M4 4h16v12H9l-5 4V4Z" />,
    file: (
      <>
        <path d="M6 3h8l4 4v14H6V3Z" />
        <path d="M14 3v5h4M9 12h6M9 16h6" />
      </>
    ),
    check: (
      <>
        <path d="m5 12 4 4L19 6" />
        <path d="M20 12v8H4V4h10" />
      </>
    ),
    upload: (
      <>
        <path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5" />
      </>
    ),
    arrow: (
      <>
        <path d="M5 12h14m-6-6 6 6-6 6" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    close: <path d="m6 6 12 12M6 18 18 6" />,
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    shield: (
      <>
        <path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Z" />
        <path d="m8 12 3 3 5-6" />
      </>
    ),
    logout: (
      <>
        <path d="M10 4H4v16h6M9 12h12m-4-4 4 4-4 4" />
      </>
    ),
    link: (
      <>
        <path d="M14 4h6v6m0-6-9 9" />
        <path d="M10 4H4v16h16v-6" />
      </>
    ),
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}

const starterQuestions = [
  {
    title: "Find the operating limit",
    detail: "What is the safe operating pressure?",
    icon: "file" as IconName,
  },
  {
    title: "Check an escalation rule",
    detail: "When should an incident be escalated?",
    icon: "shield" as IconName,
  },
  {
    title: "Verify a maintenance step",
    detail: "What is the maintenance interval?",
    icon: "clock" as IconName,
  },
];
const textOf = (message: CopilotMessage) =>
  message.parts
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("");

async function checkedFetch(url: RequestInfo | URL, options: RequestInit = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `Request failed (${response.status}). Please retry.`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* Safe fallback for non-JSON errors. */
    }
    throw new Error(detail.slice(0, 400));
  }
  return response;
}

export default function Copilot() {
  const [health, setHealth] = useState<Health | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [token, setToken] = useState("");
  const tokenRef = useRef("");
  const [credential, setCredential] = useState("");
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [tab, setTab] = useState<"chat" | "documents" | "approvals">("chat");
  const [documents, setDocuments] = useState<DocumentVersion[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadNotice, setUploadNotice] = useState("");
  const [input, setInput] = useState("");
  const [stopped, setStopped] = useState(false);
  const [restoredPending, setRestoredPending] = useState(false);
  const [firstDisplay, setFirstDisplay] = useState<number | null>(null);
  const [decisionPending, setDecisionPending] = useState<string | null>(null);
  const [source, setSource] = useState<Citation | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [pdfUrl, setPdfUrl] = useState("");
  const [sourceRetry, setSourceRetry] = useState(0);
  const [proposalText, setProposalText] = useState("");
  const [proposalReviewer, setProposalReviewer] = useState("");
  const [proposalPending, setProposalPending] = useState(false);
  const [proposalNotice, setProposalNotice] = useState("");
  const [capability, setCapability] = useState<{
    enabled: boolean;
    version: number;
    emergency_disabled?: boolean;
  } | null>(null);
  const [capabilityPending, setCapabilityPending] = useState(false);
  const conversationRef = useRef("workspace");
  const proposalRef = useRef<{ fingerprint: string; key: string } | null>(null);
  const sendStarted = useRef<number | null>(null);
  const streamStarted = useRef(false);
  const previousMessageCount = useRef(0);
  const uploadRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const authHeaders = useCallback(
    () => ({ Authorization: `Bearer ${tokenRef.current}` }),
    [],
  );
  const transport = useMemo(
    () =>
      new DefaultChatTransport<CopilotMessage>({
        api: "/api/chat/stream",
        headers: authHeaders,
        fetch: checkedFetch,
        prepareSendMessagesRequest: ({ messages }) => {
          const last = [...messages]
            .reverse()
            .find((message) => message.role === "user");
          if (!last) throw new Error("Add a question before sending.");
          return {
            body: {
              question: textOf(last),
              message_id: last.id,
              conversation_id: conversationRef.current,
            },
          };
        },
      }),
    [authHeaders],
  );

  const {
    messages,
    setMessages,
    sendMessage,
    regenerate,
    stop,
    status,
    error,
    clearError,
  } = useChat<CopilotMessage>({
    id: "operations-copilot",
    transport,
    generateId: () => crypto.randomUUID(),
    onData: (part) => {
      if (part.type === "data-status") streamStarted.current = true;
    },
  });
  const busy = status === "submitted" || status === "streaming";
  const responseError =
    error &&
    (/validation|JSON|parse|unexpected/i.test(error.message)
      ? "The response was malformed and could not be displayed. Retry this message."
      : /Failed to fetch|NetworkError|network/i.test(error.message)
        ? "The connection was interrupted. Retry this message to recover the saved result."
        : error.message.slice(0, 400));
  const activeDocuments = documents.filter((document) => document.active);
  const pendingApprovals = approvals.filter(
    (approval) => approval.status === "pending",
  );

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await (await checkedFetch("/api/health")).json());
      setConnectionError("");
    } catch {
      setConnectionError(
        "The workspace service is unreachable. Start the API, then retry.",
      );
    }
  }, []);
  useEffect(() => {
    void refreshHealth();
    conversationRef.current =
      sessionStorage.getItem("pais-conversation") || "workspace";
  }, [refreshHealth]);

  const refreshWorkspace = useCallback(async () => {
    setLoading(true);
    setWorkspaceError("");
    const outcomes = await Promise.allSettled([
      checkedFetch("/api/documents", { headers: authHeaders() }).then((r) =>
        r.json(),
      ),
      checkedFetch("/api/approvals", { headers: authHeaders() }).then((r) =>
        r.json(),
      ),
    ]);
    if (outcomes[0].status === "fulfilled")
      setDocuments(outcomes[0].value.documents);
    if (outcomes[1].status === "fulfilled")
      setApprovals(outcomes[1].value.approvals);
    const failure = outcomes.find((outcome) => outcome.status === "rejected");
    if (failure?.status === "rejected")
      setWorkspaceError(
        failure.reason?.message || "Some workspace data could not load.",
      );
    try {
      const data = await (
        await checkedFetch("/api/capabilities", { headers: authHeaders() })
      ).json();
      setCapability(
        data.capabilities.find(
          (item: { capability: string }) => item.capability === "agent.execute",
        ) || { enabled: false, version: 0 },
      );
    } catch {
      setCapability(null); /* Non-admin users cannot inspect the controls. */
    }
    setLoading(false);
  }, [authHeaders]);

  async function restoreConversation() {
    const history = await (
      await checkedFetch(
        `/api/messages?conversation_id=${encodeURIComponent(conversationRef.current)}`,
        { headers: authHeaders() },
      )
    ).json();
    setMessages(history.messages);
    setRestoredPending(history.pending.length > 0);
  }

  async function connect(value: string) {
    if (!value.trim() || connecting) return;
    setConnecting(true);
    setConnectionError("");
    tokenRef.current = value.trim();
    try {
      const current = (await (
        await checkedFetch("/api/me", { headers: authHeaders() })
      ).json()) as Principal;
      await refreshWorkspace();
      await restoreConversation();
      setPrincipal(current);
      setToken(value.trim());
      setCredential("");
      setProposalReviewer(current.subject);
    } catch (failure) {
      tokenRef.current = "";
      setToken("");
      setPrincipal(null);
      setConnectionError(
        failure instanceof Error ? failure.message : "Connection failed.",
      );
    } finally {
      setConnecting(false);
    }
  }

  useEffect(() => {
    if (
      !streamStarted.current ||
      sendStarted.current === null ||
      firstDisplay !== null
    )
      return;
    const last = messages.at(-1);
    if (
      messages.length > previousMessageCount.current &&
      last?.role === "assistant" &&
      textOf(last)
    ) {
      setFirstDisplay(Math.round(performance.now() - sendStarted.current));
    }
  }, [messages, busy, firstDisplay]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [messages, status]);

  useEffect(() => {
    if (!source) return;
    const controller = new AbortController();
    let objectUrl = "";
    setSourceLoading(true);
    setSourceError("");
    setSourceText("");
    setPdfUrl("");
    dialogRef.current?.showModal();
    const base = `/api/documents/${encodeURIComponent(source.document_id)}/versions/${encodeURIComponent(source.version_id)}`;
    Promise.all([
      checkedFetch(`${base}/pages/${source.page_number}`, {
        headers: authHeaders(),
        signal: controller.signal,
      }).then((r) => r.json()),
      checkedFetch(`${base}/pdf`, {
        headers: authHeaders(),
        signal: controller.signal,
      }).then((r) => r.blob()),
    ])
      .then(([page, blob]) => {
        if (controller.signal.aborted) return;
        setSourceText(page.text);
        objectUrl = URL.createObjectURL(blob);
        setPdfUrl(objectUrl);
      })
      .catch((failure) => {
        if (!controller.signal.aborted)
          setSourceError(failure.message || "This source could not load.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setSourceLoading(false);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [source, sourceRetry, authHeaders]);

  async function upload(file?: File) {
    if (!file) return;
    setUploadNotice("");
    setWorkspaceError("");
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setWorkspaceError("Choose a PDF document.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setWorkspaceError("PDFs must be no larger than 10 MiB.");
      return;
    }
    setUploading(true);
    const body = new FormData();
    body.append("file", file);
    try {
      await checkedFetch("/api/documents", {
        method: "POST",
        headers: authHeaders(),
        body,
      });
      setUploadNotice(`${file.name} is ready to ask about.`);
      await refreshWorkspace();
    } catch (failure) {
      setWorkspaceError(
        failure instanceof Error
          ? failure.message
          : "Upload failed. Try the file again.",
      );
    } finally {
      setUploading(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  }

  function beginRequest() {
    clearError();
    setStopped(false);
    setRestoredPending(false);
    setFirstDisplay(null);
    previousMessageCount.current = messages.length;
    sendStarted.current = performance.now();
    streamStarted.current = false;
  }
  async function ask(question = input) {
    if (!question.trim() || busy) return;
    beginRequest();
    setInput("");
    setTab("chat");
    await sendMessage({ text: question.trim() });
  }
  async function retry() {
    if (busy) return;
    beginRequest();
    previousMessageCount.current = Math.max(0, messages.length - 2);
    await regenerate();
  }
  function newConversation() {
    if (busy) return;
    conversationRef.current = crypto.randomUUID();
    sessionStorage.setItem("pais-conversation", conversationRef.current);
    setMessages([]);
    clearError();
    setStopped(false);
    setRestoredPending(false);
    setFirstDisplay(null);
    sendStarted.current = null;
    streamStarted.current = false;
    setInput("");
    setTab("chat");
    composerRef.current?.focus();
  }
  async function decision(
    approval: Approval,
    value: "approve" | "reject" | "cancel",
  ) {
    if (decisionPending) return;
    setDecisionPending(approval.approval_id);
    setWorkspaceError("");
    try {
      await checkedFetch(
        `/api/approvals/${encodeURIComponent(approval.approval_id)}/decision`,
        {
          method: "POST",
          headers: { ...authHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({
            decision: value,
            expected_action_hash: approval.action_hash,
            context_version: approval.action.context_version,
          }),
        },
      );
      await refreshWorkspace();
    } catch (failure) {
      setWorkspaceError(
        failure instanceof Error
          ? failure.message
          : "The decision was not saved.",
      );
    } finally {
      setDecisionPending(null);
    }
  }
  async function propose() {
    if (!proposalText.trim() || !proposalReviewer.trim() || proposalPending)
      return;
    setProposalPending(true);
    setProposalNotice("");
    setWorkspaceError("");
    const proposalFingerprint = JSON.stringify({
      text: proposalText.trim(),
      reviewer: proposalReviewer.trim(),
      context: activeDocuments[0]?.version_id || "workspace-v1",
    });
    if (proposalRef.current?.fingerprint !== proposalFingerprint) {
      proposalRef.current = {
        fingerprint: proposalFingerprint,
        key: crypto.randomUUID(),
      };
    }
    try {
      await checkedFetch("/api/approvals", {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewer: proposalReviewer.trim(),
          ttl_seconds: 900,
          action: {
            tool: "record_note",
            arguments: {
              text: proposalText.trim(),
              context_id: activeDocuments[0]?.document_id || "workspace",
            },
            context_version: activeDocuments[0]?.version_id || "workspace-v1",
            idempotency_key: proposalRef.current.key,
          },
        }),
      });
      proposalRef.current = null;
      setProposalText("");
      setProposalNotice("Draft submitted for review.");
      await refreshWorkspace();
    } catch (failure) {
      setWorkspaceError(
        failure instanceof Error
          ? failure.message
          : "The draft could not be submitted.",
      );
    } finally {
      setProposalPending(false);
    }
  }
  async function toggleExecution() {
    if (!capability || capabilityPending) return;
    setCapabilityPending(true);
    setWorkspaceError("");
    try {
      await checkedFetch("/api/capabilities/agent.execute", {
        method: "PUT",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: !capability.enabled,
          expected_version: capability.version,
          reason:
            "Explicit workspace administrator decision from approval controls",
        }),
      });
      await refreshWorkspace();
    } catch (failure) {
      setWorkspaceError(
        failure instanceof Error
          ? failure.message
          : "Execution control could not be updated.",
      );
    } finally {
      setCapabilityPending(false);
    }
  }
  function closeSource() {
    dialogRef.current?.close();
    setSource(null);
  }
  function keepSourceFocus(event: React.KeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") return;
    const items = [
      ...event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], [tabindex="0"]',
      ),
    ].filter((element) => element.getClientRects().length > 0);
    const first = items[0],
      last = items.at(-1);
    if (!first || !last) return;
    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    }
  }
  const documentName = (id: string) =>
    documents.find((document) => document.document_id === id)?.filename ||
    "Source document";
  const openDocument = (document: DocumentVersion) =>
    setSource({
      document_id: document.document_id,
      version_id: document.version_id,
      chunk_id: "",
      page_number: 1,
      start: 0,
      end: 0,
      quote: "",
      claim: "",
    });

  if (!token || !principal)
    return (
      <main className="connect-layout">
        <section className="connect-story">
          <div className="brand">
            <span className="brand-mark">
              <Icon name="spark" />
            </span>{" "}
            OPERATIONS<span className="brand-light">COPILOT</span>
          </div>
          <div className="connect-copy">
            <span className="eyebrow">A WORKSPACE BUILT ON EVIDENCE</span>
            <h1>
              Know where your
              <br />
              answer comes from.
            </h1>
            <p>
              Bring your operating documents. Ask a question. Inspect the source
              before taking the next step.
            </p>
            <div className="connect-capabilities">
              <span>
                <Icon name="file" /> Versioned documents
              </span>
              <span>
                <Icon name="link" /> Page-level sources
              </span>
              <span>
                <Icon name="shield" /> Human approvals
              </span>
            </div>
          </div>
          <p className="connect-foot">
            Technical operations, with a traceable path from question to action.
          </p>
        </section>
        <section className="connect-form">
          <div className="connect-card">
            <span className="eyebrow">WELCOME TO YOUR WORKSPACE</span>
            <h2>Connect to continue</h2>
            <p>Use the workspace credential supplied by your administrator.</p>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void connect(credential);
              }}
            >
              <label htmlFor="credential">Workspace credential</label>
              <input
                id="credential"
                type="password"
                autoComplete="off"
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
                placeholder="Enter your access token"
                required
              />
              <button
                className="primary wide"
                disabled={connecting || !credential.trim()}
              >
                {connecting ? "Connecting…" : "Connect workspace"}
                <Icon name="arrow" size={18} />
              </button>
            </form>
            {health?.fixture_auth && (
              <>
                <div className="divider">
                  <span>or explore the {health.profile} environment</span>
                </div>
                <button
                  className="secondary wide"
                  onClick={() => void connect("fixture-admin")}
                  disabled={connecting}
                >
                  {health.profile === "fixture"
                    ? "Open fixture workspace"
                    : "Open local test workspace"}
                  <Icon name="arrow" size={18} />
                </button>
                <p className="fine">
                  {health.profile === "fixture"
                    ? "Deterministic responses for integration testing. No claim of live model quality."
                    : "A test identity for this local model environment, explicitly enabled by its administrator."}
                </p>
              </>
            )}
            {connectionError && (
              <div role="alert" className="alert">
                <span>{connectionError}</span>
                <button
                  className="text-button"
                  onClick={() => void refreshHealth()}
                >
                  Retry connection
                </button>
              </div>
            )}
            {!health && !connectionError && (
              <p role="status" className="muted">
                Checking workspace availability…
              </p>
            )}
          </div>
        </section>
      </main>
    );

  return (
    <div className="shell">
      <a className="skip-link" href="#main-content">
        Skip to workspace
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="spark" />
          </span>
          <div>
            OPERATIONS<span className="brand-sub">COPILOT</span>
          </div>
        </div>
        <button
          className="new-conversation"
          onClick={newConversation}
          disabled={busy}
        >
          <Icon name="plus" size={18} /> New conversation
        </button>
        <span className="nav-label">WORKSPACE</span>
        <nav aria-label="Workspace navigation">
          <button
            className={tab === "chat" ? "nav-item active" : "nav-item"}
            aria-current={tab === "chat" ? "page" : undefined}
            onClick={() => setTab("chat")}
          >
            <Icon name="chat" /> Ask workspace
          </button>
          <button
            className={tab === "documents" ? "nav-item active" : "nav-item"}
            aria-current={tab === "documents" ? "page" : undefined}
            onClick={() => setTab("documents")}
          >
            <Icon name="file" /> Source library
            <span className="nav-count">{activeDocuments.length}</span>
          </button>
          <button
            className={tab === "approvals" ? "nav-item active" : "nav-item"}
            aria-current={tab === "approvals" ? "page" : undefined}
            onClick={() => setTab("approvals")}
          >
            <Icon name="check" /> Approvals
            {pendingApprovals.length > 0 && (
              <span className="nav-count amber">{pendingApprovals.length}</span>
            )}
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="identity-avatar">
            {principal.subject.slice(0, 1).toUpperCase()}
          </div>
          <div className="identity-info">
            <strong>{principal.subject}</strong>
            <span>{principal.tenant_id}</span>
          </div>
          <button
            className="icon-button"
            aria-label="Disconnect workspace"
            onClick={() => {
              void stop();
              tokenRef.current = "";
              setToken("");
              setPrincipal(null);
              setDocuments([]);
              setApprovals([]);
              setMessages([]);
            }}
          >
            <Icon name="logout" size={17} />
          </button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="breadcrumb">Workspace</span>
            <span className="slash">/</span>
            <strong>
              {tab === "chat"
                ? "Ask workspace"
                : tab === "documents"
                  ? "Source library"
                  : "Approvals"}
            </strong>
          </div>
          <span
            className={`profile-badge ${health?.profile === "fixture" ? "fixture" : ""}`}
          >
            <span />
            {health?.profile || "Unknown"} environment
          </span>
        </header>
        {health?.profile === "fixture" && (
          <div className="fixture-banner">
            <Icon name="shield" size={15} />
            <span>
              Fixture environment · Answers are deterministic test outputs.
            </span>
            <span className="fixture-banner-end">No live model evidence</span>
          </div>
        )}
        <div className="work-grid">
          <main id="main-content" className="main-panel" tabIndex={-1}>
            {workspaceError && (
              <div role="alert" className="alert workspace-alert">
                <span>{workspaceError}</span>
                <button
                  className="text-button"
                  onClick={() => void refreshWorkspace()}
                >
                  Retry
                </button>
              </div>
            )}
            {uploadNotice && (
              <div role="status" className="success-notice">
                <Icon name="check" size={16} />
                {uploadNotice}
              </div>
            )}
            {tab === "chat" && (
              <>
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">YOUR OPERATIONS, IN CONTEXT</span>
                    <h1>Evidence, before action.</h1>
                    <p>
                      Ask your documents. Follow the sources. Make a considered
                      decision.
                    </p>
                  </div>
                  <div className="small-status">
                    <span className="status-dot" />
                    {activeDocuments.length}{" "}
                    {activeDocuments.length === 1 ? "source" : "sources"} ready
                  </div>
                </div>
                <div
                  ref={transcriptRef}
                  className="transcript"
                  role="log"
                  aria-label="Conversation"
                  aria-live="polite"
                  aria-relevant="additions text"
                >
                  {messages.length === 0 && (
                    <div className="empty-chat">
                      <div className="illustration" aria-hidden="true">
                        <div className="evidence-sheet">
                          <span />
                          <span />
                          <span />
                          <div className="evidence-check">
                            <Icon name="check" size={22} />
                          </div>
                        </div>
                        <div className="small-spark">
                          <Icon name="spark" size={27} />
                        </div>
                      </div>
                      <h2>What would you like to verify?</h2>
                      <p>
                        {activeDocuments.length
                          ? "Your sources are ready. Ask a specific question to get an answer with page references."
                          : "Add an operating manual, policy, or runbook to start building your source library."}
                      </p>
                      {!activeDocuments.length && (
                        <button
                          className="primary"
                          onClick={() => uploadRef.current?.click()}
                          disabled={uploading}
                        >
                          <Icon name="upload" size={17} />
                          {uploading ? "Processing PDF…" : "Add your first PDF"}
                        </button>
                      )}
                      <div className="starter-grid">
                        {starterQuestions.map((starter) => (
                          <button
                            key={starter.title}
                            className="starter-card"
                            onClick={() => {
                              setInput(starter.detail);
                              composerRef.current?.focus();
                            }}
                          >
                            <Icon name={starter.icon} size={18} />
                            <strong>{starter.title}</strong>
                            <span>{starter.detail}</span>
                            <Icon name="arrow" size={16} />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {messages.map((message) => (
                    <article
                      key={message.id}
                      data-message-id={message.id}
                      data-role={message.role}
                      className={`message ${message.role}`}
                    >
                      <div className="message-avatar">
                        {message.role === "user" ? (
                          principal.subject.slice(0, 1).toUpperCase()
                        ) : (
                          <Icon name="spark" size={19} />
                        )}
                      </div>
                      <div className="message-body">
                        <div className="message-title">
                          <strong>
                            {message.role === "user"
                              ? "You"
                              : "Operations Copilot"}
                          </strong>
                          {message.role === "assistant" &&
                            message.metadata?.abstained && (
                              <span className="status-chip">
                                Insufficient evidence
                              </span>
                            )}
                          {message.role === "assistant" &&
                            message.metadata?.replayed && (
                              <span className="muted tiny">Restored</span>
                            )}
                        </div>
                        <div className="message-text">
                          {textOf(message) ||
                            (busy && message.role === "assistant" ? (
                              <span className="thinking">
                                <i />
                                <i />
                                <i />
                                <span>
                                  Checking sources and validating the answer…
                                </span>
                              </span>
                            ) : (
                              <span className="muted">
                                Response interrupted before text was received.
                              </span>
                            ))}
                        </div>
                        {message.parts
                          .filter((part) => part.type === "data-citations")
                          .map((part, index) => (
                            <div className="citations" key={index}>
                              {part.data.map((citation, citationIndex) => (
                                <button
                                  className="citation"
                                  key={`${citation.chunk_id}-${citationIndex}`}
                                  onClick={() => setSource(citation)}
                                  aria-label={`Open source ${citationIndex + 1}, page ${citation.page_number}`}
                                >
                                  <span className="citation-number">
                                    {citationIndex + 1}
                                  </span>
                                  <Icon name="file" size={14} />
                                  <span>
                                    {documentName(citation.document_id)}
                                  </span>
                                  <b>
                                    p.{" "}
                                    {citation.page_label ||
                                      citation.page_number}
                                  </b>
                                  <Icon name="link" size={13} />
                                </button>
                              ))}
                            </div>
                          ))}
                        {message.role === "assistant" &&
                          message.metadata?.model && (
                            <div className="message-footer">
                              <Icon name="shield" size={13} />
                              <span>
                                {message.metadata.profile === "fixture"
                                  ? "Fixture output"
                                  : `${message.metadata.profile} output`}
                              </span>
                              <span>·</span>
                              <span>Checked before display</span>
                            </div>
                          )}
                      </div>
                    </article>
                  ))}
                  {status === "submitted" && (
                    <div role="status" className="request-status">
                      <span className="spinner" />
                      Connecting to your workspace…
                    </div>
                  )}
                </div>
                <div className="composer-area">
                  {error && (
                    <div role="alert" className="alert">
                      <span>
                        {responseError || "The response was interrupted."}
                      </span>
                      <button
                        className="text-button"
                        onClick={() => void retry()}
                        disabled={busy}
                      >
                        Retry message
                      </button>
                    </div>
                  )}
                  {stopped && !error && (
                    <div role="status" className="stopped-notice">
                      <span>
                        Delivery stopped. The provider may continue processing;
                        a retry reuses the saved result when ready.
                      </span>
                      <button
                        className="text-button"
                        onClick={() => void retry()}
                        disabled={busy}
                      >
                        Retry message
                      </button>
                    </div>
                  )}
                  {restoredPending && !error && (
                    <div role="status" className="stopped-notice">
                      <span>
                        A previous request did not finish delivery. Check again
                        or retry with the same message.
                      </span>
                      <button
                        className="text-button"
                        onClick={() => void retry()}
                        disabled={busy}
                      >
                        Retry message
                      </button>
                    </div>
                  )}
                  <form
                    className="composer"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void ask();
                    }}
                  >
                    <label htmlFor="question" className="sr-only">
                      Ask your workspace
                    </label>
                    <textarea
                      ref={composerRef}
                      id="question"
                      value={input}
                      maxLength={8000}
                      rows={2}
                      placeholder="Ask a question about your documents…"
                      onChange={(event) => setInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (
                          event.key === "Enter" &&
                          !event.shiftKey &&
                          !event.nativeEvent.isComposing
                        ) {
                          event.preventDefault();
                          void ask();
                        }
                      }}
                      disabled={busy}
                    />
                    <div className="composer-controls">
                      <span>
                        <Icon name="file" size={14} />
                        {activeDocuments.length}{" "}
                        {activeDocuments.length === 1 ? "source" : "sources"} in
                        this workspace
                      </span>
                      {busy ? (
                        <button
                          type="button"
                          className="stop-button"
                          onClick={() => {
                            void stop();
                            setStopped(true);
                          }}
                        >
                          <span />
                          Stop response
                        </button>
                      ) : (
                        <button
                          className="send-button"
                          type="submit"
                          aria-label="Send question"
                          disabled={!input.trim()}
                        >
                          <Icon name="arrow" size={21} />
                        </button>
                      )}
                    </div>
                  </form>
                  <div className="composer-note">
                    <span>
                      Answers are checked before display. Always review cited
                      sources.
                    </span>
                    {firstDisplay !== null && (
                      <span data-testid="first-display">
                        First display: {firstDisplay} ms
                      </span>
                    )}
                  </div>
                </div>
              </>
            )}

            {tab === "documents" && (
              <section className="library-view">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">
                      THE KNOWLEDGE BEHIND EACH ANSWER
                    </span>
                    <h1>Source library</h1>
                    <p>
                      Versioned PDFs with a direct path back to the original
                      page.
                    </p>
                  </div>
                  <button
                    className="primary"
                    onClick={() => uploadRef.current?.click()}
                    disabled={uploading}
                  >
                    <Icon name="upload" size={17} />
                    {uploading ? "Processing…" : "Upload PDF"}
                  </button>
                </div>
                <div className="library-summary">
                  <span>
                    <strong>{activeDocuments.length}</strong> active documents
                  </span>
                  <span>
                    <strong>
                      {activeDocuments.reduce(
                        (sum, document) => sum + document.page_count,
                        0,
                      )}
                    </strong>{" "}
                    searchable pages
                  </span>
                  <span>PDF · up to 10 MiB each</span>
                </div>
                {loading && (
                  <p role="status" className="request-status">
                    <span className="spinner" />
                    Loading source library…
                  </p>
                )}
                {!loading && documents.length === 0 && (
                  <div className="empty-state">
                    <Icon name="file" size={32} />
                    <h2>Your source library is empty</h2>
                    <p>
                      Add a PDF to make its pages available for cited answers.
                    </p>
                    <button
                      className="secondary"
                      onClick={() => uploadRef.current?.click()}
                    >
                      Choose a PDF
                    </button>
                  </div>
                )}
                <div className="document-grid">
                  {documents.map((document) => (
                    <button
                      className="document-card"
                      key={document.version_id}
                      onClick={() => openDocument(document)}
                    >
                      <div className="document-card-top">
                        <span className="document-icon">
                          <Icon name="file" size={27} />
                        </span>
                        <span
                          className={`status-chip ${document.active ? "ready" : ""}`}
                        >
                          {document.active ? "Ready" : "Archived version"}
                        </span>
                      </div>
                      <h2>{document.filename}</h2>
                      <p>
                        {document.page_count}{" "}
                        {document.page_count === 1 ? "page" : "pages"} · Version{" "}
                        {document.version_id.slice(0, 8)}
                      </p>
                      <div className="document-card-bottom">
                        <span>Inspect source</span>
                        <Icon name="arrow" size={17} />
                      </div>
                    </button>
                  ))}
                </div>
              </section>
            )}

            {tab === "approvals" && (
              <section className="approvals-view">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">A HUMAN DECISION, RECORDED</span>
                    <h1>Review proposed actions</h1>
                    <p>
                      Inspect the exact action and source version before
                      approving.
                    </p>
                  </div>
                  <span className="status-chip amber">
                    {pendingApprovals.length} pending
                  </span>
                </div>
                <div className="approval-disclosure">
                  <Icon name="shield" size={19} />
                  <p>
                    Approved actions write to the local effect store. External
                    delivery is not connected.
                  </p>
                </div>
                {capability && (
                  <div className="execution-control">
                    <div>
                      <strong>
                        Local action execution is{" "}
                        {capability.enabled && !capability.emergency_disabled
                          ? "enabled"
                          : "paused"}
                      </strong>
                      <p>
                        {capability.emergency_disabled
                          ? "An operations control has paused execution for this environment."
                          : capability.enabled
                            ? "Approved actions may record their local effect."
                            : "Drafts and reviews remain available while execution is paused."}
                      </p>
                    </div>
                    <button
                      className="secondary"
                      disabled={
                        capabilityPending || capability.emergency_disabled
                      }
                      onClick={() => void toggleExecution()}
                    >
                      {capabilityPending
                        ? "Updating…"
                        : capability.enabled
                          ? "Pause execution"
                          : "Enable local execution"}
                    </button>
                  </div>
                )}
                {!approvals.length && !loading && (
                  <div className="empty-state compact">
                    <Icon name="check" size={31} />
                    <h2>No actions waiting for review</h2>
                    <p>
                      Submitted drafts will appear here with their review
                      status.
                    </p>
                  </div>
                )}
                {approvals.map((approval) => (
                  <article className="approval-card" key={approval.approval_id}>
                    <div className="approval-card-title">
                      <h2>
                        {approval.action.tool === "record_note"
                          ? "Record operational note"
                          : approval.action.tool.replaceAll("_", " ")}
                      </h2>
                      <span
                        className={`status-chip ${approval.status === "pending" ? "amber" : ""}`}
                      >
                        {approval.status}
                      </span>
                    </div>
                    <dl>
                      <div>
                        <dt>Requested by</dt>
                        <dd>{approval.requester}</dd>
                      </div>
                      <div>
                        <dt>Reviewer</dt>
                        <dd>{approval.reviewer}</dd>
                      </div>
                      <div>
                        <dt>Source</dt>
                        <dd>
                          {approval.action.arguments.context_id === "workspace"
                            ? "Workspace note"
                            : documentName(
                                String(approval.action.arguments.context_id),
                              )}
                          <span className="source-version-label">
                            Version{" "}
                            {approval.action.context_version.slice(0, 8)}
                          </span>
                        </dd>
                      </div>
                      <div>
                        <dt>Expires</dt>
                        <dd>
                          {new Date(approval.expires_at).toLocaleString()}
                        </dd>
                      </div>
                    </dl>
                    <div className="proposed-note">
                      <span className="eyebrow">PROPOSED NOTE</span>
                      <p>
                        {typeof approval.action.arguments.text === "string"
                          ? approval.action.arguments.text
                          : "Inspect the proposed action details before deciding."}
                      </p>
                    </div>
                    <details className="action-binding">
                      <summary>Inspect exact action and fingerprint</summary>
                      <pre className="action-preview">
                        {JSON.stringify(approval.action, null, 2)}
                      </pre>
                      <strong>Action fingerprint</strong>
                      <code>{approval.action_hash}</code>
                    </details>
                    {approval.status === "pending" && (
                      <div className="approval-actions">
                        <button
                          className="secondary"
                          onClick={() => void decision(approval, "reject")}
                          disabled={!!decisionPending}
                        >
                          Reject
                        </button>
                        <button
                          className="primary"
                          onClick={() => void decision(approval, "approve")}
                          disabled={!!decisionPending}
                        >
                          {decisionPending === approval.approval_id
                            ? "Saving decision…"
                            : "Approve exact action"}
                          <Icon name="check" size={17} />
                        </button>
                      </div>
                    )}
                  </article>
                ))}
                {(principal.roles.includes("writer") ||
                  principal.roles.includes("admin")) && (
                  <form
                    className="proposal-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void propose();
                    }}
                  >
                    <h2>Draft an operational note</h2>
                    <p>Submit a local note for an explicitly named reviewer.</p>
                    <label htmlFor="proposal">Note to record</label>
                    <textarea
                      id="proposal"
                      value={proposalText}
                      onChange={(event) => setProposalText(event.target.value)}
                      maxLength={4000}
                      rows={3}
                      required
                      placeholder="Describe the proposed note…"
                    />
                    <label htmlFor="reviewer">Reviewer identity</label>
                    <input
                      id="reviewer"
                      value={proposalReviewer}
                      onChange={(event) =>
                        setProposalReviewer(event.target.value)
                      }
                      required
                      maxLength={200}
                    />
                    <button
                      className="secondary"
                      disabled={proposalPending || !proposalText.trim()}
                    >
                      {proposalPending ? "Submitting…" : "Request approval"}
                      <Icon name="arrow" size={16} />
                    </button>
                    {proposalNotice && (
                      <p role="status" className="positive">
                        {proposalNotice}
                      </p>
                    )}
                  </form>
                )}
              </section>
            )}
          </main>

          <aside className="context-panel" aria-label="Workspace context">
            <div className="context-heading">
              <span className="eyebrow">WORKSPACE CONTEXT</span>
              <Icon name="file" size={17} />
            </div>
            <h2>Grounded in your sources</h2>
            <p>Every answer starts with the documents you provide.</p>
            <div className="context-metrics">
              <div>
                <strong>
                  {activeDocuments.length.toString().padStart(2, "0")}
                </strong>
                <span>Documents</span>
              </div>
              <div>
                <strong>
                  {activeDocuments
                    .reduce((sum, document) => sum + document.page_count, 0)
                    .toString()
                    .padStart(2, "0")}
                </strong>
                <span>Pages</span>
              </div>
            </div>
            <div className="context-list-title">
              <span>AVAILABLE SOURCES</span>
              <button
                className="icon-button"
                aria-label="Upload PDF to source library"
                onClick={() => uploadRef.current?.click()}
                disabled={uploading}
              >
                <Icon name="plus" size={17} />
              </button>
            </div>
            {activeDocuments.length ? (
              <div className="context-documents">
                {activeDocuments.slice(0, 5).map((document) => (
                  <button
                    key={document.version_id}
                    onClick={() => openDocument(document)}
                  >
                    <span className="small-file">
                      <Icon name="file" size={17} />
                    </span>
                    <span>
                      <strong>{document.filename}</strong>
                      <small>{document.page_count} pages · Ready</small>
                    </span>
                    <Icon name="link" size={13} />
                  </button>
                ))}
              </div>
            ) : (
              <button
                className="upload-zone"
                onClick={() => uploadRef.current?.click()}
                disabled={uploading}
              >
                <Icon name="upload" size={22} />
                <strong>
                  {uploading ? "Processing PDF…" : "Add a PDF source"}
                </strong>
                <span>Manuals, policies, and runbooks</span>
              </button>
            )}
            <div className="source-principles">
              <span className="eyebrow">HOW TO READ AN ANSWER</span>
              <div>
                <span>01</span>
                <p>Start with a specific operating question.</p>
              </div>
              <div>
                <span>02</span>
                <p>Open a citation to inspect its exact page and version.</p>
              </div>
              <div>
                <span>03</span>
                <p>Review proposed actions before they are executed.</p>
              </div>
            </div>
            <div className="context-bottom">
              <Icon name="shield" size={20} />
              <div>
                <strong>Sources stay in their workspace</strong>
                <p>
                  Access is checked by the server for every document and action.
                </p>
              </div>
            </div>
          </aside>
        </div>
      </div>
      <input
        ref={uploadRef}
        className="sr-only"
        type="file"
        accept="application/pdf,.pdf"
        aria-label="Upload PDF"
        onChange={(event) => void upload(event.target.files?.[0])}
      />

      <dialog
        ref={dialogRef}
        className="source-dialog"
        onCancel={closeSource}
        onClose={() => setSource(null)}
        onKeyDown={keepSourceFocus}
        aria-labelledby="source-title"
      >
        {source && (
          <>
            <div className="source-dialog-header">
              <div>
                <span className="eyebrow">SOURCE INSPECTION</span>
                <h2 id="source-title">{documentName(source.document_id)}</h2>
                <p>
                  Page {source.page_number} · Version{" "}
                  {source.version_id.slice(0, 8)}
                </p>
              </div>
              <button
                className="icon-button"
                aria-label="Close source inspection"
                onClick={closeSource}
              >
                <Icon name="close" />
              </button>
            </div>
            <div className="source-dialog-body">
              {sourceLoading && (
                <div role="status" className="request-status">
                  <span className="spinner" />
                  Loading the cited page…
                </div>
              )}
              {sourceError && (
                <div role="alert" className="alert">
                  <span>{sourceError}</span>
                  <button
                    className="text-button"
                    onClick={() => setSourceRetry((value) => value + 1)}
                  >
                    Retry source
                  </button>
                </div>
              )}
              {!sourceLoading && !sourceError && (
                <>
                  {source.quote && (
                    <section className="quoted-source">
                      <h3>Cited passage</h3>
                      <blockquote>{source.quote}</blockquote>
                    </section>
                  )}
                  <div className="source-page-heading">
                    <h3>Page {source.page_number} · Extracted text</h3>
                    {pdfUrl && (
                      <a
                        className="text-button"
                        href={`${pdfUrl}#page=${source.page_number}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Open original PDF
                        <Icon name="link" size={14} />
                      </a>
                    )}
                  </div>
                  <pre className="source-page" data-testid="source-page">
                    {sourceText || "This page has no extractable text."}
                  </pre>
                  <p className="fine">
                    Extraction can change visual layout. Use the original PDF to
                    verify tables and formatting.
                  </p>
                </>
              )}
            </div>
          </>
        )}
      </dialog>
    </div>
  );
}
