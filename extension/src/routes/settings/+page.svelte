<script lang="ts">
	import { _ } from 'svelte-i18n';
	import { onMount } from 'svelte';
	import { api, type AiSettings, type AiSource } from '$lib/api';
	import CopyLine from '$lib/components/CopyLine.svelte';
	import { applyPreference } from '$lib/i18n';
	import { fromReason, keyed, type Copy } from '$lib/i18n/copy';
	import { readPreference, type LocalePreference } from '$lib/i18n/locale';

	const DEEPSEEK_BASE = 'https://api.deepseek.com';
	const SEP = '\u001f';

	let sources = $state<AiSource[]>([]);
	let sourceId = $state<number | null>(null);
	let model = $state('');
	let configured = $state(false);
	let picked = $state('');
	let notice = $state<Copy | null>(null);
	let error = $state<Copy | null>(null);
	let pending = $state('');
	let language = $state<LocalePreference>(readPreference());

	let dialogEl = $state<HTMLDialogElement | null>(null);

	function rememberDialog(node: HTMLDialogElement) {
		dialogEl = node;
		return () => {
			if (dialogEl === node) dialogEl = null;
		};
	}
	let dialogMode = $state<'add' | 'edit'>('add');
	let editingId = $state<number | null>(null);
	let formName = $state('');
	let formBase = $state('');
	let formKey = $state('');
	let dialogError = $state<Copy | null>(null);

	let editing = $derived(sources.find((source) => source.id === editingId) ?? null);
	let grouped = $derived(
		sources
			.map((source) => ({ source, names: modelNames(source) }))
			.filter((item) => item.names.length > 0)
	);

	function modelNames(source: AiSource) {
		const names = [...source.models];
		if (source.id === sourceId && model && !names.includes(model)) names.unshift(model);
		return names;
	}

	function selectionKey(id: number, name: string) {
		return `${id}${SEP}${name}`;
	}

	function parseSelection(value: string) {
		const index = value.indexOf(SEP);
		if (index <= 0) return null;
		const id = Number(value.slice(0, index));
		const name = value.slice(index + SEP.length);
		if (!Number.isInteger(id) || id <= 0 || !name) return null;
		return { id, name };
	}

	function isDeepseek(url: string) {
		try {
			return new URL(url).hostname === 'api.deepseek.com';
		} catch {
			return false;
		}
	}

	function apply(row: AiSettings) {
		sources = row.sources;
		sourceId = row.source_id;
		model = row.model;
		configured = row.configured;
		picked = sourceId && model ? selectionKey(sourceId, model) : '';
	}

	async function load() {
		apply(await api.aiSettings());
	}

	onMount(() => {
		load().catch((reason: unknown) => (error = fromReason(reason, 'errors.request')));
	});

	function pickLanguage(next: LocalePreference) {
		language = next;
		applyPreference(next);
	}

	function openAdd() {
		dialogMode = 'add';
		editingId = null;
		formName = '';
		formBase = '';
		formKey = '';
		dialogError = null;
		dialogEl?.showModal();
	}

	function openEdit(source: AiSource) {
		dialogMode = 'edit';
		editingId = source.id;
		formName = source.name;
		formBase = source.base_url;
		formKey = '';
		dialogError = null;
		dialogEl?.showModal();
	}

	function useDeepseek() {
		const found = sources.find((source) => isDeepseek(source.base_url));
		if (found && found.id !== editingId) {
			dialogError = keyed('settings.deepseekExists');
			return;
		}
		dialogError = null;
		formName = 'DeepSeek';
		formBase = DEEPSEEK_BASE;
	}

	async function saveSelection() {
		const choice = parseSelection(picked);
		if (!choice) {
			error = keyed('settings.pickModel');
			return;
		}
		pending = 'select';
		error = null;
		notice = null;
		try {
			apply(await api.saveAiSelection({ source_id: choice.id, model: choice.name }));
			notice = keyed('settings.saved');
		} catch (reason) {
			error = fromReason(reason, 'errors.save');
		} finally {
			pending = '';
		}
	}

	async function loadModels(id: number) {
		pending = `models-${id}`;
		error = null;
		notice = null;
		try {
			const row = await api.aiSourceModels(id);
			apply(await api.aiSettings());
			notice = keyed('settings.modelsSaved', { count: row.models.length });
		} catch (reason) {
			error = fromReason(reason, 'errors.models');
		} finally {
			pending = '';
		}
	}

	async function testSource(id: number) {
		pending = `test-${id}`;
		error = null;
		notice = null;
		try {
			const row = await api.aiSourceTest(id);
			notice = row.reply
				? keyed('settings.connectedReply', { model: row.model, reply: row.reply })
				: keyed('settings.connected', { model: row.model });
		} catch (reason) {
			error = fromReason(reason, 'errors.connect');
		} finally {
			pending = '';
		}
	}

	async function removeSource(id: number) {
		if (!confirm($_('settings.deleteConfirm'))) return;
		pending = `delete-${id}`;
		error = null;
		notice = null;
		try {
			apply(await api.deleteAiSource(id));
			notice = keyed('settings.deleted');
		} catch (reason) {
			error = fromReason(reason, 'errors.delete');
		} finally {
			pending = '';
		}
	}

	async function submitDialog(event: SubmitEvent) {
		event.preventDefault();
		dialogError = null;
		pending = 'dialog';
		try {
			if (dialogMode === 'add') {
				apply(
					await api.createAiSource({
						name: formName.trim(),
						base_url: formBase.trim(),
						api_key: formKey.trim()
					})
				);
				notice = keyed('settings.added');
			} else if (editingId != null) {
				const body: { name: string; base_url: string; api_key?: string } = {
					name: formName.trim(),
					base_url: formBase.trim()
				};
				if (formKey.trim()) body.api_key = formKey.trim();
				apply(await api.updateAiSource(editingId, body));
				notice = keyed('settings.saved');
			}
			error = null;
			dialogEl?.close();
		} catch (reason) {
			dialogError = fromReason(reason, dialogMode === 'add' ? 'errors.add' : 'errors.save');
		} finally {
			pending = '';
		}
	}
</script>

<header>
	<h1 class="text-2xl font-semibold tracking-tight text-stone-950">{$_('settings.title')}</h1>
	<p class="mt-1 text-sm leading-6 text-stone-500">{$_('settings.lead')}</p>
</header>

{#if error}
	<p class="banner mt-4 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={error} /></p>
{/if}
{#if notice}
	<p class="banner mt-4 border-teal-200 bg-teal-50 text-teal-900"><CopyLine item={notice} /></p>
{/if}

<section class="card mt-4">
	<p class="label">{$_('language.title')}</p>
	<p class="mt-1 text-sm leading-6 text-stone-500">{$_('language.hint')}</p>
	<div class="mt-3 flex flex-wrap gap-2" role="group" aria-label={$_('language.title')}>
		<button
			type="button"
			class={language === 'system' ? 'btn' : 'btn-ghost'}
			aria-pressed={language === 'system'}
			onclick={() => pickLanguage('system')}
		>
			{$_('language.system')}
		</button>
		<button
			type="button"
			class={language === 'zh' ? 'btn' : 'btn-ghost'}
			aria-pressed={language === 'zh'}
			onclick={() => pickLanguage('zh')}
		>
			中文
		</button>
		<button
			type="button"
			class={language === 'en' ? 'btn' : 'btn-ghost'}
			aria-pressed={language === 'en'}
			onclick={() => pickLanguage('en')}
		>
			English
		</button>
	</div>
</section>

<section class="card mt-4">
	<h2 class="text-base font-semibold text-stone-950">{$_('settings.currentModel')}</h2>
	<p class="mt-1 text-sm leading-6 text-stone-500">{$_('settings.currentModelHint')}</p>
	{#if grouped.length}
		<select id="ai-model" class="field mt-3" bind:value={picked} aria-label={$_('settings.currentModel')}>
			{#if !picked}
				<option value="">{$_('settings.chooseModel')}</option>
			{/if}
			{#each grouped as item (item.source.id)}
				<optgroup label={item.source.name}>
					{#each item.names as name (name)}
						<option value={selectionKey(item.source.id, name)}>{name}</option>
					{/each}
				</optgroup>
			{/each}
		</select>
		<button type="button" class="btn mt-4" onclick={saveSelection} disabled={pending !== '' || !picked}>
			{pending === 'select' ? $_('settings.saving') : $_('settings.save')}
		</button>
	{:else}
		<p class="mt-3 text-sm leading-6 text-stone-500">{$_('settings.needSource')}</p>
	{/if}
	{#if configured}
		<p class="mt-3 text-sm text-stone-500">{$_('settings.ready')}</p>
	{/if}
</section>

<section class="card mt-4">
	<div class="flex items-center justify-between gap-3">
		<h2 class="text-base font-semibold text-stone-950">{$_('settings.sources')}</h2>
		<button type="button" class="btn" onclick={openAdd} disabled={pending !== ''}>{$_('settings.addSource')}</button>
	</div>
	{#if sources.length === 0}
		<p class="mt-3 text-sm leading-6 text-stone-500">{$_('settings.empty')}</p>
	{:else}
		<ul class="mt-2 divide-y divide-stone-200">
			{#each sources as source (source.id)}
				<li class="py-3">
					<div class="flex items-center gap-2">
						<p class="min-w-0 truncate text-sm font-medium text-stone-950">{source.name}</p>
						{#if source.id === sourceId}
							<span class="badge shrink-0 bg-teal-50 text-teal-800">{$_('settings.current')}</span>
						{/if}
					</div>
					<p class="mt-0.5 truncate text-sm text-stone-500">{source.base_url}</p>
					<p class="mt-1 text-xs text-stone-500">
						{source.key_hint
							? $_('settings.keyHint', { values: { hint: source.key_hint } })
							: $_('settings.noKey')}
						· {$_('settings.modelCount', { values: { count: source.models.length } })}
					</p>
					<div class="mt-2 flex flex-wrap gap-2">
						<button type="button" class="btn-ghost" onclick={() => loadModels(source.id)} disabled={pending !== ''}>
							{pending === `models-${source.id}` ? $_('settings.listing') : $_('settings.listModels')}
						</button>
						<button type="button" class="btn-ghost" onclick={() => testSource(source.id)} disabled={pending !== ''}>
							{pending === `test-${source.id}` ? $_('settings.testing') : $_('settings.test')}
						</button>
						<button type="button" class="btn-ghost" onclick={() => openEdit(source)} disabled={pending !== ''}>
							{$_('settings.edit')}
						</button>
						<button type="button" class="btn-danger" onclick={() => removeSource(source.id)} disabled={pending !== ''}>
							{pending === `delete-${source.id}` ? $_('settings.deleting') : $_('settings.delete')}
						</button>
					</div>
				</li>
			{/each}
		</ul>
	{/if}
</section>

<dialog
	{@attach rememberDialog}
	class="m-auto w-[min(28rem,calc(100%-1.5rem))] max-h-[calc(100%-1.5rem)] overflow-y-auto rounded-2xl border border-stone-200 bg-white p-5 text-stone-900 shadow-xl backdrop:bg-stone-950/40"
	aria-labelledby="source-dialog-title"
	onclose={() => (dialogError = null)}
>
	<form
		onsubmit={(event) => {
			event.preventDefault();
			void submitDialog(event);
		}}
	>
		<div class="flex items-start justify-between gap-3">
			<h2 id="source-dialog-title" class="text-base font-semibold text-stone-950">
				{dialogMode === 'add' ? $_('settings.addSource') : $_('settings.editSource')}
			</h2>
			<button type="button" class="btn-ghost" onclick={() => dialogEl?.close()} disabled={pending === 'dialog'}>
				{$_('settings.close')}
			</button>
		</div>
		{#if dialogError}
			<p class="banner mt-4 border-amber-200 bg-amber-50 text-amber-950"><CopyLine item={dialogError} /></p>
		{/if}
		<button type="button" class="btn-ghost mt-4" onclick={useDeepseek} disabled={pending === 'dialog'}>
			{$_('settings.deepseek')}
		</button>
		<p class="mt-3 text-sm leading-6 text-stone-500">
			{$_('settings.deepseekBefore')}<span class="text-stone-700">api.deepseek.com</span>{$_('settings.deepseekMiddle')}<a
				class="link"
				href="https://platform.deepseek.com/api_keys"
				target="_blank"
				rel="noreferrer">platform.deepseek.com</a
			>{$_('settings.deepseekAfter')}
		</p>
		<label class="label mt-4" for="source-name">{$_('settings.name')}</label>
		<input id="source-name" class="field mt-1.5" bind:value={formName} placeholder={$_('settings.namePlaceholder')} />
		<label class="label mt-4" for="source-base">{$_('settings.baseUrl')}</label>
		<input
			id="source-base"
			class="field mt-1.5"
			type="url"
			bind:value={formBase}
			placeholder="https://api.openai.com/v1"
		/>
		<label class="label mt-4" for="source-key">{$_('settings.key')}</label>
		<input
			id="source-key"
			class="field mt-1.5"
			type="password"
			bind:value={formKey}
			autocomplete="off"
			placeholder={editing?.key_hint
				? $_('settings.keySaved', { values: { hint: editing.key_hint } })
				: $_('settings.keyPlaceholder')}
		/>
		<div class="mt-4 flex flex-wrap justify-end gap-2">
			<button type="button" class="btn-ghost" onclick={() => dialogEl?.close()} disabled={pending === 'dialog'}>
				{$_('settings.cancel')}
			</button>
			<button type="submit" class="btn" disabled={pending === 'dialog'}>
				{#if pending === 'dialog'}
					{dialogMode === 'add' ? $_('settings.adding') : $_('settings.saving')}
				{:else}
					{dialogMode === 'add' ? $_('settings.add') : $_('settings.save')}
				{/if}
			</button>
		</div>
	</form>
</dialog>
