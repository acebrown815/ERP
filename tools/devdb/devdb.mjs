// Local PostgreSQL 16 for development and tests on machines without Docker.
// Usage: node devdb.mjs start | stop | status
// Connection: postgresql://erp:erp@127.0.0.1:54329/erp  (test DB: erp_test)
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import pg from "pg";

const here = dirname(fileURLToPath(import.meta.url));
const bin = join(here, "node_modules", "@embedded-postgres", "windows-x64", "native", "bin");
const dataDir = join(here, "data");
const logFile = join(here, "postgres.log");
const PORT = process.env.DEVDB_PORT ?? "54329";
const USER = "erp";
const PASSWORD = "erp";
const DATABASES = ["erp", "erp_test"];

const exe = (name) => join(bin, process.platform === "win32" ? `${name}.exe` : name);

function run(name, args, opts = {}) {
  const res = spawnSync(exe(name), args, { encoding: "utf8", ...opts });
  if (res.error) throw res.error;
  return res;
}

function init() {
  if (existsSync(join(dataDir, "PG_VERSION"))) return;
  mkdirSync(dataDir, { recursive: true });
  const pwFile = join(tmpdir(), `devdb-pw-${process.pid}`);
  writeFileSync(pwFile, PASSWORD);
  try {
    const res = run("initdb", [
      "-D", dataDir, "-U", USER, `--pwfile=${pwFile}`,
      "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C",
    ]);
    if (res.status !== 0) {
      console.error(res.stdout, res.stderr);
      process.exit(1);
    }
  } finally {
    rmSync(pwFile, { force: true });
  }
  console.log(`initialized cluster in ${dataDir}`);
}

async function ensureDatabases() {
  const client = new pg.Client({ host: "127.0.0.1", port: Number(PORT), user: USER, password: PASSWORD, database: "postgres" });
  await client.connect();
  try {
    for (const db of DATABASES) {
      const { rowCount } = await client.query("SELECT 1 FROM pg_database WHERE datname = $1", [db]);
      if (!rowCount) {
        await client.query(`CREATE DATABASE ${db} OWNER ${USER}`);
        console.log(`created database ${db}`);
      }
    }
  } finally {
    await client.end();
  }
}

function status() {
  return run("pg_ctl", ["status", "-D", dataDir]).status === 0;
}

const cmd = process.argv[2] ?? "start";
if (cmd === "start") {
  init();
  if (status()) {
    console.log(`already running on port ${PORT}`);
  } else {
    // stdio must be ignored: the server inherits pg_ctl's handles and would keep pipes open forever.
    const res = run("pg_ctl", ["start", "-w", "-D", dataDir, "-l", logFile, "-o", `-p ${PORT} -h 127.0.0.1`], { stdio: "ignore" });
    if (res.status !== 0) {
      console.error(res.stdout, res.stderr);
      process.exit(1);
    }
    console.log(`postgres running: postgresql://${USER}:${PASSWORD}@127.0.0.1:${PORT}/erp`);
  }
  await ensureDatabases();
} else if (cmd === "stop") {
  if (status()) run("pg_ctl", ["stop", "-w", "-D", dataDir, "-m", "fast"]);
  console.log("stopped");
} else if (cmd === "status") {
  console.log(status() ? "running" : "stopped");
} else {
  console.error("usage: node devdb.mjs start|stop|status");
  process.exit(2);
}
