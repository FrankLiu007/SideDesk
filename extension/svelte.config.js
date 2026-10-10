import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			pages: 'dist',
			assets: 'dist',
			fallback: 'index.html'
		}),
		// Chrome 拒绝加载文件名以 "_" 开头的扩展资源，不能用默认目录 _app。
		appDir: 'app',
		router: {
			type: 'hash',
			resolution: 'client'
		},
		paths: {
			relative: true
		}
	}
};

export default config;
