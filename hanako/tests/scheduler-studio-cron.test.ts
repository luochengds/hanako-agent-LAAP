import fs from "fs";
import os from "os";
import path from "path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createCronSchedulerMock, schedulers } = vi.hoisted(() => ({
  createCronSchedulerMock: vi.fn(),
  schedulers: [],
}));

vi.mock("../lib/desk/cron-scheduler.js", () => ({
  createCronScheduler: createCronSchedulerMock,
}));

vi.mock("../lib/desk/heartbeat.js", () => ({
  HEARTBEAT_ACTIVITY_DIR: ".hana-heartbeat",
  createHeartbeat: vi.fn(() => ({
    start: vi.fn(),
    stop: vi.fn().mockResolvedValue(undefined),
  })),
}));

vi.mock("../lib/fresh-compact/daily-scheduler.js", () => ({
  createFreshCompactDailyScheduler: vi.fn(() => ({
    start: vi.fn(),
    stop: vi.fn(),
  })),
}));

vi.mock("../hub/fresh-compact-maintainer.js", () => ({
  FreshCompactMaintainer: vi.fn().mockImplementation(function () {
    this.runDaily = vi.fn();
  }),
}));

import { Scheduler } from "../hub/scheduler.ts";

describe("Scheduler studio cron", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    schedulers.length = 0;
    createCronSchedulerMock.mockImplementation((opts) => {
      const scheduler = {
        opts,
        start: vi.fn(),
        stop: vi.fn().mockResolvedValue(undefined),
        checkJobs: vi.fn(),
      };
      schedulers.push(scheduler);
      return scheduler;
    });
  });

  it("starts one studio cron scheduler instead of one scheduler per agent directory", () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "hana-scheduler-cron-"));
    try {
      fs.mkdirSync(path.join(root, "agents", "agent-a"), { recursive: true });
      fs.mkdirSync(path.join(root, "agents", "agent-b"), { recursive: true });
      const studioStore = { listJobs: vi.fn(() => []) };
      const engine = {
        agentsDir: path.join(root, "agents"),
        agents: new Map(),
        getStudioCronStore: () => studioStore,
        getHeartbeatMaster: () => false,
      };

      const scheduler = new Scheduler({ hub: { engine, eventBus: { emit: vi.fn() } } });
      scheduler.start();

      expect(createCronSchedulerMock).toHaveBeenCalledTimes(1);
      expect(createCronSchedulerMock.mock.calls[0][0].cronStore).toBe(studioStore);
      expect(schedulers[0].start).toHaveBeenCalledOnce();
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("executes a studio cron job with its actorAgentId and captured executionContext", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "hana-scheduler-cron-"));
    try {
      const agentsDir = path.join(root, "agents");
      fs.mkdirSync(path.join(agentsDir, "agent-a"), { recursive: true });
      fs.mkdirSync(path.join(agentsDir, "agent-b"), { recursive: true });
      const activityStore = { add: vi.fn() };
      const executeIsolated = vi.fn(async () => ({ sessionPath: "", error: null }));
      const engine = {
        agentsDir,
        agents: new Map(),
        getStudioCronStore: () => ({ listJobs: vi.fn(() => []) }),
        getHeartbeatMaster: () => false,
        ensureAgentRuntime: vi.fn(async (agentId) => ({ id: agentId, agentName: agentId })),
        getAgent: vi.fn((agentId) => ({ id: agentId, agentName: agentId })),
        executeIsolated,
        summarizeActivity: vi.fn(),
        getActivityStore: vi.fn(() => activityStore),
        emitDevLog: vi.fn(),
      };
      const eventBus = { emit: vi.fn() };
      const scheduler = new Scheduler({ hub: { engine, eventBus } });
      scheduler.start();
      const executeJob = createCronSchedulerMock.mock.calls[0][0].executeJob;

      await executeJob({
        id: "studio_job_1",
        label: "Agent B workspace job",
        prompt: "run in b",
        model: { id: "gpt-test", provider: "openai" },
        actorAgentId: "agent-b",
        executionContext: {
          kind: "session_workspace",
          cwd: "/workspace/b",
          workspaceFolders: ["/workspace/ref"],
          sourceSessionPath: "/sessions/b.jsonl",
          createdByAgentId: "agent-b",
        },
      });

      expect(executeIsolated).toHaveBeenCalledWith(
        expect.stringContaining("run in b"),
        expect.objectContaining({
          agentId: "agent-b",
          cwd: "/workspace/b",
          workspaceFolders: ["/workspace/ref"],
          parentSessionPath: "/sessions/b.jsonl",
          model: { id: "gpt-test", provider: "openai" },
          activityType: "cron",
        }),
      );
      expect(activityStore.add).toHaveBeenCalledWith(expect.objectContaining({
        type: "cron",
        agentId: "agent-b",
        label: "Agent B workspace job",
      }));
      expect(eventBus.emit).toHaveBeenCalledWith(
        expect.objectContaining({ type: "activity_update" }),
        null,
      );
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("executes agent_session cron jobs through the executor read model", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "hana-scheduler-cron-"));
    try {
      const agentsDir = path.join(root, "agents");
      fs.mkdirSync(path.join(agentsDir, "agent-a"), { recursive: true });
      const activityStore = { add: vi.fn() };
      const executeIsolated = vi.fn(async () => ({ sessionPath: "", error: null }));
      const engine = {
        agentsDir,
        agents: new Map(),
        getStudioCronStore: () => ({ listJobs: vi.fn(() => []) }),
        getHeartbeatMaster: () => false,
        ensureAgentRuntime: vi.fn(async (agentId) => ({ id: agentId, agentName: agentId })),
        getAgent: vi.fn((agentId) => ({ id: agentId, agentName: agentId })),
        executeIsolated,
        summarizeActivity: vi.fn(),
        getActivityStore: vi.fn(() => activityStore),
        emitDevLog: vi.fn(),
      };
      const eventBus = { emit: vi.fn() };
      const scheduler = new Scheduler({ hub: { engine, eventBus } });
      scheduler.start();
      const executeJob = createCronSchedulerMock.mock.calls[0][0].executeJob;

      await executeJob({
        id: "studio_job_2",
        label: "Executor job",
        trigger: { kind: "cron", expression: "0 9 * * *" },
        executor: {
          kind: "agent_session",
          agentId: "agent-a",
          prompt: "run from executor",
          model: { id: "gpt-test", provider: "openai" },
          executionContext: {
            kind: "session_workspace",
            cwd: "/workspace/a",
            workspaceFolders: ["/workspace/ref"],
            sourceSessionPath: "/sessions/a.jsonl",
            createdByAgentId: "agent-a",
          },
        },
      });

      expect(executeIsolated).toHaveBeenCalledWith(
        expect.stringContaining("run from executor"),
        expect.objectContaining({
          agentId: "agent-a",
          cwd: "/workspace/a",
          workspaceFolders: ["/workspace/ref"],
          parentSessionPath: "/sessions/a.jsonl",
          model: { id: "gpt-test", provider: "openai" },
          activityType: "cron",
        }),
      );
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("uses the global automation permission mode for background Agent cron runs", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "hana-scheduler-cron-"));
    try {
      const agentsDir = path.join(root, "agents");
      fs.mkdirSync(path.join(agentsDir, "agent-a"), { recursive: true });
      const activityStore = { add: vi.fn() };
      const executeIsolated = vi.fn(async () => ({ sessionPath: "", error: null }));
      const engine = {
        agentsDir,
        agents: new Map(),
        getStudioCronStore: () => ({ listJobs: vi.fn(() => []) }),
        getHeartbeatMaster: () => false,
        getAutomationPermissionMode: vi.fn(() => "auto"),
        ensureAgentRuntime: vi.fn(async (agentId) => ({ id: agentId, agentName: agentId })),
        getAgent: vi.fn((agentId) => ({ id: agentId, agentName: agentId })),
        executeIsolated,
        summarizeActivity: vi.fn(),
        getActivityStore: vi.fn(() => activityStore),
        emitDevLog: vi.fn(),
      };
      const eventBus = { emit: vi.fn() };
      const scheduler = new Scheduler({ hub: { engine, eventBus } });
      scheduler.start();
      const executeJob = createCronSchedulerMock.mock.calls[0][0].executeJob;

      await executeJob({
        id: "studio_job_auto",
        label: "Auto permission job",
        prompt: "run with default permission",
        actorAgentId: "agent-a",
        executionContext: {
          kind: "session_workspace",
          cwd: "/workspace/a",
          workspaceFolders: [],
          sourceSessionPath: "/sessions/a.jsonl",
          createdByAgentId: "agent-a",
        },
      });

      expect(engine.getAutomationPermissionMode).toHaveBeenCalledOnce();
      expect(executeIsolated).toHaveBeenCalledWith(
        expect.stringContaining("run with default permission"),
        expect.objectContaining({
          permissionMode: "auto",
          allowHumanApproval: false,
          activityType: "cron",
        }),
      );
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails closed if an unmigrated non-Agent automation executor reaches the scheduler", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "hana-scheduler-cron-"));
    try {
      const agentsDir = path.join(root, "agents");
      fs.mkdirSync(path.join(agentsDir, "agent-a"), { recursive: true });
      const executeIsolated = vi.fn();
      const engine = {
        agentsDir,
        agents: new Map(),
        getStudioCronStore: () => ({ listJobs: vi.fn(() => []) }),
        getHeartbeatMaster: () => false,
        executeIsolated,
        emitDevLog: vi.fn(),
      };
      const scheduler = new Scheduler({ hub: { engine, eventBus: { emit: vi.fn() } } });
      scheduler.start();
      const executeJob = createCronSchedulerMock.mock.calls[0][0].executeJob;

      const result = executeJob({
        id: "studio_job_notify",
        label: "Drink Water",
        actorAgentId: "agent-a",
        executor: {
          kind: "direct_action",
          action: "notify",
          params: {
            title: "喝水",
            body: "站起来活动一下",
            channels: ["desktop"],
          },
        },
      });

      await expect(result).rejects.toThrow(/unsupported automation executor: direct_action/);
      expect(executeIsolated).not.toHaveBeenCalled();
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  it("notifies once for cron and heartbeat completions but never for other activity types", async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "hana-scheduler-notification-"));
    try {
      const agentsDir = path.join(root, "agents");
      fs.mkdirSync(path.join(agentsDir, "agent-a"), { recursive: true });
      const deliverNotification = vi.fn(async () => ({ ok: true }));
      const executeIsolated = vi.fn()
        .mockResolvedValueOnce({ sessionPath: "/sessions/cron.jsonl", error: null })
        .mockResolvedValueOnce({ sessionPath: "/sessions/heartbeat.jsonl", error: "patrol failed" });
      const engine = {
        agentsDir,
        ensureAgentRuntime: vi.fn(async () => undefined),
        getAgent: vi.fn(() => ({ id: "agent-a", agentName: "Hana" })),
        executeIsolated,
        summarizeActivity: vi.fn(async (sessionPath) => path.basename(sessionPath)),
        getActivityStore: vi.fn(() => ({ add: vi.fn() })),
        emitDevLog: vi.fn(),
        getNotificationPreferences: vi.fn(() => ({
          chatCompletion: "never",
          scheduledTaskCompletion: "always",
          patrolCompletion: "always",
        })),
        deliverNotification,
      };
      const scheduler = new Scheduler({ hub: { engine, eventBus: { emit: vi.fn() } } });

      await scheduler._executeActivityForAgent("agent-a", "cron prompt", "cron", "Daily report");
      expect(deliverNotification).toHaveBeenCalledTimes(1);
      expect(deliverNotification).toHaveBeenLastCalledWith(
        expect.objectContaining({
          desktopFocusPolicy: "always",
          sessionPath: "/sessions/cron.jsonl",
          idempotencyKey: "activity-completion:cron:agent-a:/sessions/cron.jsonl",
        }),
        { agentId: "agent-a" },
      );

      await expect(scheduler._executeActivityForAgent(
        "agent-a",
        "heartbeat prompt",
        "heartbeat",
        "Routine patrol",
      )).rejects.toThrow("patrol failed");
      expect(deliverNotification).toHaveBeenCalledTimes(2);
      expect(deliverNotification).toHaveBeenLastCalledWith(
        expect.objectContaining({
          desktopFocusPolicy: "always",
          sessionPath: "/sessions/heartbeat.jsonl",
          idempotencyKey: "activity-completion:heartbeat:agent-a:/sessions/heartbeat.jsonl",
        }),
        { agentId: "agent-a" },
      );

      for (const type of ["workflow", "subagent"]) {
        await scheduler._deliverActivityCompletionNotification({
          entry: {
            id: `${type}-1`,
            type,
            label: type,
            agentId: "agent-a",
            agentName: "Hana",
            summary: type,
            status: "done",
          },
          sessionPath: `/sessions/${type}.jsonl`,
        });
      }
      expect(deliverNotification).toHaveBeenCalledTimes(2);
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
});
