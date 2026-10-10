<script lang="ts">
	import '$lib/i18n';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { activateProject, desk, refreshProjects } from '$lib/desk.svelte';
	import '../app.css';

	let { children } = $props();

	const links = [
		{ href: '/', label: 'nav.inbox' },
		{ href: '/monitors', label: 'nav.monitors' },
		{ href: '/project', label: 'nav.project' },
		{ href: '/settings', label: 'nav.settings' }
	] as const;

	const titles: Record<string, string> = {
		'/': 'titles.inbox',
		'/monitors': 'titles.monitors',
		'/project': 'titles.project',
		'/settings': 'titles.settings'
	};

	onMount(() => {
		refreshProjects().catch(() => {});
	});

	// 哈希路由里，浏览器地址的 pathname 一直是 /，真正的页面在 hash 里。
	let path = $derived.by(() => {
		const fromHash = page.url.hash.replace(/^#/, '').split(/[?#]/)[0];
		const next = fromHash.startsWith('/') ? fromHash : page.url.pathname;
		if (next.length > 1 && next.endsWith('/')) return next.slice(0, -1);
		return next || '/';
	});
	let titleKey = $derived(titles[path] ?? 'brand.name');
</script>

<svelte:head>
	<title>{$_(titleKey)} · {$_('brand.name')}</title>
</svelte:head>

<div class="min-h-screen bg-paper">
	<header class="sticky top-0 z-10 border-b border-stone-800 bg-ink text-stone-100">
		<div class="flex items-center gap-2 px-3 py-2">
			<svg class="size-7 shrink-0" viewBox="14 18 100 92" aria-hidden="true">
				<rect width="66" height="92" rx="14" fill="#F6F3EE" />
				<rect x="12" y="22" width="42" height="8" rx="4" fill="#D6D3D1" />
				<rect x="12" y="38" width="30" height="8" rx="4" fill="#E7E5E4" />
				<rect x="12" y="54" width="36" height="8" rx="4" fill="#E7E5E4" />
				<rect x="72" width="28" height="92" rx="14" fill="#0D9488" />
				<circle cx="86" cy="22" r="6" fill="#F6F3EE" />
			</svg>
			<p class="min-w-0 flex-1 text-sm font-semibold tracking-tight">{$_('brand.name')}</p>
			{#if desk.projects.length}
				<label class="sr-only" for="active-project">{$_('nav.currentProject')}</label>
				<select
					id="active-project"
					class="max-w-36 rounded-lg border border-white/15 bg-white/10 px-2 py-1 text-xs text-white outline-none"
					value={desk.activeId}
					onchange={(event) => activateProject(Number(event.currentTarget.value))}
				>
					{#each desk.projects as project (project.id)}
						<option value={project.id}>{project.name}</option>
					{/each}
				</select>
			{/if}
		</div>
		<nav class="flex gap-1 overflow-x-auto px-2 pb-2" aria-label={$_('nav.label')}>
			{#each links as link (link.href)}
				{@const current = path === link.href}
				<a
					href={resolve(link.href)}
					aria-current={current ? 'page' : undefined}
					class={[
						'rounded-lg px-2.5 py-1.5 text-sm font-medium whitespace-nowrap',
						current ? 'bg-white/15 text-white' : 'text-stone-300 hover:bg-white/5 hover:text-white'
					]}
				>
					{$_(link.label)}
				</a>
			{/each}
		</nav>
	</header>
	<main class="px-3 py-4">
		{@render children()}
	</main>
</div>
