#!/usr/bin/env node
"use strict";

const { spawnSync } = require("node:child_process");
const { realpathSync } = require("node:fs");
const { constants } = require("node:os");

const TARGET = "aarch64-unknown-linux-gnu";

function rejectOverride() {
  throw new Error("managed GNU ARM cross-linking does not support an explicit linker override");
}

function validateFlags(flags) {
  for (let index = 0; index < flags.length; index += 1) {
    const flag = flags[index] === "-C" ? flags[++index] : flags[index].replace(/^-C/, "");
    if (/^(linker|linker-flavor)=/.test(flag ?? "") || /^link-args?=.*(?:fuse-ld|ld-path)/.test(flag ?? "")) {
      rejectOverride();
    }
  }
}

function unquote(value) {
  if (value.startsWith("'")) return value.slice(1, -1);
  if (!value.startsWith('"')) return value;
  try {
    return JSON.parse(value);
  } catch {
    return rejectOverride();
  }
}

function validateConfig(value) {
  const keyPart = String.raw`(?:[A-Za-z0-9_-]+|"(?:[^"\\]|\\.)*"|'[^']*')`;
  const assignment = new RegExp(`^\\s*(${keyPart}(?:\\s*\\.\\s*${keyPart})*)\\s*=`).exec(value ?? "");
  if (!assignment) rejectOverride();
  const keys = assignment[1].match(new RegExp(keyPart, "g")).map(unquote);
  const target = keys[0] === "target" && (keys[1] === TARGET || keys[1].startsWith("cfg("));
  if (target && keys.at(-1) === "linker") rejectOverride();
  if ((target || keys[0] === "build") && keys.at(-1) === "rustflags") {
    const literals = value.slice(assignment[0].length).match(/"(?:[^"\\]|\\.)*"|'[^']*'|#[^\n]*/g) ?? [];
    const comment = literals.findIndex((literal) => literal.startsWith("#"));
    const strings = comment < 0 ? literals : literals.slice(0, comment);
    validateFlags(strings.flatMap((literal) => unquote(literal).split(/\s+/)));
  }
}

function validateLinker(args, env) {
  const keys = [
    "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER",
    `CC_${TARGET}`,
    "CC_aarch64_unknown_linux_gnu",
    `CXX_${TARGET}`,
    "CXX_aarch64_unknown_linux_gnu",
  ];
  if (keys.some((key) => Object.hasOwn(env, key))) rejectOverride();
  const plainFlags =
    env.RUSTFLAGS ?? env.CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_RUSTFLAGS ?? env.CARGO_BUILD_RUSTFLAGS ?? "";
  const flags = Object.hasOwn(env, "CARGO_ENCODED_RUSTFLAGS")
    ? env.CARGO_ENCODED_RUSTFLAGS.split("\x1f")
    : plainFlags.split(/\s+/);
  validateFlags(flags);
  for (let index = 0; index < args.length; index += 1) {
    const value =
      args[index] === "--config"
        ? args[++index]
        : args[index].startsWith("--config=")
          ? args[index].slice("--config=".length)
          : null;
    if (value !== null) validateConfig(value);
  }
}

function managedArgs(args, env) {
  if (args[0] !== "zigbuild") return args;
  validateLinker(args, env);
  let targets = 0;
  const result = args.map((arg, index) => {
    const value = arg.startsWith("--target=")
      ? arg.slice("--target=".length)
      : args[index - 1] === "--target"
        ? arg
        : null;
    if (value === null) return arg;
    if (value !== TARGET) throw new Error("managed GNU ARM cross-linking requires its canonical target");
    targets += 1;
    return arg.startsWith("--target=") ? `--target=${TARGET}.2.17` : `${TARGET}.2.17`;
  });
  if (targets !== 1) throw new Error("managed GNU ARM cross-linking requires exactly one target");
  return result;
}

try {
  const cargo = process.env.XBERG_NAPI_REAL_CARGO;
  if (!cargo || realpathSync(cargo) === realpathSync(__filename)) {
    throw new Error("managed GNU ARM cross-linking requires the real Cargo executable");
  }
  const env = { ...process.env, CARGO: cargo };
  delete env.XBERG_NAPI_REAL_CARGO;
  const args = managedArgs(process.argv.slice(2), env);
  const result = spawnSync(cargo, args, { env, stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.signal) process.exitCode = 128 + (constants.signals[result.signal] ?? 1);
  else process.exitCode = result.status;
} catch (error) {
  process.stderr.write(`build-node-napi: ${error.message}\n`);
  process.exitCode = 1;
}
