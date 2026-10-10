<script lang="ts">
	import { _ } from 'svelte-i18n';
	import { api } from '$lib/api';
	import CopyLine from '$lib/components/CopyLine.svelte';
	import ProjectForm from '$lib/components/ProjectForm.svelte';
	import { desk, refreshProjects } from '$lib/desk.svelte';
	import { fromReason, keyed, type Copy } from '$lib/i18n/copy';

	let newName = $state('');
	let notice = $state<Copy | null>(null);
	let error = $state<Copy | null>(null);
	let busy = $state(false);

	let current = $derived(desk.projects.find((item) => item.id === desk.activeId));

	async function create() {
		const next = newName.trim();
		if (!next) return;
		busy = true;
		error = null;
		notice = null;
		try {
			await api.createProject({ name: next });
			newName = '';
			await refreshProjects();
			notice = keyed('project.created');
		} catch (reason) {
			error = fromReason(reason, 'errors.create');
		} finally {
			busy = false;
		}
	}
</script>

<header>
	<h1 class="text-2xl font-semibold tracking-tight text-stone-950">{$_('project.title')}</h1>
	<p class="mt-1 text-sm leading-6 text-stone-500">{$_('project.lead')}</p>
</header>

{#if error}
	<p class="banner mt-4 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={error} /></p>
{/if}
{#if notice}
	<p class="banner mt-4 border-teal-200 bg-teal-50 text-teal-900"><CopyLine item={notice} /></p>
{/if}

{#if current}
	{#key current.id}
		<ProjectForm project={current} />
	{/key}
{/if}

<section class="card mt-4">
	<h2 class="text-base font-semibold text-stone-950">{$_('project.newTitle')}</h2>
	<p class="mt-1 text-sm text-stone-500">{$_('project.newHint')}</p>
	<label class="label mt-4" for="new-project">{$_('project.name')}</label>
	<input id="new-project" class="field mt-1.5" type="text" bind:value={newName} />
	<button type="button" class="btn mt-4" onclick={create} disabled={busy || !newName.trim()}
		>{$_('project.create')}</button
	>
</section>
