export function sameUrl(left: string, right: string) {
	return left.trim().replace(/\/+$/, '') === right.trim().replace(/\/+$/, '');
}

export function statusTone(status: string) {
	switch (status) {
		case 'unread':
			return 'bg-amber-100 text-amber-900';
		case 'drafted':
			return 'bg-sky-100 text-sky-900';
		case 'replied':
			return 'bg-teal-100 text-teal-900';
		default:
			return 'bg-stone-100 text-stone-600';
	}
}

export function eventTone(kind: string) {
	switch (kind) {
		case 'new_child':
			return 'bg-amber-100 text-amber-900';
		case 'score_change':
			return 'bg-sky-100 text-sky-900';
		case 'deleted':
			return 'bg-rose-100 text-rose-800';
		default:
			return 'bg-stone-100 text-stone-600';
	}
}
