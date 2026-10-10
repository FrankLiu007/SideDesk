import type { Reroute } from '@sveltejs/kit';

const retired = new Set(['/today', '/leads', '/replies']);

export const reroute: Reroute = ({ url }) => {
	if (retired.has(url.pathname)) return '/';
};
