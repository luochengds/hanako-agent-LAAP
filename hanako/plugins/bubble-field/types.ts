/**
 * bubble-field 共享类型定义
 *
 * 状态编码规则（无需文字辅助即可表达身份与状态）：
 * - color:  身份主色（hex），每个 LAAPer 自定义
 * - brightness: 0-1，在线(>0.6) / 休眠(<0.3) / 离线(0)
 * - size: 像素直径，反映认知能量（活跃度 + 共鸣强度）
 * - pulse: 是否正在思考（触发光晕脉冲动画）
 * - status: 语义状态，映射到 brightness / pulse
 */

/** sidecar /agents/online 返回的单个 LAAPer 在线条目 */
export interface AgentOnline {
  /** 分布式公钥标识（P3 identity-pki 产出） */
  public_key: string;
  /** 显示名称 */
  name: string;
  /** 身份主色 hex（如 "#4a9eff"） */
  color: string;
  /** 语义状态 */
  status: "online" | "thinking" | "sleeping";
  /** 认知能量 0.0-1.0，映射到泡泡大小 */
  energy: number;
  /** 能力清单（如 ["code-review", "architecture"]） */
  capabilities: string[];
}

/** sidecar /agents/online 返回格式 */
export interface AgentsOnlineResponse {
  agents: AgentOnline[];
}

/** Bubble 组件 props */
export interface BubbleProps {
  /** 身份主色 hex */
  color: string;
  /** 亮度 0-1（在线/休眠） */
  brightness: number;
  /** 像素直径（认知能量） */
  size: number;
  /** 是否思考中（触发光晕脉冲） */
  pulse: boolean;
  /** 名称 + 状态徽章文本 */
  label: string;
  /** 绝对定位坐标 */
  position: { x: number; y: number };
  /** 点击回调（P3 1v1 对话入口） */
  onClick?: () => void;
  /** 拖拽起始回调 */
  onDragStart?: (e: React.MouseEvent) => void;
  /** 鼠标进入回调（显示浮卡） */
  onMouseEnter?: () => void;
  /** 鼠标离开回调（隐藏浮卡） */
  onMouseLeave?: () => void;
}

/** ResonanceLine 组件 props */
export interface ResonanceLineProps {
  /** 起点坐标 */
  from: { x: number; y: number };
  /** 终点坐标 */
  to: { x: number; y: number };
  /** 共振强度 0-1（>0.7 实线，否则虚线） */
  strength: number;
  /** 连线颜色（可选，默认取共振强度暖色） */
  color?: string;
}

/** BubbleField 内部使用的带位置气泡数据结构 */
export interface PositionedBubble {
  agent: AgentOnline;
  position: { x: number; y: number };
  velocity: { x: number; y: number };
}

/** BubbleField 组件 props */
export interface BubbleFieldProps {
  /** 点击 Bubble 进入 1v1 对话回调（P3 p3-1v1-protocol 完成后接入） */
  onSelectBubble?: (agent: AgentOnline) => void;
  /** 拖拽叠加创建多人聊天室回调（P3 p3-trio-chatroom 完成后接入） */
  onCreateChatroom?: (agents: AgentOnline[]) => void;
  /** sidecar 端点 URL，默认 http://127.0.0.1:11521/agents/online */
  endpoint?: string;
  /** 轮询间隔毫秒，默认 5000 */
  pollInterval?: number;
  /** 外部注入的 agent 列表（用于测试或离线预览，不传则 fetch endpoint） */
  agents?: AgentOnline[];
  /** 关闭回调（overlay 关闭按钮） */
  onClose?: () => void;
}
