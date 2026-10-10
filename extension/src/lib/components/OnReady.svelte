<script lang="ts">
	import { onMount } from 'svelte';

	let { run }: { run: () => void } = $props();

	onMount(() => {
		run();
	});
</script>
