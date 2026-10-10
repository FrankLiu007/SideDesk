import { browser } from '$app/environment';
import { addMessages, init, locale } from 'svelte-i18n';
import en from './locales/en.json';
import zh from './locales/zh.json';
import { htmlLang, persistPreference, readPreference, resolveLocale, type LocalePreference } from './locale';

addMessages('en', en);
addMessages('zh', zh);

const starting = resolveLocale(browser ? readPreference() : 'en');

init({
	fallbackLocale: 'en',
	initialLocale: starting
});

if (browser) document.documentElement.lang = htmlLang(starting);

export function applyPreference(preference: LocalePreference) {
	const next = resolveLocale(preference);
	persistPreference(preference);
	locale.set(next);
	if (browser) document.documentElement.lang = htmlLang(next);
}
