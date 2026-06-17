/**
 * Bridge to the Python engine.
 *
 * Spawns `python -m crabkey.cli.bridge` and exchanges newline-delimited JSON.
 * Everything the engine prints on stdout is a protocol event; stderr is treated
 * as diagnostics.
 */
import {spawn, type ChildProcess} from 'node:child_process';
import {EventEmitter} from 'node:events';
import readline from 'node:readline';

export type BridgeEvent = {
	type: string;
	[key: string]: unknown;
};

export type ReadyEvent = {
	type: 'ready';
	provider: string;
	model: string;
	missing_key: string | null;
	cwd: string;
	providers: string[];
};

export class Bridge extends EventEmitter {
	private readonly proc: ChildProcess;
	private closed = false;

	constructor() {
		super();
		const python = process.env['CRABKEY_PYTHON'] ?? 'python3';
		const projectCwd = process.env['CRABKEY_CWD'] ?? process.cwd();
		const repoRoot = process.env['CRABKEY_REPO'] ?? projectCwd;

		const args = ['-m', 'crabkey.cli.bridge', '--cwd', projectCwd];
		if (process.env['CRABKEY_PROVIDER']) {
			args.push('--provider', process.env['CRABKEY_PROVIDER']!);
		}
		if (process.env['CRABKEY_MODEL']) {
			args.push('--model', process.env['CRABKEY_MODEL']!);
		}

		this.proc = spawn(python, args, {
			cwd: repoRoot, // run from repo root so `crabkey` is importable
			env: {...process.env, PYTHONUNBUFFERED: '1'},
			stdio: ['pipe', 'pipe', 'pipe'],
		});

		const rl = readline.createInterface({input: this.proc.stdout!});
		rl.on('line', line => {
			const trimmed = line.trim();
			if (!trimmed) return;
			try {
				this.emit('event', JSON.parse(trimmed) as BridgeEvent);
			} catch {
				// Non-JSON noise on stdout — ignore so the UI never breaks.
			}
		});

		let stderr = '';
		this.proc.stderr!.on('data', (chunk: Buffer) => {
			stderr += chunk.toString();
		});

		this.proc.on('close', code => {
			this.closed = true;
			this.emit('close', code, stderr);
		});
		this.proc.on('error', err => {
			this.emit('event', {
				type: 'error',
				data: `Failed to start the CrabKey engine: ${err.message}`,
			});
		});
	}

	send(message: BridgeEvent): void {
		if (this.closed) return;
		this.proc.stdin!.write(JSON.stringify(message) + '\n');
	}

	prompt(text: string): void {
		this.send({type: 'prompt', text});
	}

	quit(): void {
		this.send({type: 'quit'});
		this.proc.stdin!.end();
	}
}
