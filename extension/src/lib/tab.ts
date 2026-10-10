import { sameUrl } from '$lib/ui';

export type BrowserTab = {
	url: string;
	title: string;
};

function usable(url: string) {
	return Boolean(url) && !/^(chrome|chrome-extension|edge|about|devtools|view-source):/.test(url);
}

export function pageTitle(raw: string) {
	return raw
		.replace(/\s+:\s+r\/\S+$/, '')
		.replace(/\s+-\s+YouTube$/, '')
		.replace(/\s+-\s+哔哩哔哩$/, '')
		.trim();
}

export function postKey(url: string) {
	try {
		const parsed = new URL(url);
		const host = parsed.hostname.toLowerCase();
		const path = parsed.pathname;
		if (host.includes('reddit.com')) {
			const match = path.match(/\/comments\/([a-z0-9]+)/i);
			if (match) return `reddit:${match[1]}`;
		}
		if (host.includes('bilibili.com')) {
			const match = path.match(/BV[0-9A-Za-z]+/);
			if (match) return `bilibili:${match[0]}`;
		}
		if (host === 'youtube.com' || host === 'www.youtube.com' || host === 'm.youtube.com') {
			const video = parsed.searchParams.get('v');
			if (video) return `youtube:${video}`;
		}
		if (host === 'youtu.be') {
			const video = path.replace(/^\//, '').split('/')[0];
			if (video) return `youtube:${video}`;
		}
		if (host.includes('v2ex.com')) {
			const match = path.match(/\/t\/(\d+)/);
			if (match) return `v2ex:${match[1]}`;
		}
		if (host.includes('zhihu.com')) return `zhihu:${path}`;
		return `other:${url}`;
	} catch {
		return `other:${url}`;
	}
}

function extensionApi() {
	if (typeof chrome === 'undefined' || !chrome.tabs?.query || !chrome.windows?.getCurrent) return null;
	return chrome;
}

async function deskWindowId() {
	const browser = extensionApi();
	if (!browser) return undefined;
	const current = await browser.windows.getCurrent();
	if (!current.type || current.type === 'normal') return current.id;
	const normal = await browser.windows.getAll({ windowTypes: ['normal'] });
	return (normal.find((item) => item.focused) ?? normal[0])?.id;
}

async function currentBrowserTab() {
	const browser = extensionApi();
	const windowId = await deskWindowId();
	if (!browser || windowId == null) return null;
	const [tab] = await browser.tabs.query({ active: true, windowId });
	return tab ?? null;
}

export function watchTab(onTab: (tab: BrowserTab | 'preview' | null) => void) {
	const browser = extensionApi();
	if (!browser) {
		onTab('preview');
		return () => {};
	}

	let stopped = false;
	const pull = () => {
		void currentBrowserTab().then((tab) => {
			if (stopped) return;
			const url = tab?.url ?? '';
			if (!usable(url)) {
				onTab(null);
				return;
			}
			onTab({ url, title: tab?.title ?? '' });
		});
	};

	const onActivated = (info: chrome.tabs.OnActivatedInfo) => {
		void deskWindowId().then((windowId) => {
			if (info.windowId !== windowId) return;
			pull();
		});
	};
	const onUpdated = (_tabId: number, info: chrome.tabs.OnUpdatedInfo, tab: chrome.tabs.Tab) => {
		if (!info.url && info.status !== 'complete') return;
		void deskWindowId().then((windowId) => {
			if (tab.windowId !== windowId || !tab.active) return;
			pull();
		});
	};

	pull();
	browser.tabs.onActivated.addListener(onActivated);
	browser.tabs.onUpdated.addListener(onUpdated);
	return () => {
		stopped = true;
		browser.tabs.onActivated.removeListener(onActivated);
		browser.tabs.onUpdated.removeListener(onUpdated);
	};
}

export async function openInWindow(url: string) {
	const browser = extensionApi();
	if (!browser) {
		window.open(url, '_blank', 'noopener');
		return;
	}
	const windowId = await deskWindowId();
	if (windowId == null) {
		await browser.tabs.create({ url });
		return;
	}
	const tabs = await browser.tabs.query({ windowId });
	const key = postKey(url);
	const matches = tabs.filter((tab) => tab.id != null && tab.url && postKey(tab.url) === key);
	const existing = matches.find((tab) => tab.active) ?? matches[0];
	if (existing?.id != null) {
		if (existing.url && sameUrl(existing.url, url)) await browser.tabs.update(existing.id, { active: true });
		else await browser.tabs.update(existing.id, { url, active: true });
		return;
	}
	const active = tabs.find((tab) => tab.active && tab.id != null);
	if (active?.id != null) {
		await browser.tabs.update(active.id, { url });
		return;
	}
	await browser.tabs.create({ url, windowId });
}
