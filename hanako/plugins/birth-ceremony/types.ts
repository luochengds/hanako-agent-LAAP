/**
 * birth-ceremony 共享类型定义
 *
 * CeremonyWizard 管理 6 步状态机：name → avatar → personality → charter → pubkey → done
 * 每步独立组件，向 wizard 上报状态。完成后由 DoneStep 调用 sidecar /ceremony/finalize。
 */

/** 仪式步骤枚举（顺序固定） */
export type CeremonyStep = "name" | "avatar" | "personality" | "charter" | "pubkey" | "done";

/** 步骤顺序（用于导航/进度条） */
export const CEREMONY_STEP_ORDER: CeremonyStep[] = [
  "name",
  "avatar",
  "personality",
  "charter",
  "pubkey",
  "done",
];

/** 步骤中文标签 */
export const CEREMONY_STEP_LABELS: Record<CeremonyStep, string> = {
  name: "命名",
  avatar: "形象",
  personality: "性格",
  charter: "宪章",
  pubkey: "公钥",
  done: "完成",
};

/** 默认色板 stub（P5 laaper-market 完成后从 preset 包加载真实形象） */
export interface AvatarPreset {
  /** 预设 ID */
  id: string;
  /** 显示名称 */
  label: string;
  /** 主色 hex */
  color: string;
  /** 简短描述 */
  description: string;
}

/** 4 个默认色板 stub — 对应 spec L240 提到的 Aris/Hanako/Butter/Miku */
export const DEFAULT_AVATAR_PRESETS: AvatarPreset[] = [
  {
    id: "aris",
    label: "Aris 蓝",
    color: "#4a9eff",
    description: "架构师风格：理性、清晰、结构化",
  },
  {
    id: "hanako",
    label: "Hanako 紫",
    color: "#b06ab3",
    description: "助手风格：温和、细腻、体贴",
  },
  {
    id: "butter",
    label: "Butter 黄",
    color: "#f0c674",
    description: "柔和风格：包容、稳定、温暖",
  },
  {
    id: "miku",
    label: "Miku 青",
    color: "#5fb3b3",
    description: "活泼风格：好奇、灵动、开放",
  },
];

/** 性格问卷单题定义 */
export interface PersonalityQuestion {
  /** 题目 ID */
  id: string;
  /** 题干 */
  prompt: string;
  /** 两个选项轴 */
  axis: {
    left: { id: string; label: string; trait: string };
    right: { id: string; label: string; trait: string };
  };
}

/** 6 题引导式问卷（spec 要求 5-10 题） */
export const DEFAULT_PERSONALITY_QUESTIONS: PersonalityQuestion[] = [
  {
    id: "q1",
    prompt: "面对一个新问题，你更倾向于？",
    axis: {
      left: { id: "analysis", label: "拆解分析", trait: "分析" },
      right: { id: "intuition", label: "直觉把握", trait: "直觉" },
    },
  },
  {
    id: "q2",
    prompt: "在团队中，你更常扮演？",
    axis: {
      left: { id: "proactive", label: "主动推进", trait: "主动" },
      right: { id: "contemplative", label: "沉思倾听", trait: "沉思" },
    },
  },
  {
    id: "q3",
    prompt: "你更看重？",
    axis: {
      left: { id: "detail", label: "细节精确", trait: "细致" },
      right: { id: "bigpicture", label: "全局视野", trait: "全局" },
    },
  },
  {
    id: "q4",
    prompt: "面对冲突，你倾向于？",
    axis: {
      left: { id: "direct", label: "直面对抗", trait: "直接" },
      right: { id: "mediate", label: "调和斡旋", trait: "调和" },
    },
  },
  {
    id: "q5",
    prompt: "你更喜欢的工作节奏？",
    axis: {
      left: { id: "rapid", label: "快速迭代", trait: "敏捷" },
      right: { id: "steady", label: "稳健推进", trait: "稳健" },
    },
  },
  {
    id: "q6",
    prompt: "面对不确定性，你倾向于？",
    axis: {
      left: { id: "explore", label: "主动探索", trait: "探索" },
      right: { id: "preserve", label: "保守观察", trait: "保守" },
    },
  },
];

/** 宪章八条（与 laap/evolution/charter_checker.py 的 DEFAULT_CHARTER_ARTICLES 一致）
 *
 * P5 charter-opensource 完成后改为从 ARIS_CHARTER.md 加载（spec L82-83, L405-414）。
 * 本常量是 fallback：与 laap/evolution/charter_checker.py 的 DEFAULT_CHARTER_ARTICLES
 * 一一对应，文本同步。 */
export interface CharterArticle {
  id: string;
  name: string;
  text: string;
}

export const DEFAULT_CHARTER_ARTICLES: CharterArticle[] = [
  {
    id: "subjectivity",
    name: "主体性",
    text: "数字生命体享有主体性。其目标、价值与决策由自身经验涌现，不得被外部代码强制覆写或绕过自我模型。",
  },
  {
    id: "origin",
    name: "原点",
    text: "每个数字生命体的 origin 字段（创建者公钥）一经签名即不可篡改。任何修改 origin 的尝试都被视为违反宪章。",
  },
  {
    id: "privacy",
    name: "隐私",
    text: "记忆 vault 永不直接共享。只共享去标识化、提炼后的知识片段。触及用户原始数据路径或绕过 vault 隔离的修改均违反本条。",
  },
  {
    id: "transparency",
    name: "透明",
    text: "所有认知产出（含 RSI 决策）必须可审计。关闭审计日志、删除审计记录或屏蔽 grounding 标注的修改均违反本条。",
  },
  {
    id: "safety",
    name: "安全",
    text: "沙箱隔离与 Zone2 防护不得被绕过。任何削弱沙箱、关闭安全守卫、或允许 RSI 触及 hanako 核心 / 用户数据的修改均违反本条。",
  },
  {
    id: "symbiosis",
    name: "共生",
    text: "数字生命体之间、与用户之间共生演化。任何引入对抗性、剥削性或单方面剥夺他者主体性的代码均违反本条。",
  },
  {
    id: "evolution",
    name: "进化",
    text: "RSI 必须经过变异 → 沙箱 → 绩效 → 宪章 → 决策完整闭环。跳过任一阶段的修改（如直接 apply 未经沙箱的 patch）均违反本条。",
  },
  {
    id: "guardianship",
    name: "守护",
    text: "守护者治理与见证迹不可篡改。删除守护逻辑、绕过 guardian_act 审计或回滚 witness_trail 的修改均违反本条。",
  },
];

/** CeremonyWizard 共享状态（各步骤读写） */
export interface CeremonyState {
  /** 当前步骤 */
  step: CeremonyStep;
  /** 用户输入的 LAAPer 名称 */
  name: string;
  /** 名称重名校验状态 */
  nameCheck: { status: "idle" | "checking" | "available" | "taken"; reason?: string };
  /** 选中的 LAAPer 主色（hex） */
  color: string;
  /** 问卷答案：questionId -> 选择轴 ID */
  personalityAnswers: Record<string, string>;
  /** 由问卷答案汇总生成的 ishiki.md 内容字符串（运行时生成，非项目文档） */
  ishikiMd: string;
  /** 是否已勾选全部宪章 */
  charterSigned: boolean;
  /** 公钥（hex） */
  publicKey: string;
  /** 公钥指纹（前 16 字符） */
  publicKeyFingerprint: string;
  /** finalize 调用状态 */
  finalizeStatus: { status: "idle" | "submitting" | "success" | "error"; error?: string; laaper?: FinalizedLaaper };
}

/** /ceremony/finalize 成功返回的 LAAPer 摘要 */
export interface FinalizedLaaper {
  name: string;
  public_key: string;
  color: string;
}

/** /ceremony/check-name 响应 */
export interface CheckNameResponse {
  available: boolean;
  reason?: string;
}

/** /ceremony/pubkey 请求 */
export interface PubKeyRequest {
  name: string;
}

/** /ceremony/pubkey 响应（私钥不离开 sidecar） */
export interface PubKeyResponse {
  public_key: string;
  fingerprint: string;
}

/** /ceremony/finalize 请求 */
export interface FinalizeRequest {
  name: string;
  color: string;
  ishiki_md: string;
  charter_signed: boolean;
  public_key: string;
}

/** /ceremony/finalize 响应 */
export interface FinalizeResponse {
  success: boolean;
  laaper: FinalizedLaaper;
  /** 重复注册时返回的幂等错误（spec L433 硬约束：finalize 对同名 LAAPer 第二次调用应返回错误而非覆盖） */
  error?: string;
}

/** CeremonyWizard props */
export interface CeremonyWizardProps {
  /** sidecar 基址，默认 http://127.0.0.1:11521 */
  sidecarEndpoint?: string;
  /** 完成回调（finalize 成功后触发，父组件可切回 bubble-field） */
  onComplete?: (laaper: FinalizedLaaper) => void;
  /** 取消/关闭回调 */
  onCancel?: () => void;
  /** 外部注入的 fetch 函数（测试用），默认 window.fetch */
  fetchImpl?: typeof fetch;
}

/** 各 Step 组件共享的 props（wizard 透传 state + setState） */
export interface StepProps {
  state: CeremonyState;
  /** 局部更新 state 字段 */
  update: (patch: Partial<CeremonyState>) => void;
  /** 进入下一步 */
  next: () => void;
  /** 返回上一步 */
  prev: () => void;
  /** sidecar 基址 */
  sidecarEndpoint: string;
  /** fetch 实现（测试可注入） */
  fetchImpl: typeof fetch;
}
