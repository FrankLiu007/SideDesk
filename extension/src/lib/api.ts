import { DeskError } from '$lib/i18n/copy';

export type Lead = {
	id: number;
	platform_id: string;
	platform_name: string;
	url: string;
	title: string;
	excerpt: string;
	author: string;
	discovered_at: string;
	status: string;
	draft: string;
	reply_count: number;
	project_id: number;
	project_name: string;
	followup_zh: string;
	followup_en: string;
	unseen?: ReplyEvent[];
	comment_urls?: string[];
};

export type ChatMessage = {
	id: number;
	role: 'user' | 'assistant' | string;
	body: string;
	reasoning: string;
	created_at: string | null;
};

export type Project = {
	id: number;
	name: string;
	background: string;
	followup_zh: string;
	followup_en: string;
	active: boolean;
};

export type AiSource = {
	id: number;
	name: string;
	base_url: string;
	models: string[];
	configured: boolean;
	key_hint: string;
};

export type AiSettings = {
	sources: AiSource[];
	source_id: number | null;
	model: string;
	configured: boolean;
};

export type AiSourceInput = {
	name?: string;
	base_url?: string;
	api_key?: string;
};

export type ReplyEvent = {
	id: number;
	kind: string;
	detail: string;
	created_at: string | null;
};

export type Reply = {
	id: number;
	lead_id: number;
	lead_title: string;
	lead_url: string;
	platform_name: string;
	body: string;
	comment_url: string;
	posted_at: string | null;
	last_checked_at: string | null;
	score: number | null;
	child_count: number;
	deleted: boolean;
	last_error: string | null;
	unseen: ReplyEvent[];
};

export type Monitor = {
	id: number;
	platform_id: string;
	platform_name: string;
	kind: string;
	content: string;
	enabled: boolean;
	last_run_at: string | null;
	last_error: string | null;
};

export type Platform = {
	id: string;
	name: string;
	can_search: boolean;
	can_watch: boolean;
	can_refresh_reply: boolean;
};

function apiBase() {
	if (typeof location !== 'undefined' && location.protocol === 'chrome-extension:') return 'http://127.0.0.1:8765';
	return '';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	let response: Response;
	try {
		response = await fetch(`${apiBase()}${path}`, {
			headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
			...init
		});
	} catch {
		throw new DeskError('errors.offline');
	}
	if (!response.ok) {
		let detail = response.statusText;
		try {
			const body = await response.json();
			detail = body.detail ?? detail;
		} catch {
			/* keep status text */
		}
		throw typeof detail === 'string' && detail ? new Error(detail) : new DeskError('errors.request');
	}
	if (response.status === 204) return undefined as T;
	return response.json() as Promise<T>;
}

async function streamChat(
	id: number,
	message: string,
	draft: string,
	onEvent: (event: { reasoning?: string; delta?: string }) => void,
	signal: AbortSignal
): Promise<ChatMessage[]> {
	let response: Response;
	try {
		response = await fetch(`${apiBase()}/api/leads/${id}/chat/stream`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ message, draft }),
			signal
		});
	} catch (reason) {
		if (signal.aborted) throw reason;
		throw new DeskError('errors.offline');
	}
	if (!response.ok) {
		let detail = response.statusText;
		try {
			const body = await response.json();
			detail = body.detail ?? detail;
		} catch {
			/* keep status text */
		}
		throw typeof detail === 'string' && detail ? new Error(detail) : new DeskError('errors.request');
	}
	const reader = response.body?.getReader();
	if (!reader) throw new DeskError('errors.model');
	const decoder = new TextDecoder();
	let buffer = '';
	const state: { saved: ChatMessage[] | null } = { saved: null };
	const take = (block: string) => {
		for (const line of block.split('\n')) {
			const trimmed = line.trim();
			if (!trimmed.startsWith('data:')) continue;
			const payload = JSON.parse(trimmed.slice(5).trim()) as {
				reasoning?: string;
				delta?: string;
				error?: string;
				done?: boolean;
				messages?: ChatMessage[];
			};
			if (payload.error) throw new Error(payload.error);
			if (payload.reasoning) onEvent({ reasoning: payload.reasoning });
			if (payload.delta) onEvent({ delta: payload.delta });
			if (payload.done && payload.messages) state.saved = payload.messages;
		}
	};
	while (true) {
		const { value, done } = await reader.read();
		buffer += decoder.decode(value, { stream: !done });
		const blocks = buffer.split('\n\n');
		buffer = blocks.pop() ?? '';
		for (const block of blocks) take(block);
		if (done) break;
	}
	if (buffer.trim()) take(buffer);
	if (!state.saved) throw new DeskError('errors.model');
	return state.saved.map((item) => ({ ...item, reasoning: item.reasoning ?? '' }));
}

export type Match = {
	lead: Lead | null;
	on_comment: boolean;
	comment_url: string;
};

export const api = {
	today: () => request<{ needs_reply: Lead[]; followups: Lead[] }>('/api/today'),
	refresh: () =>
		request<{ leads_found: number; monitor_errors: string[]; replies_checked: number; new_events: number }>(
			'/api/refresh',
			{ method: 'POST' }
		),
	leads: (query = '') => request<Lead[]>(`/api/leads${query}`),
	match: (url: string) => request<Match>(`/api/leads/match?url=${encodeURIComponent(url)}`),
	createLead: (body: { url: string; title: string; excerpt: string }) =>
		request<Lead>('/api/leads', { method: 'POST', body: JSON.stringify(body) }),
	setStatus: (id: number, status: string) =>
		request<Lead>(`/api/leads/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
	deleteLead: (id: number) => request<void>(`/api/leads/${id}`, { method: 'DELETE' }),
	saveDraft: (id: number, body: string) =>
		request<Lead>(`/api/leads/${id}/draft`, { method: 'PUT', body: JSON.stringify({ body }) }),
	addReply: (id: number, comment_url: string, body: string) =>
		request<Reply>(`/api/leads/${id}/replies`, {
			method: 'POST',
			body: JSON.stringify({ comment_url, body })
		}),
	replies: () => request<Reply[]>('/api/replies'),
	seen: (id: number) => request<Reply>(`/api/replies/${id}/seen`, { method: 'POST' }),
	monitors: () => request<Monitor[]>('/api/monitors'),
	platforms: () => request<Platform[]>('/api/platforms'),
	createMonitor: (body: { platform_id?: string; kind: string; content: string }) =>
		request<Monitor>('/api/monitors', { method: 'POST', body: JSON.stringify(body) }),
	patchMonitor: (id: number, body: { enabled?: boolean; content?: string }) =>
		request<Monitor>(`/api/monitors/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deleteMonitor: (id: number) => request<void>(`/api/monitors/${id}`, { method: 'DELETE' }),
	aiSettings: () => request<AiSettings>('/api/settings/ai'),
	saveAiSelection: (body: { source_id: number; model: string }) =>
		request<AiSettings>('/api/settings/ai', { method: 'PUT', body: JSON.stringify(body) }),
	createAiSource: (body: AiSourceInput) =>
		request<AiSettings>('/api/settings/ai/sources', { method: 'POST', body: JSON.stringify(body) }),
	updateAiSource: (id: number, body: AiSourceInput) =>
		request<AiSettings>(`/api/settings/ai/sources/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	deleteAiSource: (id: number) =>
		request<AiSettings>(`/api/settings/ai/sources/${id}`, { method: 'DELETE' }),
	aiSourceModels: (id: number) =>
		request<{ models: string[] }>(`/api/settings/ai/sources/${id}/models`, { method: 'POST' }),
	aiSourceTest: (id: number, model = '') =>
		request<{ ok: boolean; model: string; reply: string }>(`/api/settings/ai/sources/${id}/test`, {
			method: 'POST',
			body: JSON.stringify({ model })
		}),
	projects: () => request<Project[]>('/api/projects'),
	createProject: (body: { name: string; background?: string; followup_zh?: string; followup_en?: string }) =>
		request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
	updateProject: (
		id: number,
		body: { name?: string; background?: string; followup_zh?: string; followup_en?: string }
	) => request<Project>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
	activateProject: (id: number) => request<Project>(`/api/projects/${id}/activate`, { method: 'POST' }),
	messages: (id: number) => request<ChatMessage[]>(`/api/leads/${id}/messages`),
	streamChat: (
		id: number,
		message: string,
		draft: string,
		onEvent: (event: { reasoning?: string; delta?: string }) => void,
		signal: AbortSignal
	) => streamChat(id, message, draft, onEvent, signal),
	adoptDraft: (id: number, body: string) =>
		request<Lead>(`/api/leads/${id}/draft/adopt`, { method: 'POST', body: JSON.stringify({ body }) })
};

export function replyFence(body: string) {
	const matches = [...body.matchAll(/```reply\s*\n([\s\S]*?)```/gi)];
	if (!matches.length) return '';
	return matches[matches.length - 1][1].trim();
}

export async function copyText(value: string) {
	await navigator.clipboard.writeText(value);
}
