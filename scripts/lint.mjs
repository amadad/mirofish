import { spawnSync } from 'node:child_process';

const shouldFix = process.argv.includes('--fix');
const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm';

if (shouldFix) {
  console.log('No auto-fixers are configured; running verification checks only.');
}

const commands = [
  {
    cmd: npmCommand,
    args: ['run', 'build', '--prefix', 'frontend'],
  },
  {
    cmd: 'uv',
    args: ['run', 'pytest', 'tests'],
    cwd: 'backend',
    env: {
      UV_CACHE_DIR: '/tmp/uv-cache',
    },
  },
];

for (const command of commands) {
  const result = spawnSync(command.cmd, command.args, {
    cwd: command.cwd,
    env: {
      ...process.env,
      ...command.env,
    },
    stdio: 'inherit',
  });

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
