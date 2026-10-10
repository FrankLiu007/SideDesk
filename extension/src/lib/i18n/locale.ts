export const STORAGE_KEY = 'desk-language';

export type LocalePreference = 'system' | 'zh' | 'en';
export type AppLocale = 'zh' | 'en';

export function readPreference(): LocalePreference {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw === 'zh' || raw === 'en' || raw === 'system') return raw;
	} catch {
		/* private mode */
	}
	return 'system';
}

export function persistPreference(preference: LocalePreference) {
	try {
		localStorage.setItem(STORAGE_KEY, preference);
	} catch {
		/* private mode */
	}
}

export function systemLocale(): AppLocale {
	const lang = (navigator.language || 'en').toLowerCase();
	return lang.startsWith('zh') ? 'zh' : 'en';
}

export function resolveLocale(preference: LocalePreference): AppLocale {
	return preference === 'system' ? systemLocale() : preference;
}

export function htmlLang(locale: AppLocale) {
	return locale === 'zh' ? 'zh-CN' : 'en';
}
