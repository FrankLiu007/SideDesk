<script lang="ts">
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { api, type Lead, type Reply, type ReplyEvent } from '$lib/api';
	import CopyLine from '$lib/components/CopyLine.svelte';
	import LeadDraft from '$lib/components/LeadDraft.svelte';
	import OnReady from '$lib/components/OnReady.svelte';
	import { activateProject, desk } from '$lib/desk.svelte';
	import { fromReason, keyed, type Copy } from '$lib/i18n/copy';
	import { openInWindow, pageTitle, watchTab, type BrowserTab } from '$lib/tab';
	import { eventTone, sameUrl, statusTone } from '$lib/ui';

	type Filter = 'needs_reply' | 'followups' | 'skipped';
	type Selection = {
		lead: Lead;
		unseen: ReplyEvent[];
		replyIds: number[];
		commentUrls: string[];
	};
	type PlatformGroup = { platform_id: string; platform_name: string; items: Lead[] };

	const filters = [
		{ id: 'needs_reply', label: 'inbox.needsReply' },
		{ id: 'followups', label: 'inbox.followups' },
		{ id: 'skipped', label: 'inbox.skipped' }
	] as const;

	let filter = $state<Filter>('needs_reply');
	let needsReply = $state<Lead[]>([]);
	let followups = $state<Lead[]>([]);
	let skippedLeads = $state<Lead[]>([]);
	let selected = $state<Selection | null>(null);
	let listError = $state<Copy | null>(null);
	let tabError = $state<Copy | null>(null);
	let message = $state<Copy | null>(null);
	let busy = $state(false);
	let deletingId = $state<number | null>(null);
	let pendingDelete = $state<Lead | null>(null);
	let deleteButton: HTMLElement | null = null;
	let refreshing = $state(false);
	let loaded = $state(false);

	let tab = $state<BrowserTab | null>(null);
	let tabLead = $state<Lead | null>(null);
	let tabOnComment = $state(false);
	let tabCommentUrl = $state('');
	let tabMode = $state<'loading' | 'offline' | 'preview' | 'unsupported' | 'ready'>('loading');

	let loadedUrl = '';
	let tabTicket = 0;
	let loadTicket = 0;
	let openTicket = 0;

	function groupLeads(items: Lead[]): PlatformGroup[] {
		const groups: PlatformGroup[] = [];
		for (const lead of items) {
			let group = groups.find((item) => item.platform_id === lead.platform_id);
			if (!group) {
				group = { platform_id: lead.platform_id, platform_name: lead.platform_name, items: [] };
				groups.push(group);
			}
			group.items.push(lead);
		}
		return groups;
	}

	let activeItems = $derived(
		filter === 'needs_reply' ? needsReply : filter === 'followups' ? followups : skippedLeads
	);
	let groups = $derived(groupLeads(activeItems));
	let queue = $derived(groups.flatMap((group) => group.items));
	let selectedIndex = $derived.by(() => {
		const current = selected;
		if (!current) return -1;
		return queue.findIndex((item) => item.id === current.lead.id);
	});

	function catalog(group: string, id: string) {
		const key = `${group}.${id}`;
		const value = $_(key);
		return value === key ? id : value;
	}

	async function load() {
		const current = ++loadTicket;
		const next = filter;
		try {
			if (next === 'skipped') {
				const nextLeads = await api.leads('?status=skipped');
				if (current !== loadTicket) return;
				skippedLeads = nextLeads;
				needsReply = [];
				followups = [];
			} else {
				const data = await api.today();
				if (current !== loadTicket) return;
				needsReply = data.needs_reply;
				followups = data.followups;
				skippedLeads = [];
			}
			listError = null;
		} catch (reason) {
			if (current !== loadTicket) return;
			listError = fromReason(reason, 'errors.request');
		} finally {
			if (current === loadTicket) loaded = true;
		}
	}

	function chooseFilter(next: Filter) {
		filter = next;
		selected = null;
		message = null;
		needsReply = [];
		followups = [];
		skippedLeads = [];
		loaded = false;
		void load();
	}

	async function syncTab(next: BrowserTab | 'preview' | null, force = false) {
		if (next === 'preview') {
			tab = null;
			tabLead = null;
			tabOnComment = false;
			tabCommentUrl = '';
			loadedUrl = '';
			tabMode = 'preview';
			return;
		}
		tab = next;
		if (!next) {
			tabLead = null;
			tabOnComment = false;
			tabCommentUrl = '';
			loadedUrl = '';
			tabMode = 'unsupported';
			return;
		}
		if (!force && next.url === loadedUrl && tabMode === 'ready') return;
		loadedUrl = next.url;
		const current = ++tabTicket;
		if (tabMode !== 'ready') tabMode = 'loading';
		try {
			const matched = await api.match(next.url);
			if (current !== tabTicket) return;
			tabLead = matched.lead;
			tabOnComment = matched.on_comment;
			tabCommentUrl = matched.comment_url;
			tabMode = 'ready';
			tabError = null;
		} catch (reason) {
			if (current !== tabTicket) return;
			tabLead = null;
			tabOnComment = false;
			tabCommentUrl = '';
			tabError = fromReason(reason, 'errors.request');
			tabMode = 'offline';
		}
	}

	function targetFor(lead: Lead) {
		if (filter === 'followups') {
			const url = lead.comment_urls?.find(Boolean);
			if (url) return url;
		}
		return lead.url;
	}

	async function openWork(lead: Lead, target: string) {
		const current = ++openTicket;
		const replies = await api.replies().catch(() => [] as Reply[]);
		if (current !== openTicket) return;
		const mine = replies.filter((reply) => reply.lead_id === lead.id);
		selected = {
			lead,
			unseen: mine.flatMap((reply) => reply.unseen),
			replyIds: mine.filter((reply) => reply.unseen.length).map((reply) => reply.id),
			commentUrls: mine.map((reply) => reply.comment_url).filter(Boolean)
		};
		try {
			await openInWindow(target);
		} catch (reason) {
			if (current !== openTicket) return;
			listError = fromReason(reason, 'errors.openTab');
		}
	}

	async function step(delta: number) {
		const next = queue[selectedIndex + delta];
		if (!next) return;
		await openWork(next, targetFor(next));
	}

	async function addCurrent() {
		if (!tab) return;
		busy = true;
		listError = null;
		try {
			const created = await api.createLead({
				url: tab.url,
				title: pageTitle(tab.title) || tab.title,
				excerpt: ''
			});
			tabLead = created;
			await load();
			await openWork(created, tab.url);
		} catch (reason) {
			listError = fromReason(reason, 'errors.add');
		} finally {
			busy = false;
		}
	}

	function applyLead(saved: Lead, notedUrl = '') {
		const advance = Boolean(notedUrl) && filter === 'needs_reply';
		const index = queue.findIndex((item) => item.id === saved.id);
		const upcoming = advance && index >= 0 ? (queue[index + 1] ?? null) : null;
		if (selected?.lead.id === saved.id) {
			const commentUrls =
				notedUrl && !selected.commentUrls.some((url) => sameUrl(url, notedUrl))
					? [...selected.commentUrls, notedUrl]
					: selected.commentUrls;
			selected = { ...selected, lead: saved, commentUrls };
		}
		if (!advance) {
			void load();
			return;
		}
		void (async () => {
			await load();
			if (upcoming) await openWork(upcoming, targetFor(upcoming));
			else if (selected?.lead.id === saved.id) selected = null;
		})();
	}

	function askRemove(lead: Lead, event: MouseEvent) {
		if (deletingId !== null) return;
		const button = event.currentTarget;
		if (!(button instanceof HTMLElement)) return;
		deleteButton = button;
		pendingDelete = lead;
	}

	function dismissRemove() {
		if (deletingId !== null) return;
		pendingDelete = null;
		deleteButton = null;
	}

	function placeDeletePopup(node: HTMLElement) {
		const place = () => {
			const button = deleteButton;
			if (!button?.isConnected) return;
			const rect = button.getBoundingClientRect();
			const box = node.getBoundingClientRect();
			const width = box.width || Math.min(288, window.innerWidth - 16);
			const height = box.height || node.scrollHeight;
			let left = rect.left;
			if (left + width > window.innerWidth - 8) left = window.innerWidth - 8 - width;
			if (left < 8) left = 8;
			let top = rect.bottom + 8;
			if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 8);
			node.style.top = `${top}px`;
			node.style.left = `${left}px`;
			node.classList.remove('invisible');
		};
		place();
		window.addEventListener('scroll', place, true);
		window.addEventListener('resize', place);
		node.focus();
		return () => {
			window.removeEventListener('scroll', place, true);
			window.removeEventListener('resize', place);
		};
	}

	function onConfirmKey(event: KeyboardEvent) {
		if (pendingDelete && event.key === 'Escape') dismissRemove();
	}

	async function removeLead() {
		const lead = pendingDelete;
		if (!lead) return;
		const fromDetail = selected?.lead.id === lead.id;
		const index = fromDetail ? queue.findIndex((item) => item.id === lead.id) : -1;
		const upcoming = index >= 0 ? (queue[index + 1] ?? null) : null;
		deletingId = lead.id;
		listError = null;
		try {
			await api.deleteLead(lead.id);
			if (tabLead?.id === lead.id) tabLead = null;
			message = keyed('inbox.deleted');
			if (fromDetail && upcoming) await openWork(upcoming, targetFor(upcoming));
			else if (selected?.lead.id === lead.id) selected = null;
			await load();
		} catch (reason) {
			listError = fromReason(reason, 'errors.delete');
		} finally {
			deletingId = null;
			pendingDelete = null;
			deleteButton = null;
		}
	}

	async function markSeen() {
		if (!selected) return;
		const leadId = selected.lead.id;
		for (const id of selected.replyIds) await api.seen(id);
		if (selected?.lead.id === leadId) selected = { ...selected, unseen: [], replyIds: [] };
		await load();
	}

	async function refresh() {
		refreshing = true;
		listError = null;
		try {
			const result = await api.refresh();
			const summary = keyed('inbox.refreshResult', {
				checked: result.replies_checked,
				events: result.new_events,
				found: result.leads_found
			});
			if (result.monitor_errors.length) {
				summary.suffixKey = 'inbox.refreshSuffix';
				summary.suffixValues = { errors: result.monitor_errors.join('; ') };
			}
			message = summary;
			await load();
		} catch (reason) {
			listError = fromReason(reason, 'errors.refresh');
		} finally {
			refreshing = false;
		}
	}

	function reloadForProject() {
		if (selected && selected.lead.project_id !== desk.activeId) selected = null;
		void load();
	}

	onMount(() => {
		const stop = watchTab((next) => void syncTab(next));
		return stop;
	});
</script>

{#if desk.ready}
	{#key desk.token}
		<OnReady run={reloadForProject} />
	{/key}
{/if}

<section class="rounded-xl border border-stone-200 bg-white px-3 py-2.5">
	{#if tabMode === 'loading'}
		<p class="text-sm text-stone-500">{$_('inbox.readingTab')}</p>
	{:else if tabMode === 'preview'}
		<p class="text-sm leading-6 text-stone-500">{$_('inbox.preview')}</p>
	{:else if tabMode === 'unsupported'}
		<p class="text-sm leading-6 text-stone-500">{$_('inbox.unsupported')}</p>
	{:else if tabMode === 'offline'}
		<button type="button" class="btn-ghost" onclick={() => syncTab(tab, true)}>{$_('inbox.matchAgain')}</button>
	{:else if tabLead}
		{@const current = tabLead}
		<div class="flex items-center justify-between gap-2">
			<p class="min-w-0 truncate text-sm font-medium text-stone-900">{current.title || tab?.url}</p>
			{#if current.project_id !== desk.activeId}
				<button type="button" class="btn shrink-0" onclick={() => activateProject(current.project_id)}>
					{$_('inbox.switchProject', { values: { name: current.project_name } })}
				</button>
			{:else if selected && current.id !== selected.lead.id}
				<button type="button" class="btn shrink-0" onclick={() => tab && openWork(current, tab.url)}
					>{$_('inbox.watchThis')}</button
				>
			{:else if !selected}
				<button type="button" class="btn shrink-0" onclick={() => tab && openWork(current, tab.url)}
					>{$_('inbox.workThis')}</button
				>
			{:else if tabOnComment}
				<span class="shrink-0 text-xs font-medium text-teal-800">{$_('inbox.onComment')}</span>
			{/if}
		</div>
	{:else if tab}
		<div class="flex items-center justify-between gap-2">
			<p class="min-w-0 truncate text-sm text-stone-600">{pageTitle(tab.title) || tab.url}</p>
			<button type="button" class="btn shrink-0" onclick={addCurrent} disabled={busy}>{$_('inbox.addLead')}</button>
		</div>
	{/if}
</section>

{#if tabError}
	<p class="banner mt-3 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={tabError} /></p>
{/if}
{#if listError}
	<p class="banner mt-3 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={listError} /></p>
	<button type="button" class="btn-ghost mt-3" onclick={() => load()}>{$_('common.retry')}</button>
{/if}

{#if selected}
	{@const item = selected}
	<div class="mt-4 flex flex-wrap items-center justify-between gap-2">
		<div class="flex flex-wrap items-center gap-2">
			<button type="button" class="btn-ghost" onclick={() => (selected = null)}>{$_('common.back')}</button>
			<button
				type="button"
				class="btn-danger"
				onclick={(event) => askRemove(item.lead, event)}
				disabled={deletingId !== null}
			>
				{deletingId === item.lead.id ? $_('inbox.deleting') : $_('inbox.delete')}
			</button>
		</div>
		<div class="flex items-center gap-2">
			<button type="button" class="btn-ghost" onclick={() => step(-1)} disabled={selectedIndex <= 0}>
				{$_('inbox.previous')}
			</button>
			{#if selectedIndex >= 0}
				<span class="text-xs tabular-nums text-stone-500">
					{$_('inbox.position', { values: { current: selectedIndex + 1, total: queue.length } })}
				</span>
			{/if}
			<button
				type="button"
				class="btn-ghost"
				onclick={() => step(1)}
				disabled={selectedIndex < 0 || selectedIndex >= queue.length - 1}
			>
				{$_('inbox.next')}
			</button>
		</div>
	</div>
	<div class="mt-3">
		{#key item.lead.id}
			<LeadDraft
				lead={item.lead}
				unseen={item.unseen}
				commentUrls={item.commentUrls}
				onComment={tabOnComment && tabLead?.id === item.lead.id}
				liveCommentUrl={tabLead?.id === item.lead.id ? tabCommentUrl : ''}
				onchange={applyLead}
				onseen={markSeen}
			/>
		{/key}
	</div>
{:else}
	<header class="mt-4">
		<div class="flex flex-wrap items-end justify-between gap-3">
			<div>
				<h1 class="text-2xl font-semibold tracking-tight text-stone-950">{$_('inbox.title')}</h1>
				<p class="mt-1 text-sm text-stone-500">{$_('inbox.lead')}</p>
			</div>
			{#if filter !== 'skipped'}
				<button type="button" class="btn" onclick={refresh} disabled={refreshing}>
					{#if refreshing}
						<span class="size-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>
						{$_('inbox.refreshing')}
					{:else}
						{$_('inbox.refresh')}
					{/if}
				</button>
			{/if}
		</div>
		<div class="mt-3 flex gap-1" role="tablist" aria-label={$_('inbox.filter')}>
			{#each filters as item (item.id)}
				<button
					type="button"
					role="tab"
					aria-selected={filter === item.id}
					class={[
						'rounded-lg px-2.5 py-1.5 text-sm font-medium',
						filter === item.id ? 'bg-teal-800 text-white' : 'bg-white text-stone-600 ring-1 ring-stone-200'
					]}
					onclick={() => chooseFilter(item.id)}
				>
					{$_(item.label)}
				</button>
			{/each}
		</div>
	</header>

	{#if message}
		<p class="banner mt-4 border-teal-200 bg-teal-50 text-teal-900"><CopyLine item={message} /></p>
	{/if}

	{#if !loaded}
		<p class="mt-6 text-sm text-stone-500">{$_('common.loading')}</p>
	{:else if activeItems.length === 0 && !listError}
		<p class="mt-6 rounded-2xl border border-dashed border-stone-300 bg-white/70 px-4 py-8 text-center text-sm text-stone-500">
			{filter === 'needs_reply' ? $_('inbox.empty') : filter === 'followups' ? $_('inbox.noReplies') : $_('inbox.noSkipped')}
		</p>
	{:else}
		{#each groups as group (group.platform_id)}
			<section class="mt-6">
				<div class="mb-3 flex items-baseline justify-between gap-3">
					<h2 class="text-sm font-semibold tracking-wide text-stone-500">{group.platform_name}</h2>
					<span class="text-xs tabular-nums text-stone-400">{group.items.length}</span>
				</div>
				<div class="grid gap-3">
					{#each group.items as lead (lead.id)}
						<article class={['card', filter === 'followups' && lead.unseen?.length ? 'border-l-4 border-l-amber-400' : '']}>
							<div class="flex flex-wrap items-center gap-2">
								<h3 class="min-w-0 text-base font-semibold tracking-tight text-stone-950">{lead.title || lead.url}</h3>
								{#if filter === 'needs_reply'}
									<span class="badge {statusTone(lead.status)}">{catalog('status', lead.status)}</span>
								{/if}
								{#if lead.unseen?.length}
									<span class="badge bg-amber-100 text-amber-900">{$_('inbox.updated')}</span>
								{/if}
							</div>
							{#if filter === 'followups' && lead.unseen?.length}
								<ul class="mt-3 space-y-2">
									{#each lead.unseen as event (event.id)}
										<li class="flex flex-wrap items-start gap-2 text-sm text-stone-700">
											<span class="badge {eventTone(event.kind)}">{catalog('event', event.kind)}</span>
											<span>{event.detail}</span>
										</li>
									{/each}
								</ul>
							{:else if lead.excerpt}
								<p class="mt-3 line-clamp-3 text-sm leading-6 text-stone-600">{lead.excerpt}</p>
							{/if}
							<div class="mt-4 flex flex-wrap items-center gap-2">
								<button type="button" class="btn" onclick={() => openWork(lead, targetFor(lead))}>
									{filter === 'followups'
										? $_('inbox.check')
										: filter === 'skipped'
											? $_('common.open')
											: lead.status === 'drafted'
												? $_('inbox.continue')
												: $_('inbox.write')}
								</button>
								<button
									type="button"
									class="btn-danger"
									onclick={(event) => askRemove(lead, event)}
									disabled={deletingId !== null}
								>
									{deletingId === lead.id ? $_('inbox.deleting') : $_('inbox.delete')}
								</button>
							</div>
						</article>
					{/each}
				</div>
			</section>
		{/each}
	{/if}
{/if}

<svelte:window onkeydown={onConfirmKey} />

{#if pendingDelete}
	{@const lead = pendingDelete}
	<button
		type="button"
		tabindex={-1}
		class="fixed inset-0 z-20 cursor-default bg-transparent"
		aria-label={$_('inbox.cancel')}
		onclick={dismissRemove}
	></button>
	<div
		{@attach placeDeletePopup}
		class="invisible fixed z-30 w-[min(18rem,calc(100vw-1rem))] rounded-2xl border border-stone-200 bg-white p-4 shadow-[0_12px_32px_rgba(28,25,23,0.16)]"
		role="dialog"
		tabindex="-1"
		aria-modal="true"
		aria-labelledby="delete-lead-title"
	>
		<h2 id="delete-lead-title" class="text-sm font-semibold tracking-tight text-stone-950">
			{$_('inbox.deleteConfirm')}
		</h2>
		<p class="mt-2 line-clamp-2 text-sm leading-6 break-all text-stone-600">{lead.title || lead.url}</p>
		<div class="mt-3 flex flex-wrap gap-2">
			<button type="button" class="btn-danger" onclick={removeLead} disabled={deletingId === lead.id}>
				{deletingId === lead.id ? $_('inbox.deleting') : $_('inbox.delete')}
			</button>
			<button type="button" class="btn-ghost" onclick={dismissRemove} disabled={deletingId === lead.id}>
				{$_('inbox.cancel')}
			</button>
		</div>
	</div>
{/if}
