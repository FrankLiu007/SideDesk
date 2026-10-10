<script lang="ts">
	import { _ } from 'svelte-i18n';
	import { api, type Monitor, type Platform } from '$lib/api';
	import CopyLine from '$lib/components/CopyLine.svelte';
	import OnReady from '$lib/components/OnReady.svelte';
	import { desk } from '$lib/desk.svelte';
	import { fromReason, type Copy } from '$lib/i18n/copy';

	let monitors = $state<Monitor[]>([]);
	let platforms = $state<Platform[]>([]);
	let platformId = $state('reddit');
	let kind = $state('keyword');
	let content = $state('');
	let error = $state<Copy | null>(null);

	let searchable = $derived(platforms.filter((item) => item.can_search));
	let monitorGroups = $derived.by(() => {
		const groups: { id: string; name: string; items: Monitor[] }[] = [];
		for (const monitor of monitors) {
			let group = groups.find((item) => item.id === monitor.platform_id);
			if (!group) {
				group = { id: monitor.platform_id, name: monitor.platform_name, items: [] };
				groups.push(group);
			}
			group.items.push(monitor);
		}
		return groups;
	});

	async function load() {
		monitors = await api.monitors();
		platforms = await api.platforms();
		if (!searchable.some((item) => item.id === platformId)) platformId = searchable[0]?.id ?? 'reddit';
	}

	async function add() {
		error = null;
		try {
			if (kind === 'url') await api.createMonitor({ kind, content: content.trim() });
			else await api.createMonitor({ platform_id: platformId, kind, content: content.trim() });
			content = '';
			await load();
		} catch (reason) {
			error = fromReason(reason, 'errors.add');
		}
	}

	async function toggle(monitor: Monitor) {
		await api.patchMonitor(monitor.id, { enabled: !monitor.enabled });
		await load();
	}

	async function remove(id: number) {
		await api.deleteMonitor(id);
		await load();
	}
</script>

{#if desk.ready}
	{#key desk.token}
		<OnReady run={() => load().catch((reason: unknown) => (error = fromReason(reason, 'errors.request')))} />
	{/key}
{/if}

<header>
	<h1 class="text-3xl font-semibold tracking-tight text-stone-950">{$_('monitors.title')}</h1>
	<p class="mt-2 max-w-2xl text-sm leading-6 text-stone-500">{$_('monitors.lead')}</p>
</header>

{#if error}
	<p class="banner mt-5 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={error} /></p>
{/if}

<section class="card mt-6">
	<h2 class="text-base font-semibold text-stone-950">{$_('monitors.addTitle')}</h2>
	<div class="mt-4 grid gap-3 sm:grid-cols-2">
		<div>
			<label class="label" for="monitor-kind">{$_('monitors.kind')}</label>
			<select id="monitor-kind" class="field mt-1.5" bind:value={kind}>
				<option value="keyword">{$_('monitors.keyword')}</option>
				<option value="url">{$_('monitors.urlKind')}</option>
			</select>
		</div>
		{#if kind === 'keyword'}
			<div>
				<label class="label" for="monitor-platform">{$_('monitors.platform')}</label>
				<select id="monitor-platform" class="field mt-1.5" bind:value={platformId}>
					{#each searchable as item (item.id)}
						<option value={item.id}>{item.name}</option>
					{/each}
				</select>
			</div>
		{/if}
		<div class="sm:col-span-2">
			<label class="label" for="monitor-content"
				>{kind === 'keyword' ? $_('monitors.keyword') : $_('monitors.link')}</label
			>
			<input
				id="monitor-content"
				class="field mt-1.5"
				type="text"
				bind:value={content}
				placeholder={kind === 'keyword' ? $_('monitors.keywordPlaceholder') : $_('monitors.urlPlaceholder')}
			/>
			{#if kind === 'url'}
				<p class="mt-1.5 text-xs text-stone-500">{$_('monitors.urlHint')}</p>
			{/if}
		</div>
	</div>
	<button type="button" class="btn mt-4" onclick={add} disabled={!content.trim()}>{$_('monitors.add')}</button>
</section>

<section class="mt-6">
	<div class="mb-3 flex items-baseline justify-between">
		<h2 class="text-sm font-semibold tracking-wide text-stone-500">{$_('monitors.existing')}</h2>
		<span class="text-xs tabular-nums text-stone-400">{monitors.length}</span>
	</div>
	{#if monitors.length === 0}
		<p class="rounded-2xl border border-dashed border-stone-300 bg-white/70 px-4 py-8 text-center text-sm text-stone-500">
			{$_('monitors.empty')}
		</p>
	{:else}
		<div class="grid gap-6">
			{#each monitorGroups as group (group.id)}
				<section>
					<div class="mb-3 flex items-baseline justify-between gap-3">
						<h3 class="text-sm font-semibold tracking-wide text-stone-500">{group.name}</h3>
						<span class="text-xs tabular-nums text-stone-400">{group.items.length}</span>
					</div>
					<div class="grid gap-3">
						{#each group.items as monitor (monitor.id)}
							<article class="card">
								<div class="flex flex-wrap items-center gap-2">
									<span class="badge bg-stone-100 text-stone-700"
										>{monitor.kind === 'keyword' ? $_('monitors.keyword') : $_('monitors.watching')}</span
									>
									<span class={['badge', monitor.enabled ? 'bg-teal-100 text-teal-900' : 'bg-stone-100 text-stone-500']}>
										{monitor.enabled ? $_('monitors.on') : $_('monitors.off')}
									</span>
								</div>
								<p class="mt-3 text-sm leading-6 break-all text-stone-800">{monitor.content}</p>
								{#if monitor.last_error}
									<p class="banner mt-3 border-amber-200 bg-amber-50 text-amber-950">{monitor.last_error}</p>
								{/if}
								{#if monitor.last_run_at}
									<p class="mt-2 text-xs text-stone-500">
										{$_('monitors.lastRun', { values: { time: monitor.last_run_at } })}
									</p>
								{/if}
								<div class="mt-4 flex flex-wrap gap-2">
									<button type="button" class="btn-ghost" onclick={() => toggle(monitor)}>
										{monitor.enabled ? $_('monitors.turnOff') : $_('monitors.turnOn')}
									</button>
									<button type="button" class="btn-danger" onclick={() => remove(monitor.id)}>{$_('monitors.delete')}</button>
								</div>
							</article>
						{/each}
					</div>
				</section>
			{/each}
		</div>
	{/if}
</section>
