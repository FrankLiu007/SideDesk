<script lang="ts">
	import { untrack } from 'svelte';
	import { _ } from 'svelte-i18n';
	import { api, type Project } from '$lib/api';
	import CopyLine from '$lib/components/CopyLine.svelte';
	import { refreshProjects } from '$lib/desk.svelte';
	import { fromReason, keyed, type Copy } from '$lib/i18n/copy';

	let { project }: { project: Project } = $props();

	let name = $state(untrack(() => project.name));
	let background = $state(untrack(() => project.background));
	let followZh = $state(untrack(() => project.followup_zh));
	let followEn = $state(untrack(() => project.followup_en));
	let notice = $state<Copy | null>(null);
	let error = $state<Copy | null>(null);
	let busy = $state(false);

	async function save() {
		busy = true;
		error = null;
		notice = null;
		try {
			await api.updateProject(project.id, {
				name: name.trim(),
				background,
				followup_zh: followZh,
				followup_en: followEn
			});
			await refreshProjects();
			notice = keyed('project.saved');
		} catch (reason) {
			error = fromReason(reason, 'errors.save');
		} finally {
			busy = false;
		}
	}
</script>

<section class="card mt-4">
	{#if error}
		<p class="banner mb-4 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={error} /></p>
	{/if}
	{#if notice}
		<p class="banner mb-4 border-teal-200 bg-teal-50 text-teal-900"><CopyLine item={notice} /></p>
	{/if}
	<label class="label" for="project-name">{$_('project.name')}</label>
	<input id="project-name" class="field mt-1.5" type="text" bind:value={name} />
	<label class="label mt-4" for="project-background">{$_('project.background')}</label>
	<textarea id="project-background" class="field mt-1.5 min-h-56 resize-y leading-6" bind:value={background}></textarea>
	<label class="label mt-4" for="follow-zh">{$_('project.followZh')}</label>
	<textarea id="follow-zh" class="field mt-1.5 min-h-20 resize-y leading-6" bind:value={followZh}></textarea>
	<p class="mt-1 text-xs text-stone-500">{$_('project.followEmpty')}</p>
	<label class="label mt-4" for="follow-en">{$_('project.followEn')}</label>
	<textarea id="follow-en" class="field mt-1.5 min-h-20 resize-y leading-6" bind:value={followEn}></textarea>
	<button type="button" class="btn mt-4" onclick={save} disabled={busy || !name.trim()}>{$_('project.save')}</button>
</section>
