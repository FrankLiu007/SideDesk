# SideDesk

本地用的跟进台。每天看两类东西：新出现的问题，以及你已经发出去的回复下面有没有人接话。

回复还是你自己到 Reddit、B 站、YouTube、V2EX、知乎去发。SideDesk 不代发。

这个台子是在推广 ThinkNote 时想到的。它不绑定任何产品，项目、背景和监控都由你自己填。

## 环境

- Python 3.12
- pnpm
- Chrome

## 运行

后端一键启动（没有虚拟环境或依赖时会先装好，没有 `.env` 时会从 `.env.example` 复制一份，然后监听 http://127.0.0.1:8765 ）：

```bash
cd backend
./start-backend.sh
```

第一次启动会建一个空的「默认」项目。线索和监控从界面里加。

界面在扩展里。先装依赖并打一次包：

```bash
cd extension
pnpm install
pnpm build
```

在 Chrome 打开 `chrome://extensions`，打开开发者模式，加载已解压的扩展程序，选 `extension/dist`。点插件图标，侧边栏在窗口右边。打开就是待办；点一条后，左边是原帖，右边做这一条。顶上可以进监控。后端没开时侧边栏会提示先跑 `./start-backend.sh`。

开发时可以预览同一份扩展页面，这不是另一套产品：

```bash
cd extension
pnpm dev
```

打开 http://127.0.0.1:5175 。预览读不到当前标签。装进 Chrome 之后，顶上会认左边的页面；正在改的稿不会因为换标签被换掉。

## 配置

把 `.env.example` 复制成 `.env`。

Reddit 搜索和评论刷新需要密钥。填上 [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) 里 script 应用的 client id、secret，以及你的用户名。不填也能记线索、贴评论链接；只是不能自动搜，也不能自动看 Reddit 评论下面的新回复。

每天 8 点（`Asia/Shanghai`，可用 `DESK_REFRESH_HOUR` 改）会跑一次。页面上的「立即刷新」是同一次检查。

`SEED_PATH` 可以指向一份 Markdown。库里还没有线索时，启动会导入一次。不设就跳过。

YouTube、哔哩哔哩可以先把视频链接加进监控源。链接会保存，评论拉取还没接。

## 测试

```bash
cd backend
../.venv/bin/python -m pytest
```

## 目录

- `backend/`：本地 API 和数据库
- `extension/`：Chrome 侧边栏
- `data/`：SQLite，不进仓库
- `.env`：密钥，不进仓库
