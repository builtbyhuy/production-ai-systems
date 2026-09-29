import type { UIMessage } from "ai";

export type Citation = {
  document_id: string;
  version_id: string;
  chunk_id: string;
  page_number: number;
  page_label?: string | null;
  start: number;
  end: number;
  quote: string;
  claim: string;
};
export type DocumentVersion = {
  document_id: string;
  version_id: string;
  filename: string;
  page_count: number;
  sha256: string;
  created_at: string;
  active: boolean;
};
export type ChatMetadata = {
  profile?: string;
  model?: string;
  abstained?: boolean;
  buffered?: boolean;
  firstDisplayMs?: number;
  providerTTFTMs?: number | null;
  replayed?: boolean;
  requestId?: string;
};
export type CopilotMessage = UIMessage<
  ChatMetadata,
  {
    citations: Citation[];
    status: { state: string; buffered: boolean };
  }
>;
export type Approval = {
  approval_id: string;
  requester: string;
  reviewer: string;
  action_hash: string;
  status:
    "pending" | "approved" | "rejected" | "cancelled" | "expired" | "executed";
  expires_at: string;
  action: {
    tool: string;
    arguments: Record<string, unknown>;
    context_version: string;
    idempotency_key: string;
  };
};
export type Health = {
  status: string;
  profile: string;
  fixture_auth: boolean;
  test_faults: boolean;
  required_validator_ready: boolean;
  evidence: string;
};
export type Principal = { subject: string; tenant_id: string; roles: string[] };
