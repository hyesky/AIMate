# README

## About

This is the official Wails Vanilla template.

You can configure the project by editing `wails.json`. More information about the project settings can be found
here: https://wails.io/docs/reference/project-config

## Live Development

To run in live development mode, run `wails dev` in the project directory. This will run a Vite development
server that will provide very fast hot reload of your frontend changes. If you want to develop in a browser
and have access to your Go methods, there is also a dev server that runs on http://localhost:34115. Connect
to this in your browser, and you can call your Go code from devtools.

## Building

To build a redistributable, production mode package, use `wails build`.

## Windows 交叉编译（在 macOS 上打 Windows 包）

前置：`wails` CLI（`~/go/bin/wails`）、前端依赖、`makensis`（NSIS 安装器，`brew install makensis`）。

```sh
cd packaging/aimate
export PATH=$PATH:$HOME/go/bin
# 裸可执行（无 CGO；Wails v2 用 WebView2Loader 纯 Go，可跨 OS 编译）
wails build -platform windows/amd64 -skipbindings
# 或带 NSIS 安装器
wails build -platform windows/amd64 -skipbindings -nsis
```

产物：`build/bin/aimate.exe`（裸可执行）、`build/bin/aimate-amd64-installer.exe`（NSIS 安装器）。
`build/bin/` 已在 `.gitignore`，不提交二进制。
