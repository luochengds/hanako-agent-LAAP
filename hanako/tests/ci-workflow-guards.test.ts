import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";
import { describe, expect, it } from "vitest";

/**
 * tests/ci-workflow-guards.test.ts — 静态断言"边界/构建守卫已接进 CI 工作流"
 *
 * 这不是测试守卫脚本本身（lint-open-boundary.mjs / verify-seed-kit.mjs 各自
 * 有自己的单测），而是测试"工作流 YAML 有没有把它们接上"。动机：这类接线
 * 一旦被后续改动（比如重构 job、精简步骤）无意间删掉，CI 本身不会报错——
 * 少了一个校验步骤只会让流水线更快地"通过"，不会让它变红。这份测试把"工作
 * 流必须包含这些守卫步骤"这件事，从"运维记忆"变成一个会失败的断言。
 *
 * 解析用 js-yaml（仓库已有依赖，见 package.json dependencies），不新增依赖。
 */

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CI_YAML_PATH = path.join(ROOT, ".github", "workflows", "ci.yml");
const BUILD_YAML_PATH = path.join(ROOT, ".github", "workflows", "build.yml");

interface WorkflowStep {
  name?: string;
  run?: string;
  if?: string;
  [key: string]: unknown;
}

interface WorkflowJob {
  steps?: WorkflowStep[];
  [key: string]: unknown;
}

interface WorkflowDoc {
  jobs: Record<string, WorkflowJob>;
  [key: string]: unknown;
}

function loadWorkflow(filePath: string): WorkflowDoc {
  const text = fs.readFileSync(filePath, "utf-8");
  // GitHub Actions workflow YAML uses a bare `on:` key, which YAML 1.1
  // schemas interpret as the boolean `true`. js-yaml's default schema
  // resolves it that way too; we only ever read `jobs`, so this quirk is
  // harmless here and not worked around.
  return yaml.load(text) as WorkflowDoc;
}

function stepRun(step: WorkflowStep): string {
  return typeof step.run === "string" ? step.run : "";
}

describe("ci.yml: open composition build+smoke guard is wired", () => {
  const doc = loadWorkflow(CI_YAML_PATH);

  it("defines an open-build-smoke job", () => {
    expect(doc.jobs).toHaveProperty("open-build-smoke");
  });

  it("the open-build-smoke job builds and smoke-tests the open composition server", () => {
    const job = doc.jobs["open-build-smoke"];
    expect(job).toBeDefined();
    const steps = job.steps ?? [];
    expect(steps.some((s) => stepRun(s).includes("build:server:open"))).toBe(true);
    expect(steps.some((s) => stepRun(s).includes("smoke:server:open"))).toBe(true);
  });

  it("defines a lint-open-boundary job that runs the boundary lint script", () => {
    const job = doc.jobs["lint-open-boundary"];
    expect(job).toBeDefined();
    const steps = job?.steps ?? [];
    expect(steps.some((s) => stepRun(s).includes("scripts/lint-open-boundary.mjs"))).toBe(true);
  });
});

describe("build.yml: seed kit verification precedes every electron-builder invocation", () => {
  const doc = loadWorkflow(BUILD_YAML_PATH);

  it("every job step that invokes electron-builder is preceded, within the same job, by a matching verify-seed-kit step", () => {
    const jobsWithElectronBuilder: string[] = [];

    for (const [jobName, job] of Object.entries(doc.jobs)) {
      const steps = job.steps ?? [];
      steps.forEach((step, index) => {
        // Match the actual invocation ("npx electron-builder"), not a bare "electron-builder"
        // substring — several steps in this file carry that word inside `run:` block-scalar
        // shell comments (e.g. the keychain setup step explaining why CSC_KEYCHAIN is exported
        // for electron-builder to reuse), which would otherwise false-positive here.
        if (!stepRun(step).includes("npx electron-builder")) return;
        jobsWithElectronBuilder.push(jobName);

        const precedingSteps = steps.slice(0, index);
        // The verify step must also gate on the same "if" condition as the electron-builder
        // step it guards — otherwise (e.g. three verify-seed-kit steps for three different
        // platforms all sitting earlier in the same steps array) an unrelated platform's
        // verify step could satisfy a naive "any preceding verify-seed-kit step exists"
        // check while this platform's build runs completely unguarded.
        const guard = precedingSteps.find(
          (s) => stepRun(s).includes("verify-seed-kit.mjs") && s.if === step.if,
        );
        expect(
          guard,
          `job "${jobName}" step "${step.name}" (if: ${step.if}) calls electron-builder ` +
            `without a preceding verify-seed-kit.mjs step gated on the same "if" condition`,
        ).toBeDefined();
      });
    }

    // Sanity: this test would be vacuously true if build.yml stopped invoking
    // electron-builder anywhere at all. Pin down that we actually found the
    // three known platform build steps, so a refactor that removes them all
    // gets caught by this assertion changing rather than by silence.
    expect(jobsWithElectronBuilder.length).toBeGreaterThanOrEqual(3);
  });
});
