<script lang="ts">
	import { _ } from 'svelte-i18n';
	import type { Copy } from '$lib/i18n/copy';

	let { item }: { item: Copy } = $props();
</script>

{#if item.text}{item.text}{:else if item.key}{$_(item.key, { values: item.values })}{/if}{#if item.suffixKey}{$_(item.suffixKey, { values: item.suffixValues })}{/if}
