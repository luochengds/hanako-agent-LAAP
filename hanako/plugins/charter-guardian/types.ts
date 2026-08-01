/**
 * charter-guardian plugin 类型定义 (P4-charter-guardian)
 *
 * 守护权力行使记录 + 社区健康仪表盘的数据契约.
 */

/** 守护权力 action 类型（spec L367） */
export type GuardianAction = "suspend" | "warn" | "expel" | "restore";

/** 目标 agent 当前状态（GuardianRegistry._target_status 取值） */
export type TargetStatus = "active" | "suspended" | "warned" | "expelled" | "restored";

/** 单条行使记录（来自 /guardian/list） */
export interface GuardianAct {
  act_id: string;
  action: GuardianAction;
  target: string;
  reason: string;
  guardian_public_key: string;
  previous_status: TargetStatus;
  new_status: TargetStatus;
  trail_id: string;
  trail_hash: string;
  timestamp: number;
}

/** 近期滥用事件（stats.recent_abuse_events） */
export interface AbuseEvent {
  act_id: string;
  action: GuardianAction;
  target: string;
  reason: string;
  timestamp: number;
}

/** 社区健康仪表盘统计（/guardian/stats 返回） */
export interface GuardianStats {
  total_acts: number;
  by_action: Record<GuardianAction, number>;
  by_target_status: Record<string, number>;
  active_guardians: number;
  recent_abuse_events: AbuseEvent[];
  targets_count: number;
  target_status_snapshot: Record<string, number>;
}

/** guardian_act 端点返回结构 */
export interface GuardianActResult {
  acted: boolean;
  act_id?: string;
  trail_id?: string;
  hash?: string;
  action?: GuardianAction;
  target?: string;
  target_status?: TargetStatus;
  reason?: string;
  guardian_public_key?: string;
  reason_if_failed?: string;
  error?: string;
}

/** guardian_register 端点返回结构 */
export interface GuardianRegisterResult {
  registered: boolean;
  public_key?: string;
  total_guardians?: number;
  reason?: string;
  error?: string;
}

/** get_target_status 端点返回结构 */
export interface TargetStatusResult {
  target: string;
  status: TargetStatus;
  reason?: string;
}
