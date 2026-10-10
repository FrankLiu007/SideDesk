export class DeskError extends Error {
	readonly key: string;

	constructor(key: string) {
		super(key);
		this.name = 'DeskError';
		this.key = key;
	}
}

export type CopyValues = Record<string, string | number>;

export type Copy = {
	key?: string;
	values?: CopyValues;
	text?: string;
	suffixKey?: string;
	suffixValues?: CopyValues;
};

export function keyed(key: string, values?: CopyValues): Copy {
	return { key, values };
}

export function fromReason(reason: unknown, fallbackKey: string): Copy {
	if (reason instanceof DeskError) return { key: reason.key };
	if (reason instanceof Error && reason.message) return { text: reason.message };
	return { key: fallbackKey };
}
