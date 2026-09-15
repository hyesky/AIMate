package main

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

// App struct — AIMate 桌面壳应用
type App struct {
	ctx      context.Context
	console  *exec.Cmd // AIMate Python console 子进程
	port     int
	readyURL string
}

// NewApp creates a new App application struct
func NewApp() *App {
	return &App{port: 8905, readyURL: "http://127.0.0.1:8905/"}
}

// startup is called when the app starts — 后台拉起 AIMate console 服务。
func (a *App) startup(ctx context.Context) {
	a.ctx = ctx
	go func() {
		_, _ = a.StartConsole()
	}()
}

// shutdown is called when the app is closing — 回收 AIMate console 子进程。
func (a *App) shutdown(ctx context.Context) {
	a.StopConsole()
}

// StartConsole 启动 AIMate 的 Python console 服务（后台子进程）。
// 用内网 LLM 网关配置；安排在本机 Python 环境跑。
func (a *App) StartConsole() (string, error) {
	if a.console != nil && a.console.Process != nil {
		return "already running", nil
	}
	// 定位 AIMate 项目根：优先环境变量，其次当前目录的父目录
	proj := os.Getenv("AIMATE_PROJECT")
	if proj == "" {
		wd, _ := os.Getwd()
		proj = wd
	}
	py := os.Getenv("AIMATE_PYTHON")
	if py == "" {
		py = "python3"
	}
	args := []string{
		"-m", "aimate.cli", "console",
		"--port", fmt.Sprintf("%d", a.port),
		"--llm-config", "configs/llm.gateway.json",
	}
	cmd := exec.Command(py, args...)
	cmd.Dir = proj
	cmd.Env = append(os.Environ(), "PYTHONPATH="+proj)
	// 输出丢弃（可改为写日志文件便于排查）
	cmd.Stdout = os.Stderr
	cmd.Stderr = os.Stderr
	if err := cmd.Start(); err != nil {
		return "", fmt.Errorf("启动 AIMate console 失败: %w", err)
	}
	a.console = cmd
	return a.readyURL, nil
}

// ConsoleURL 返回 AIMate Web UI 的地址（供前端 iframe 加载）。
func (a *App) ConsoleURL() string {
	return a.readyURL
}

// StopConsole 停止 AIMate console 子进程。
func (a *App) StopConsole() string {
	if a.console == nil || a.console.Process == nil {
		return "not running"
	}
	proc := a.console.Process
	_ = proc.Kill()
	_, _ = a.console.Process.Wait()
	a.console = nil
	return "stopped"
}

// Greet kept for template compatibility.
func (a *App) Greet(name string) string {
	return fmt.Sprintf("Hello %s, It's show time!", strings.TrimSpace(name))
}
