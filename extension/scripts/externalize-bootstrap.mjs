import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';

const htmlPath = new URL('../dist/index.html', import.meta.url);
const jsPath = new URL('../dist/bootstrap.js', import.meta.url);
const html = readFileSync(htmlPath, 'utf8');
const match = html.match(/<script>\s*([\s\S]*?)\s*<\/script>/);
if (!match) throw new Error('找不到侧边栏启动脚本');

const root = (value) => value.replaceAll('"/app/', '"./app/');
writeFileSync(jsPath, root(match[1]));
writeFileSync(htmlPath, root(html).replace(root(match[0]), '<script src="./bootstrap.js"></script>'));

// 旧构建留下的 _app 仍会让 Chrome 拒绝加载整个扩展目录。
const staleAppDir = new URL('../dist/_app', import.meta.url);
if (existsSync(staleAppDir)) rmSync(staleAppDir, { recursive: true, force: true });
