const os = require("os");
const path = require("path");

function expandHome(input, homeDir = os.homedir()) {
  if (!input) return input;
  if (input === "~") return homeDir;
  if (input.startsWith("~/") || input.startsWith("~" + path.sep)) {
    return path.join(homeDir, input.slice(2));
  }
  return input;
}

// LAAP 定制版默认 home 目录与官方 Hanako 隔离，避免数据/端口/单实例冲突.
const DEFAULT_HOME_DIR_NAME = ".hanako-laap";

function resolveHanakoHome(input, homeDir = os.homedir()) {
  const raw = input || path.join(homeDir, DEFAULT_HOME_DIR_NAME);
  return path.resolve(expandHome(raw, homeDir));
}

function assertHanakoHome(hanakoHome, caller) {
  if (!hanakoHome || typeof hanakoHome !== "string") {
    throw new Error(`${caller}: hanakoHome is required`);
  }
}

function resolveHanaPiSdkRuntimeRoot(hanakoHome) {
  assertHanakoHome(hanakoHome, "resolveHanaPiSdkRuntimeRoot");
  return path.join(hanakoHome, "runtime", "pi-sdk");
}

function resolveHanaPiSdkManagedBinDir(hanakoHome) {
  return path.join(resolveHanaPiSdkRuntimeRoot(hanakoHome), "bin");
}

function resolveHanaPiSdkResourceLoaderCwd(hanakoHome) {
  return path.join(resolveHanaPiSdkRuntimeRoot(hanakoHome), "resource-loader", "project");
}

function resolveHanaPiSdkResourceLoaderAgentDir(hanakoHome) {
  return path.join(resolveHanaPiSdkRuntimeRoot(hanakoHome), "resource-loader", "agent");
}

function resolveLegacyPiSdkManagedBinDir(hanakoHome) {
  assertHanakoHome(hanakoHome, "resolveLegacyPiSdkManagedBinDir");
  return path.join(hanakoHome, ".pi", "agent", "bin");
}

module.exports = {
  resolveHanakoHome,
  resolveHanaPiSdkManagedBinDir,
  resolveHanaPiSdkResourceLoaderAgentDir,
  resolveHanaPiSdkResourceLoaderCwd,
  resolveHanaPiSdkRuntimeRoot,
  resolveLegacyPiSdkManagedBinDir,
};
