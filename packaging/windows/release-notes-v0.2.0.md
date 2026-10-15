# AI Translator v0.2.0

Windows 全局热键与体验修复版本。

## 新增

- **Windows 全局热键**：设置 → 外观与快捷键 → 「全局呼出」，系统级生效（任意程序前台时均可呼出窗口），默认 `Ctrl+Alt+T`，可自定义（支持 字母/数字/F1–F24 + 修饰键组合）；注册成败有托盘气泡提示，快捷键被占用时自动降级
- **自定义场景预设**：内置场景之外可自行添加、编辑翻译场景
- **TaskRunner**：统一后台任务管理，忙碌状态更稳定

## 修复

- **Windows 单实例唤起失效**：Windows 命名管道下 `QLocalSocket` 缓冲区不会同步刷出，二次启动的唤起命令被丢弃；现在保活连接并等待完整写出，双击图标即可正常唤起已运行的实例
- **热键过滤器空指针崩溃**：修复 Windows 上测试触发的 access violation（Linux CI 不复现）
- 修复 Windows 打包脚本读取版本号失败的问题（pyproject 动态版本）

## 说明

- 应用内快捷键（如 `Ctrl+Return` 翻译）仅在窗口聚焦时生效，这是跨平台 Qt 的标准行为
- Linux 上全局呼出建议继续使用合成器 keybind（niri/hyprland `bind` → 启动命令，单实例 IPC 会自动唤起已有窗口）

**下载**：`ai-translator-setup-0.2.0.exe`（Windows 安装包，64 位）
