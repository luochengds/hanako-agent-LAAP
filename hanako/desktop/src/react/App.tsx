/**
 * App.tsx — React 根组件（纯布局编排）
 *
 * 初始化逻辑在 app-init.ts，拖拽/主内容区在 MainContent.tsx。
 * 此文件只负责 titlebar + sidebar + 主区域 + overlays 的组装。
 */

import { useEffect, lazy, useState, Suspense } from 'react';
import { useStore } from './stores';
import type { ActivePanel } from './types';
import { ErrorBoundary } from './components/ErrorBoundary';
import { RegionalErrorBoundary } from './components/RegionalErrorBoundary';

const SkillViewerOverlay = lazy(() => import('./components/SkillViewerOverlay').then(m => ({ default: m.SkillViewerOverlay })));
// P2-bubble-field: 意识海洋 overlay（lazy，仅 activePanel === 'bubble-field' 时渲染）
const BubbleField = lazy(() => import('../../../plugins/bubble-field/BubbleField').then(m => ({ default: m.BubbleField })));
// P2-birth-ceremony: 诞生仪式 overlay（lazy，仅 activePanel === 'birth-ceremony' 时渲染）
const CeremonyWizard = lazy(() => import('../../../plugins/birth-ceremony/CeremonyWizard').then(m => ({ default: m.CeremonyWizard })));
// P2-skill-packs: 技能包管理 overlay（lazy，仅 activePanel === 'skill-packs' 时渲染）
const SkillPacksPanel = lazy(() => import('../../../plugins/skill-packs/SkillPacksPanel').then(m => ({ default: m.SkillPacksPanel })));
// P2-hot-compile-preview: 组件热编译预览 overlay（lazy，仅 activePanel === 'hot-compile-preview' 时渲染）
const HotCompilePanel = lazy(() => import('../../../plugins/hot-compile-preview/HotCompilePanel').then(m => ({ default: m.HotCompilePanel })));
// P3-1v1-protocol: LAAPer 间 1v1 对话 overlay（lazy，仅 activePanel === 'laaper-chat' 时渲染）
const LaaperChatPanel = lazy(() => import('../../../plugins/laaper-chat/LaaperChatPanel').then(m => ({ default: m.LaaperChatPanel })));
// P3-trio-chatroom: 三人聊天室 overlay（lazy，仅 activePanel === 'trio-chatroom' 时渲染）
const TrioChatPanel = lazy(() => import('../../../plugins/trio-chatroom/TrioChatPanel').then(m => ({ default: m.TrioChatPanel })));
// P4-charter-guardian: 宪章守护者治理面板 overlay（lazy，仅 activePanel === 'charter-guardian' 时渲染）
const CharterGuardianPanel = lazy(() => import('../../../plugins/charter-guardian/GuardianPanel').then(m => ({ default: m.GuardianPanel })));
// P5-laaper-market: LAAPer 市场 overlay（lazy，仅 activePanel === 'laaper-market' 时渲染）
const MarketBrowser = lazy(() => import('../../../plugins/laaper-market/MarketBrowser').then(m => ({ default: m.MarketBrowser })));
import { ChannelsPanel } from './components/ChannelsPanel';
import { ChannelCreateOverlay } from './components/channels/ChannelCreateOverlay';
import { SidebarLayout, toggleSidebar } from './components/SidebarLayout';
import { FloatSidebar, useFloatSidebar } from './components/FloatSidebar';
import { useSidebarResize } from './hooks/use-sidebar-resize';
import { createNewSession } from './stores/session-actions';
import { toggleJianSidebar } from './stores/desk-actions';
import { ToastContainer } from './components/ToastContainer';
import { InputContextMenu } from './components/InputContextMenu';
import { StatusBar } from './components/StatusBar';
import { LeavesOverlay } from './components/LeavesOverlay';
import { SelectionQuoteActionSurface } from './components/selection/SelectionQuoteActionSurface';
import { MediaViewer } from './components/shared/MediaViewer/MediaViewer';
import { SettingsModalShell } from './components/SettingsModalShell';
import { initTheme, initDragPrevention } from './bootstrap';
import { initApp } from './app-init';
import { openSettingsModal } from './stores/settings-modal-actions';
import { AppTitlebar } from './components/app/AppTitlebar';
import { ChatSidebar } from './components/app/ChatSidebar';
import { AppPages } from './components/app/AppPages';

declare function t(key: string, vars?: Record<string, string | number>): string;

// ── 主题 + drag 阻止（import 时立即执行） ──
initTheme();
initDragPrevention();

// ── 面板切换 ──

function togglePanel(panel: ActivePanel) {
  const s = useStore.getState();
  s.setActivePanel(s.activePanel === panel ? null : panel);
}

function ConnectionStatus() {
  const connected = useStore(s => s.connected);
  const statusKey = useStore(s => s.statusKey);
  const statusVars = useStore(s => s.statusVars);
  return (
    <div className={`connection-status${connected ? ' connected' : ''}`}>
      <span className="status-dot"></span>
      <span className="status-text">{statusKey ? t(statusKey, statusVars) : ''}</span>
    </div>
  );
}

// ── App 根组件 ──

function App() {
  useSidebarResize();
  // 订阅 locale 变化，驱动整棵树重渲染
  useStore(s => s.locale);
  const sidebarOpen = useStore(s => s.sidebarOpen);
  const jianOpen = useStore(s => s.jianOpen);
  const currentTab = useStore(s => s.currentTab);
  const isPluginTab = typeof currentTab === 'string' && currentTab.startsWith('plugin:');
  const bubbleFieldOpen = useStore(s => s.activePanel === 'bubble-field');
  const birthCeremonyOpen = useStore(s => s.activePanel === 'birth-ceremony');
  const skillPacksOpen = useStore(s => s.activePanel === 'skill-packs');
  const hotCompileOpen = useStore(s => s.activePanel === 'hot-compile-preview');
  const laaperChatOpen = useStore(s => s.activePanel === 'laaper-chat');
  const laaperChatPeer = useStore(s => s.laaperChatPeer);
  const trioChatOpen = useStore(s => s.activePanel === 'trio-chatroom');
  const trioChatMembers = useStore(s => s.trioChatMembers);
  const charterGuardianOpen = useStore(s => s.activePanel === 'charter-guardian');
  const laaperMarketOpen = useStore(s => s.activePanel === 'laaper-market');
  const agentName = useStore(s => s.agentName);
  const [selfPublicKey, setSelfPublicKey] = useState('');
  const { side: floatSide, show: showFloat, scheduleHide: scheduleFloatHide, cancelHide: cancelFloatHide, hide: hideFloat } = useFloatSidebar();

  // P3-1v1-protocol / P3-trio-chatroom / P4-charter-guardian: 面板打开时拉取本机 LAAPer 公钥（sidecar /agents/online）
  useEffect(() => {
    if (!(laaperChatOpen || trioChatOpen || charterGuardianOpen) || selfPublicKey) return;
    let cancelled = false;
    fetch('http://127.0.0.1:11521/agents/online')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data?.agents) return;
        const self = data.agents.find(
          (a: { name?: string; public_key?: string }) =>
            a.name === agentName && a.public_key,
        );
        if (self) setSelfPublicKey(self.public_key);
      })
      .catch(() => { /* sidecar 未启动时静默 */ });
    return () => { cancelled = true; };
  }, [laaperChatOpen, trioChatOpen, charterGuardianOpen, selfPublicKey, agentName]);

  useEffect(() => {
    console.info('[hana-launch] init-start');
    initApp()
      .then(() => {
        console.info('[hana-launch] init-finished');
      })
      .catch((err: unknown) => {
        console.error('[init] 初始化异常:', err);
        console.error('[hana-launch] init-failed', err);
        console.info('[hana-launch] app-ready', JSON.stringify({ reason: 'init-failed' }));
        window.platform?.appReady?.();
      });
  }, []);

  return (
    <ErrorBoundary>
      {/* Headless behavior components */}
      <SidebarLayout />
      <ChannelsPanel />

      {/* ── App shell: titlebar 作为独立布局行（flex column 第一行），
           app body 占剩余高度。取代旧的 fixed overlay + 各内容区 padding-top 避让。 ── */}
      <div className="app-shell">
        {/* ── Titlebar ── */}
        <AppTitlebar
          sidebarOpen={sidebarOpen}
          jianOpen={jianOpen}
          onToggleSidebar={() => { hideFloat(); toggleSidebar(); }}
          onToggleJian={() => { hideFloat(); toggleJianSidebar(); }}
          onLeftMouseEnter={() => showFloat('left')}
          onRightMouseEnter={() => showFloat('right')}
          onToggleMouseLeave={scheduleFloatHide}
        />

        {/* ── App body ── */}
        <div className="app">
          <ChatSidebar
            open={sidebarOpen && !isPluginTab}
            onNewSession={createNewSession}
            onCollapse={() => toggleSidebar()}
            onOpenSettings={() => openSettingsModal()}
            onTogglePanel={togglePanel}
          />

          <RegionalErrorBoundary region="app-pages" resetKeys={[currentTab]}>
            <AppPages />
          </RegionalErrorBoundary>
        </div>
      </div>

      {/* Connection status */}
      <ConnectionStatus />

      {/* Channel create overlay */}
      <ChannelCreateOverlay />

      {/* Skill viewer overlay */}
      <Suspense fallback={null}><SkillViewerOverlay /></Suspense>

      {/* Float sidebar */}
      <FloatSidebar
        side={floatSide}
        onMouseEnter={cancelFloatHide}
        onMouseLeave={scheduleFloatHide}
        onAction={hideFloat}
      />

      {/* Connection status bar */}
      <StatusBar />

      {/* Leaves shadow overlay */}
      <LeavesOverlay />

      {/* Media viewer overlay */}
      <MediaViewer />

      {/* P2-bubble-field: 意识海洋 overlay（可选，默认不显示） */}
      {bubbleFieldOpen && (
        <Suspense fallback={null}>
          <BubbleField
            onClose={() => useStore.getState().setActivePanel(null)}
            onSelectBubble={(agent) => {
              useStore.getState().setLaaperChatPeer({
                public_key: agent.public_key,
                name: agent.name,
                color: agent.color,
              });
              useStore.getState().setActivePanel('laaper-chat');
            }}
            onCreateChatroom={(agents) => {
              // P3-trio-chatroom: 拖拽叠加创建多人聊天室
              // 取前 3 个成员（spec 硬约束为三人聊天室），不足 2 人时不触发
              const selected = agents.slice(0, 3);
              if (selected.length < 2) return;
              useStore.getState().setTrioChatMembers(
                selected.map((a) => ({
                  public_key: a.public_key,
                  name: a.name,
                  color: a.color,
                })),
              );
              useStore.getState().setActivePanel('trio-chatroom');
            }}
          />
        </Suspense>
      )}

      {/* P2-birth-ceremony: 诞生仪式 overlay
          - 完成后 onComplete 调用 setActivePanel('bubble-field') 切到意识海洋
          - 取消则 setActivePanel(null) 关闭 */}
      {birthCeremonyOpen && (
        <Suspense fallback={null}>
          <CeremonyWizard
            onComplete={() => useStore.getState().setActivePanel('bubble-field')}
            onCancel={() => useStore.getState().setActivePanel(null)}
          />
        </Suspense>
      )}

      {/* P2-skill-packs: 技能包管理 overlay */}
      {skillPacksOpen && (
        <Suspense fallback={null}>
          <SkillPacksPanel onClose={() => useStore.getState().setActivePanel(null)} />
        </Suspense>
      )}

      {/* P2-hot-compile-preview: 组件热编译预览 overlay */}
      {hotCompileOpen && (
        <Suspense fallback={null}>
          <HotCompilePanel onClose={() => useStore.getState().setActivePanel(null)} />
        </Suspense>
      )}

      {/* P3-1v1-protocol: LAAPer 间 1v1 对话 overlay
          - peer 来自 BubbleField onSelectBubble 存入 store
          - selfPublicKey 从 sidecar /agents/online 拉取
          - 关闭后清空 peer 防止下次误用 */}
      {laaperChatOpen && laaperChatPeer && (
        <Suspense fallback={null}>
          <LaaperChatPanel
            peer={laaperChatPeer}
            selfPublicKey={selfPublicKey}
            selfName={agentName || ''}
            onClose={() => {
              useStore.getState().setLaaperChatPeer(null);
              useStore.getState().setActivePanel(null);
            }}
          />
        </Suspense>
      )}

      {/* P3-trio-chatroom: 三人聊天室 overlay
          - members 来自 BubbleField onCreateChatroom（拖拽叠加）存入 store
          - selfPublicKey 从 sidecar /agents/online 拉取
          - 关闭后清空 members 防止下次误用 */}
      {trioChatOpen && trioChatMembers && trioChatMembers.length >= 2 && (
        <Suspense fallback={null}>
          <TrioChatPanel
            members={trioChatMembers}
            selfPublicKey={selfPublicKey}
            selfName={agentName || ''}
            onClose={() => {
              useStore.getState().setTrioChatMembers(null);
              useStore.getState().setActivePanel(null);
            }}
          />
        </Suspense>
      )}

      {/* P4-charter-guardian: 宪章守护者治理面板 overlay
          - selfPublicKey 从 sidecar /agents/online 拉取（与 laaper-chat 共享）
          - 行使记录写入 WitnessTrail（链式 hash + 可选 Ed25519 签名）
          - 关闭后 setActivePanel(null) */}
      {charterGuardianOpen && (
        <Suspense fallback={null}>
          <CharterGuardianPanel
            selfPublicKey={selfPublicKey}
            selfName={agentName || ''}
            onClose={() => useStore.getState().setActivePanel(null)}
          />
        </Suspense>
      )}

      {/* P5-laaper-market: LAAPer 市场 overlay
          - 挂载时拉取 /preset/list 渲染社区预设包卡片网格
          - 克隆 (/preset/clone) 不直接创建身份, 返回配置后
            onClone 切换到 birth-ceremony 由诞生仪式完成身份创建
          - 关闭后 setActivePanel(null) */}
      {laaperMarketOpen && (
        <Suspense fallback={null}>
          <MarketBrowser
            onClose={() => useStore.getState().setActivePanel(null)}
            onClone={(_config) => {
              // 克隆配置交给诞生仪式; birth-ceremony 内部引导用户完成身份创建
              useStore.getState().setActivePanel('birth-ceremony');
            }}
          />
        </Suspense>
      )}

      {/* In-window settings overlay */}
      <SettingsModalShell />

      {/* Input context menu (cut/copy/paste) */}
      <InputContextMenu />

      {/* Selection quote action */}
      <SelectionQuoteActionSurface />

      {/* Toast notifications */}
      <ToastContainer />

    </ErrorBoundary>
  );
}

export default App;
