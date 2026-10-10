<script lang="ts">
	import { resolve } from '$app/paths';
	import { onDestroy, onMount, untrack } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { api, copyText, replyFence, type ChatMessage, type Lead, type ReplyEvent } from '$lib/api';
	import CopyLine from '$lib/components/CopyLine.svelte';
	import { fromReason, keyed, type Copy } from '$lib/i18n/copy';
	import { openInWindow } from '$lib/tab';
	import { eventTone, sameUrl, statusTone } from '$lib/ui';

	let {
		lead,
		unseen = [],
		commentUrls = [],
		onComment = false,
		liveCommentUrl = '',
		onchange,
		onseen
	}: {
		lead: Lead;
		unseen?: ReplyEvent[];
		commentUrls?: string[];
		onComment?: boolean;
		liveCommentUrl?: string;
		onchange?: (lead: Lead, notedUrl?: string) => void;
		onseen?: () => Promise<void>;
	} = $props();

	let draft = $state(untrack(() => lead.draft));
	let manualUrl = $state('');
	let notice = $state<Copy | null>(null);
	let error = $state<Copy | null>(null);
	let busy = $state(false);
	let followZh = $derived(lead.followup_zh);
	let followEn = $derived(lead.followup_en);
	let messages = $state<ChatMessage[]>([]);
	let chatText = $state('');
	let chatting = $state(false);
	let aiReady = $state(false);
	let chatError = $state<Copy | null>(null);
	let chatNotice = $state<Copy | null>(null);
	let transcript = $state<HTMLDivElement | null>(null);
	let autoScroll = $state(true);
	let composing = false;
	let compositionEndedAt = -2e8;
	let chatAbort: AbortController | null = null;
	const isSafari =
		typeof navigator !== 'undefined' && /^((?!chrome|android).)*safari/i.test(navigator.userAgent);

	let followUp = $derived(unseen.length > 0);
	let drafting = $derived(!followUp && (lead.status === 'unread' || lead.status === 'drafted'));
	let noted = $derived(
		Boolean(liveCommentUrl) && commentUrls.some((url) => sameUrl(url, liveCommentUrl))
	);
	let showCapture = $derived(onComment && Boolean(liveCommentUrl) && !noted);

	function catalog(group: string, id: string) {
		const key = `${group}.${id}`;
		const value = $_(key);
		return value === key ? id : value;
	}

	onMount(() => {
		if (!drafting) return;
		api
			.aiSettings()
			.then((settings) => (aiReady = settings.configured))
			.catch(() => {});
		api
			.messages(lead.id)
			.then((rows) => (messages = rows.map((row) => ({ ...row, reasoning: row.reasoning ?? '' }))))
			.catch(() => {});
	});

	onDestroy(() => {
		chatAbort?.abort();
	});

	$effect(() => {
		const last = messages.at(-1);
		const marker = `${last?.reasoning ?? ''}\n${last?.body ?? ''}`;
		if (!autoScroll || !transcript) return;
		void marker;
		transcript.scrollTop = transcript.scrollHeight;
	});

	async function saveDraft() {
		busy = true;
		error = null;
		try {
			const saved = await api.saveDraft(lead.id, draft);
			onchange?.(saved);
			notice = keyed('draft.saved');
		} catch (reason) {
			error = fromReason(reason, 'errors.save');
		} finally {
			busy = false;
		}
	}

	async function markSkipped() {
		busy = true;
		error = null;
		try {
			const saved = await api.setStatus(lead.id, 'skipped');
			onchange?.(saved);
			notice = keyed('draft.skipped');
		} catch (reason) {
			error = fromReason(reason, 'errors.update');
		} finally {
			busy = false;
		}
	}

	async function copyDraft() {
		error = null;
		try {
			await copyText(draft);
			notice = keyed('draft.copiedPaste');
		} catch {
			error = keyed('errors.copy');
		}
	}

	async function copyFollow(value: string) {
		error = null;
		try {
			await copyText(value);
			notice = keyed('draft.copiedFollow');
		} catch {
			error = keyed('errors.copy');
		}
	}

	async function recordReply(url: string) {
		const target = url.trim();
		if (!target) return;
		busy = true;
		error = null;
		try {
			await api.addReply(lead.id, target, draft);
			manualUrl = '';
			onchange?.({ ...lead, status: 'replied', draft, reply_count: lead.reply_count + 1 }, target);
			notice = keyed('draft.recorded');
		} catch (reason) {
			error = fromReason(reason, 'errors.record');
		} finally {
			busy = false;
		}
	}

	function onTranscriptScroll() {
		if (!transcript) return;
		autoScroll =
			transcript.scrollHeight - transcript.scrollTop <= transcript.clientHeight + 5;
	}

	function inOrNearComposition(event: KeyboardEvent) {
		if (composing) return true;
		if (isSafari && Math.abs(event.timeStamp - compositionEndedAt) < 500) {
			compositionEndedAt = -2e8;
			return true;
		}
		return false;
	}

	function onChatKeydown(event: KeyboardEvent) {
		if (inOrNearComposition(event)) return;
		const enter = event.key === 'Enter' || event.keyCode === 13;
		if (!enter || event.shiftKey || chatting) return;
		event.preventDefault();
		void sendChat();
	}

	function appendPiece(field: 'body' | 'reasoning', delta: string) {
		const index = messages.length - 1;
		const current = messages[index];
		if (!current) return;
		messages[index] = { ...current, [field]: current[field] + delta };
	}

	function dropPending(userId: number, assistantId: number, text: string) {
		messages = messages.filter((item) => item.id !== userId && item.id !== assistantId);
		chatText = text;
	}

	function stopChat() {
		chatAbort?.abort();
	}

	async function sendChat() {
		const text = chatText.trim();
		if (!text || chatting) return;
		const userId = -Date.now();
		const assistantId = userId - 1;
		chatText = '';
		autoScroll = true;
		chatting = true;
		chatError = null;
		chatNotice = null;
		messages = [
			...messages,
			{ id: userId, role: 'user', body: text, reasoning: '', created_at: null },
			{ id: assistantId, role: 'assistant', body: '', reasoning: '', created_at: null }
		];
		const controller = new AbortController();
		chatAbort = controller;
		try {
			const saved = await api.streamChat(
				lead.id,
				text,
				draft,
				(event) => {
					if (event.reasoning) appendPiece('reasoning', event.reasoning);
					if (event.delta) appendPiece('body', event.delta);
				},
				controller.signal
			);
			const same =
				saved.length === messages.length &&
				saved.every(
					(item, index) =>
						item.body === messages[index].body && (item.reasoning ?? '') === messages[index].reasoning
				);
			messages = same
				? messages.map((item, index) => ({
						...item,
						id: saved[index].id,
						created_at: saved[index].created_at
					}))
				: saved.map((item) => ({ ...item, reasoning: item.reasoning ?? '' }));
		} catch (reason) {
			dropPending(userId, assistantId, text);
			if (!controller.signal.aborted) {
				chatError = fromReason(reason, 'errors.model');
			}
		} finally {
			chatting = false;
			chatAbort = null;
		}
	}

	async function adopt(body: string) {
		busy = true;
		chatError = null;
		try {
			const saved = await api.adoptDraft(lead.id, body);
			draft = saved.draft;
			onchange?.(saved);
			chatNotice = keyed('draft.adopted');
		} catch (reason) {
			chatError = fromReason(reason, 'errors.adopt');
		} finally {
			busy = false;
		}
	}

	async function markSeen() {
		if (!onseen) return;
		busy = true;
		error = null;
		try {
			await onseen();
			notice = keyed('draft.seen');
		} catch (reason) {
			error = fromReason(reason, 'errors.update');
		} finally {
			busy = false;
		}
	}
</script>

<section class="card">
	<div class="flex flex-wrap items-start justify-between gap-2">
		<div class="min-w-0">
			<h2 class="text-lg font-semibold tracking-tight text-stone-950">{lead.title || $_('draft.untitled')}</h2>
			{#if lead.url}
				<button
					type="button"
					class="link mt-2 block max-w-full text-left font-normal break-all"
					onclick={() => openInWindow(lead.url)}
				>
					{lead.url}
				</button>
			{/if}
			{#if lead.excerpt}
				<p class="mt-2 text-sm leading-6 text-stone-600">{lead.excerpt}</p>
			{/if}
		</div>
		<div class="flex flex-wrap gap-1.5">
			<span class="badge bg-stone-100 text-stone-700">{lead.platform_name}</span>
			<span class="badge {statusTone(lead.status)}">{catalog('status', lead.status)}</span>
		</div>
	</div>

	{#if error}
		<p class="banner mt-3 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={error} /></p>
	{/if}
	{#if notice}
		<p class="banner mt-3 border-teal-200 bg-teal-50 text-teal-900"><CopyLine item={notice} /></p>
	{/if}

	{#if followUp}
		<ul class="mt-4 space-y-2">
			{#each unseen as event (event.id)}
				<li class="flex flex-wrap items-start gap-2 text-sm text-stone-700">
					<span class="badge {eventTone(event.kind)}">{catalog('event', event.kind)}</span>
					<span>{event.detail}</span>
				</li>
			{/each}
		</ul>
		{#if followZh || followEn}
			<div class="mt-5 border-t border-stone-100 pt-5">
				<h3 class="text-base font-semibold text-stone-950">{$_('draft.followTitle')}</h3>
				<p class="mt-1 text-sm text-stone-500">{$_('draft.followHint')}</p>
				<div class="mt-3 grid gap-3">
					{#if followZh}
						<div class="rounded-xl border border-stone-200 bg-stone-50 p-3">
							<p class="text-xs font-medium tracking-wide text-stone-500">{$_('common.zh')}</p>
							<p class="mt-2 text-sm leading-6 whitespace-pre-wrap text-stone-800">{followZh}</p>
							<button type="button" class="btn-ghost mt-3" onclick={() => copyFollow(followZh)}>{$_('draft.copyZh')}</button>
						</div>
					{/if}
					{#if followEn}
						<div class="rounded-xl border border-stone-200 bg-stone-50 p-3">
							<p class="text-xs font-medium tracking-wide text-stone-500">{$_('common.en')}</p>
							<p class="mt-2 text-sm leading-6 whitespace-pre-wrap text-stone-800">{followEn}</p>
							<button type="button" class="btn-ghost mt-3" onclick={() => copyFollow(followEn)}>{$_('draft.copyEn')}</button>
						</div>
					{/if}
				</div>
			</div>
		{/if}
		<button type="button" class="btn-ghost mt-4" onclick={markSeen} disabled={busy}>{$_('draft.markSeen')}</button>
	{:else if !drafting}
		{#if commentUrls.length}
			<div class="mt-4 flex flex-col items-start gap-2">
				{#each commentUrls as url, index (url)}
					<button type="button" class="link" onclick={() => openInWindow(url)}>
						{commentUrls.length > 1
							? $_('draft.openCommentN', { values: { index: index + 1 } })
							: $_('draft.openComment')}
					</button>
				{/each}
			</div>
		{/if}
		{#if lead.draft}
			<p class="mt-4 text-sm leading-6 whitespace-pre-wrap text-stone-800">{lead.draft}</p>
		{/if}
	{:else}
		<label class="label mt-4" for="draft-{lead.id}">{$_('draft.label')}</label>
		<textarea id="draft-{lead.id}" class="field mt-1.5 min-h-40 resize-y leading-6" bind:value={draft}></textarea>
		<div class="mt-3 flex flex-wrap gap-2">
			<button type="button" class="btn" onclick={saveDraft} disabled={busy}>{$_('draft.save')}</button>
			<button type="button" class="btn-ghost" onclick={copyDraft}>{$_('draft.copy')}</button>
			<button type="button" class="btn-ghost" onclick={markSkipped} disabled={busy}>{$_('draft.skip')}</button>
		</div>
	{/if}

	{#if showCapture && !drafting}
		<button type="button" class="btn mt-4" onclick={() => recordReply(liveCommentUrl)} disabled={busy}>
			{$_('draft.noteLive')}
		</button>
	{/if}
</section>

{#if drafting}
	<section
		class="mt-4 flex h-[min(32rem,70vh)] flex-col overflow-hidden rounded-2xl border border-stone-800 bg-white shadow-[0_12px_32px_rgba(28,25,23,0.08)]"
		aria-labelledby="draft-chat-title"
	>
		<header class="shrink-0 bg-ink px-4 py-3">
			<h3 id="draft-chat-title" class="text-sm font-semibold tracking-tight text-white">{$_('draft.chatTitle')}</h3>
			<p class="mt-1 text-xs leading-5 text-stone-400">{$_('draft.chatHint')}</p>
		</header>
		{#if chatError}
			<p class="banner mx-3 mt-3 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={chatError} /></p>
		{/if}
		{#if chatNotice}
			<p class="banner mx-3 mt-3 border-teal-200 bg-teal-50 text-teal-900"><CopyLine item={chatNotice} /></p>
		{/if}
		{#if !aiReady}
			<p class="mx-4 mt-3 text-sm text-stone-600">
				{$_('draft.noModel')}
				<a class="link" href={resolve('/settings')}>{$_('draft.goSettings')}</a>
			</p>
		{/if}
		<div bind:this={transcript} onscroll={onTranscriptScroll} class="min-h-0 flex-1 overflow-y-auto bg-paper px-3 py-3">
			{#if messages.length}
				<ol class="space-y-4">
					{#each messages as message (message.id)}
						{@const mine = message.role === 'user'}
						{@const pending = chatting && !mine && message.id === messages.at(-1)?.id}
						<li class={mine ? 'flex flex-col items-end' : 'flex flex-col items-start'}>
							<p class={['text-xs font-medium', mine ? 'text-teal-800' : 'text-stone-500']}>
								{mine ? $_('common.you') : $_('common.model')}
							</p>
							{#if message.reasoning}
								<p class="mt-1 text-xs font-medium text-stone-400">{$_('draft.thinking')}</p>
								<p class="mt-1 max-w-[92%] rounded-xl bg-white/80 px-3 py-2 text-sm leading-6 whitespace-pre-wrap text-stone-500">
									{message.reasoning}
								</p>
							{/if}
							{#if message.body || pending}
								<p
									class={[
										'mt-1 max-w-[92%] px-3 py-2 text-sm leading-6 whitespace-pre-wrap',
										mine
											? 'rounded-2xl rounded-br-md bg-teal-800 text-white'
											: 'rounded-2xl rounded-bl-md border border-stone-200 bg-white text-stone-800'
									]}
								>
									{message.body || $_('draft.writing')}
								</p>
							{/if}
							{#if !chatting && !mine && replyFence(message.body)}
								<button
									type="button"
									class="btn-ghost mt-2"
									onclick={() => adopt(replyFence(message.body))}
									disabled={busy}
								>
									{$_('draft.adopt')}
								</button>
							{/if}
						</li>
					{/each}
				</ol>
			{:else}
				<p class="flex h-full items-center justify-center px-6 text-center text-sm leading-6 text-stone-400">
					{$_('draft.chatEmpty')}
				</p>
			{/if}
		</div>
		<div class="shrink-0 border-t border-stone-200 bg-white px-3 py-3">
			<label class="label" for="chat-{lead.id}">{$_('draft.continueLabel')}</label>
			<textarea
				id="chat-{lead.id}"
				class="field mt-1.5 min-h-16 resize-y leading-6"
				bind:value={chatText}
				placeholder={draft.trim() ? $_('draft.placeholderEdit') : $_('draft.placeholderNew')}
				disabled={!aiReady}
				oncompositionstart={() => (composing = true)}
				oncompositionend={(event) => {
					compositionEndedAt = event.timeStamp;
					composing = false;
				}}
				onkeydown={onChatKeydown}
			></textarea>
			{#if chatting}
				<button type="button" class="btn mt-3" onclick={stopChat}>{$_('draft.stop')}</button>
			{:else}
				<button type="button" class="btn mt-3" onclick={sendChat} disabled={!aiReady || !chatText.trim()}>
					{$_('draft.send')}
				</button>
			{/if}
		</div>
	</section>
	<section class="card mt-4">
		{#if showCapture}
			<button type="button" class="btn" onclick={() => recordReply(liveCommentUrl)} disabled={busy}>
				{$_('draft.noteLive')}
			</button>
		{/if}
		<label class={['label', showCapture ? 'mt-4' : '']} for="comment-{lead.id}">
			{showCapture ? $_('draft.orOtherLink') : $_('draft.commentLink')}
		</label>
		<input
			id="comment-{lead.id}"
			class="field mt-1.5"
			type="url"
			bind:value={manualUrl}
			placeholder={$_('draft.commentPlaceholder')}
		/>
		<button
			type="button"
			class={['mt-3', showCapture ? 'btn-ghost' : 'btn']}
			onclick={() => recordReply(manualUrl)}
			disabled={busy || !manualUrl.trim()}
		>
			{$_('draft.noteReply')}
		</button>
	</section>
{/if}
