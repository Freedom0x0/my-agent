# 技术设计 — 办公 Agent 视觉与交互

> 延续 antd-x 组件化重构，本轮落实视觉基线、会话隔离、流式 stop、sender @/。

---

## 视觉 token（在 styles.css 里覆盖）

```css
:root {
  --color-bg: #fafaf9;            /* 主背景 */
  --color-surface: #ffffff;       /* 卡片/输入框 */
  --color-surface-hover: #f3f3f1; /* hover 态 */
  --color-surface-active: #ebebe8;/* 选中态（更深一点） */
  --color-border: #e5e5e2;        /* 1px 细边框 */
  --color-text: #1f2328;          /* 主文字 */
  --color-text-secondary: #6b7280;/* 次文字 */
  --color-accent: #2b4a8b;        /* 主色（克制使用） */
  --color-accent-soft: #eef2f7;   /* 主色浅背景 */
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --sider-width: 280px;
  --preview-width: 380px;
}
```

`XProvider` 的 `theme.token` 同步对齐这些变量。`borderRadius` 统一 8。

---

## 组件树（目标）

```
App (XProvider theme)
├── AppHeader (品牌 60px, 极简)
│
├── LeftSider (aside, 可折叠)
│   ├── NewTaskButton (顶部全宽按钮)
│   ├── GroupTitle ("历史任务")
│   ├── ConversationList (Conversations 组件 + 自定义 item render)
│   └── UserFooter (avatar + name + settings icon)
│
├── DragHandle (左, 6px, 拖拽改 siderWidth)
│
├── ChatSection (flex: 1)
│   ├── EmptyState (Welcome + Prompts) — 仅 messages 为空时
│   ├── MessageList (Bubble.List)
│   └── Sender (输入框, @ / commands, send/stop 切换)
│
├── DragHandle (右, 6px)
│
└── RightPreviewer (aside, 可折叠)
    ├── TabBar (横向滚动, close 按钮)
    └── TabContent (Previewer 组件, 单文件)
        └── EmptyState (无 tab 时)
```

---

## 数据模型变更（zustand store）

`useAppStore` 新增 / 调整：

```typescript
// 面板状态（已存在，本轮完善边界）
panel: {
  siderWidth, siderCollapsed,
  previewWidth, previewCollapsed,
}

// 会话级 tab 隔离
tabsBySession: Record<string, Tab[]>;       // persist
activeTabBySession: Record<string, string>; // persist
addTab(sessionId, tab): void;
removeTab(sessionId, tabId): void;
setActiveTab(sessionId, tabId): void;

// 流式输出
streamingContent: string;            // 当前流式文本（不持久化）
abortStream(): void;                  // 中止当前流（AbortController）

// session.files 也需要 persist，让 @ 文件引用刷新后可用
```

`Tab` 形状：

```typescript
type Tab = {
  id: string;          // 唯一 id (uuid 或 `${fileId}-${sheet}`)
  fileId: string;
  fileName: string;
  sheetName?: string;
  outputId?: string;   // 用于跳转到处理结果
  openedAt: string;    // ISO 时间戳，用于排序
};
```

---

## Sender 的 @ / 命令实现

**@ 文件引用**：

- 监听 Sender `onChange`，检测光标前的 `@` 触发字符
- 检测到时：在输入框上方弹出 Popover（`Mentions`/`AutoComplete`），列出当前 session 已上传文件
- 选中文件：插入 `@文件名 ` token 到输入框，光标后移
- 实现：用一个 `useState` 记录 `mentionState`，Sender `prefix` 属性支持 antd x 的 `Mention` 吗？
  - 调研结果：antd x `Sender` 暂不直接支持 mention，需要自己用 `onChange` + Popover 实现
  - 简化方案：监听 `@`，弹一个 antd `AutoComplete` 浮层

**/ 命令**：

- 同上：监听 `/`，弹出下拉命令列表
- 命令：`/clear`（清空当前 session 消息）、`/new`（新建会话并切换）
- 简化方案：监听 `/`，弹 antd `Dropdown` 或自定义 Popover

实现用一个独立的 `SenderPopover` 组件，统一处理 @ 和 / 的弹出。

---

## 流式输出 + Stop 按钮

### 后端（最小改动）

`backend/app/api/chat.py` 的 SSE 接口：
- 接受请求时创建 `asyncio.Task` 用于生成
- 提供 `/chat/abort` 接口（或在原 SSE 连接上发送一个 abort 消息）
- 客户端断开连接（`request.is_disconnected()`）时自动取消 task
- 简化方案：本轮不真做 abort，后端继续跑完，但前端给"停止"按钮立即停止渲染更多内容（用户体验上 OK）

### 前端 store

```typescript
streamingContent: string;  // 当前 streaming 文本
appendStream(token: string): void;  // 追加
finishStream(): void;     // 流结束，合并到 messages
abortStream(): void;      // 中止，调用 finishStream
```

### Sender 按钮切换

```tsx
<Sender
  submitType="enter"
  loading={status === "processing"}
  onSubmit={isProcessing ? abortStream : sendMessage}
  // Sender 本身没有内置 stop 按钮，用 onSubmit + loading 控制按钮文本
/>
```

查看 antd x Sender 是否有原生 stop 行为：API 里 `onSubmit` + `loading` 已经能展示不同状态。本轮实现：loading=true 时按钮文案变 "停止"。

### DOM 稳定

- 每条 streaming message 在 store 里只有一条记录
- `bubbleItems` 的 key 稳定（用 message.id）
- 流式过程只更新 `streamingContent` 字符串字段，React 只 diff 文本节点
- 验证方式：观察 dev tools，气泡容器 div 在流式过程中不重建

---

## 右栏 Tab 实现

- 不用 antd x 的 Tabs 组件（要支持自定义关闭按钮 + 横向滚动，antd Tabs 不够灵活）
- 自己写一个简单 TabBar：
  - 容器：`display: flex; overflow-x: auto; gap: 4px`
  - 每个 tab：`display: inline-flex; padding: 6px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-md); background: var(--color-surface);`
  - 激活态：`background: var(--color-surface-active); border-color: var(--color-text);`
  - 关闭按钮：右侧 16px icon，hover 变红
- 横向滚动：容器 overflow-x: auto，::-webkit-scrollbar 高度 6px

---

## 折叠 + 伸缩（已在上一轮实现，本轮完善边界）

- 折叠：panel.collapsed = true 时 aside `display: none`
- 拖拽：drag handle 在面板交界处，监听 mousedown → document mousemove/mouseup
- 边界：siderWidth ∈ [240, 480]，previewWidth ∈ [280, 720]
- 持久化：整个 panel 状态 + tabsBySession + activeTabBySession 都 persist

---

## 测试策略

- 现有测试 8/8 必须继续通过
- 本轮新增测试：
  - 新建会话后中间栏显示空状态
  - 切换会话后右栏 tab 切换
  - 关闭 tab 后 store 状态正确
  - 流式过程中只追加文本（手动验证或 mock）
- 不新增视觉回归测试（无 infra）

---

## 实施步骤概要

1. 后端：SSE 接口支持 abort（如果时间紧可跳过，仅前端切换按钮）
2. store：新增 tabsBySession、activeTabBySession、streamingContent、abortStream
3. styles.css：替换视觉 token（浅色 + 细边框 + 8px 圆角）
4. App.tsx：
   - 左栏：NewTaskButton + GroupTitle + ConversationList + UserFooter
   - 中间：Welcome + Prompts（已有）+ Sender（with @ /）
   - 右栏：TabBar + Previewer + EmptyState
5. SenderPopover 新组件（处理 @ / 触发）
6. 拖拽边界收紧（sider 240-480，preview 280-720）
7. 测试更新 + 验证