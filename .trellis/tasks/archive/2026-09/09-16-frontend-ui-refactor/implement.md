# 实施计划

> 执行顺序：store → 视觉 token → 左栏 → 右栏 → Sender → 流式 → 切换会话 → 验证

---

## 前置

- [x] antd x 已装
- [x] 当前 8/8 测试通过，build 成功
- [x] 上一轮的 store panel 状态已就位（只需扩展）

---

## 步骤

### Step 1: Store 扩展（1 文件）

**文件**: `frontend/src/hooks/useAppStore.ts`

新增：

```ts
type Tab = { id: string; fileId: string; fileName: string; sheetName?: string; outputId?: string; openedAt: string };

// state
tabsBySession: Record<string, Tab[]>;
activeTabBySession: Record<string, string>;
streamingContent: string;

// actions
addTab(sessionId, tab): void;
removeTab(sessionId, tabId): void;
setActiveTab(sessionId, tabId): void;
appendStream(token): void;
finishStream(): void;
abortStream(): void;
```

`partialize` 增加 `tabsBySession` 和 `activeTabBySession`（其它不 persist）。

---

### Step 2: 视觉 token 替换（1 文件）

**文件**: `frontend/src/styles.css`

- 替换 `:root` 变量为新的浅色 token（见 design.md）
- 保留布局类（.workspace, .drag-handle 等）
- 新增：`.session-item-menu`、`.tab-bar`、`.tab-item`、`.empty-state`、`.user-footer`、`.new-task-btn`

---

### Step 3: 左栏改造（1-2 文件）

**文件**: `frontend/src/App.tsx`

- 顶部：`+ 新工作任务` 按钮（占满宽度，主色文字 + 浅色背景）
- 分组标题：`历史任务`
- 会话列表：用 antd x `Conversations`，但通过 `items` 传入 title/time 字段
  - 单行省略：title 用 CSS 处理
  - 三点菜单：用 antd `Dropdown` 包裹每个 item 渲染（Conversations 组件的 menu 不够灵活，考虑换实现）
  - 决定：保持 Conversations 组件，在 App 层用 `groupable` + `menu` props，或者放弃 Conversations 自己写一个简单列表
- 底部用户区：头像 + 用户名 + 设置图标

调研后决定：用 antd x `Conversations`，点三点弹出 `Dropdown`（rename / delete）。Rename 本轮不实现，菜单项作为 placeholder。

---

### Step 4: 右栏 TabBar（1-2 文件）

**文件**: `frontend/src/App.tsx`, `frontend/src/components/Previewer.tsx`

- 在 `Previewer` 外层包一个 TabBar
- TabBar：横向 flex 滚动，每个 tab 一个文件
- 内容区：根据 activeTab 渲染对应文件
- 无 tab 时：空状态（居中提示）
- 切换会话：监听 currentSessionId，从 `tabsBySession[currentSessionId]` 读取 tabs

---

### Step 5: Sender @ / 命令（1-2 文件）

**文件**: `frontend/src/App.tsx`, 新增 `frontend/src/components/SenderPopover.tsx`

- 监听 Sender `onChange`
- 检测光标前字符：
  - `@` → 弹文件列表 AutoComplete
  - `/` → 弹命令列表 Dropdown
- 选中后插入到光标处

简化：如果复杂，本轮只做 `/` 触发，@ 文件引用放到下一轮（暂存为 placeholder）。

---

### Step 6: 流式 + Stop 按钮（2-3 文件）

**文件**: `frontend/src/hooks/useAppStore.ts`, `frontend/src/App.tsx`, `backend/app/api/chat.py`

- store: streamingContent / appendStream / finishStream / abortStream
- Sender: `loading={isProcessing}`, `onSubmit={isProcessing ? abortStream : sendMessage}`，loading 态按钮文案变 "停止"
- DOM 稳定：每条 streaming message 用稳定 key，只更新 content 字符串
- 后端：可选地支持 abort，本轮可暂不实现（前端按钮停止只停止渲染）

---

### Step 7: 切换会话联动（store 已就位，1 文件）

**文件**: `frontend/src/hooks/useAppStore.ts` 中的 `selectSession`

- 切换时自动加载该 session 的 tabs（store 已按 sessionId 分组，直接 select）
- 切换时清空 streamingContent（防止旧 session 的流串到新 session）

---

### Step 8: 测试更新（1 文件）

**文件**: `frontend/src/__tests__/App.test.tsx`

- 更新现有测试以适应新组件结构
- 新增测试：
  - 新建会话显示空状态
  - 切换会话右栏 tab 切换
  - 关闭 tab
  - Sender loading 态按钮

---

### Step 9: 验证

```bash
cd frontend
npx tsc --noEmit
npm test -- --run
npm run build
```

预期：0 TS 错误，8+ 测试通过，build 成功。

---

## 回滚

```bash
git checkout -- frontend/src/
git checkout -- backend/app/api/chat.py
```