import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Box, Static, Text, useApp, useInput} from 'ink';
import {Bridge, type BridgeEvent, type ReadyEvent} from './backend.js';
import {Message, type ChatItem} from './components/Message.js';
import {Prompt} from './components/Prompt.js';
import {CommandPalette} from './components/CommandPalette.js';
import {StatusBar} from './components/StatusBar.js';
import {SLASH_COMMANDS, type SlashCommand, expand, filterCommands} from './commands.js';
import {theme} from './theme.js';

type Status = 'idle' | 'thinking' | 'tool';

type CustomCommand = {name: string; description: string; prompt: string};

// Omit must distribute over the ChatItem union so each variant keeps its keys.
type NewChatItem = ChatItem extends infer T
	? T extends {id: number}
		? Omit<T, 'id'>
		: never
	: never;

const HELP = [
	'Slash commands:',
	'  /help                       show this help',
	'  /session new|list|switch    manage sessions',
	'  /thread  new|list|exit      manage threads (fork the conversation)',
	'  /clear                      clear the conversation',
	'  /quit, /exit                leave CrabKey',
	'',
	'Type / to browse commands; keep typing to filter. ↑/↓ to select, Enter to run.',
	'Tips: Esc cancels the current input · Ctrl+C exits.',
].join('\n');

export function App(): React.ReactElement {
	const {exit} = useApp();
	const bridge = useMemo(() => new Bridge(), []);
	const nextId = useRef(0);
	const make = () => nextId.current++;

	const [items, setItems] = useState<ChatItem[]>([]);
	const [input, setInput] = useState('');
	const [selected, setSelected] = useState(0);
	const [status, setStatus] = useState<Status>('idle');
	const [activeTool, setActiveTool] = useState<string | undefined>();
	const [busy, setBusy] = useState(false);
	const [ready, setReady] = useState<ReadyEvent | null>(null);
	const [tokens, setTokens] = useState({in: 0, out: 0});
	const [customCommands, setCustomCommands] = useState<CustomCommand[]>([]);
	const [session, setSession] = useState<string | undefined>();
	const [thread, setThread] = useState<string | undefined>();

	const push = (item: NewChatItem) =>
		setItems(prev => [...prev, {...item, id: make()} as ChatItem]);

	// Built-in commands plus any custom commands the engine reported.
	const allCommands: SlashCommand[] = useMemo(
		() => [
			...SLASH_COMMANDS,
			...customCommands.map(c => ({name: c.name, description: c.description})),
		],
		[customCommands],
	);

	// Command palette: open while typing a slash command (before any space/args).
	const paletteOpen = !busy && input.startsWith('/') && !input.includes(' ');
	const matches = useMemo(
		() => (paletteOpen ? filterCommands(input.slice(1), allCommands) : []),
		[paletteOpen, input, allCommands],
	);
	// Reset the highlight to the top whenever the query changes.
	useEffect(() => {
		setSelected(0);
	}, [input]);

	useEffect(() => {
		const onEvent = (evt: BridgeEvent) => {
			switch (evt.type) {
				case 'ready': {
					const r = evt as unknown as ReadyEvent;
					setReady(r);
					const cmds = (evt['commands'] ?? []) as CustomCommand[];
					setCustomCommands(cmds);
					push({
						role: 'banner',
						provider: r.provider,
						model: r.model,
						cwd: r.cwd,
					});
					if (r.missing_key) {
						push({
							role: 'error',
							text: `${r.missing_key} is not set. Run \`crabkey configure\` or export ${r.missing_key} before chatting.`,
						});
					}
					break;
				}
				case 'thinking':
					setStatus('thinking');
					break;
				case 'text':
					push({role: 'assistant', text: String(evt['data'] ?? '')});
					setStatus('thinking');
					break;
				case 'tool_call': {
					const tool = String(evt['tool'] ?? 'tool');
					setActiveTool(tool);
					setStatus('tool');
					push({
						role: 'tool',
						tool,
						args: String(evt['args'] ?? ''),
					});
					break;
				}
				case 'tool_result':
					// Attach the result to the most recent matching tool call.
					setItems(prev => {
						const copy = [...prev];
						for (let i = copy.length - 1; i >= 0; i--) {
							const it = copy[i]!;
							if (it.role === 'tool' && it.result === undefined) {
								copy[i] = {
									...it,
									result: String(evt['data'] ?? ''),
									isError: Boolean(evt['is_error']),
								};
								break;
							}
						}
						return copy;
					});
					setStatus('thinking');
					break;
				case 'turn_end': {
					const usage = (evt['usage'] ?? {}) as Record<string, number>;
					setTokens({
						in: usage['total_in'] ?? 0,
						out: usage['total_out'] ?? 0,
					});
					setStatus('idle');
					setBusy(false);
					setActiveTool(undefined);
					break;
				}
				case 'error':
					push({role: 'error', text: String(evt['data'] ?? 'Unknown error')});
					setStatus('idle');
					setBusy(false);
					break;
				case 'info':
					push({role: 'info', text: String(evt['data'] ?? '')});
					break;
				case 'state':
					setSession((evt['session'] as string) ?? undefined);
					setThread((evt['thread'] as string) ?? undefined);
					break;
				default:
					break;
			}
		};

		const onClose = (code: number | null, stderr: string) => {
			if (code && code !== 0) {
				push({
					role: 'error',
					text: `Engine exited (code ${code}).${stderr ? '\n' + stderr.trim() : ''}`,
				});
			}
		};

		bridge.on('event', onEvent);
		bridge.on('close', onClose);
		return () => {
			bridge.off('event', onEvent);
			bridge.off('close', onClose);
		};
	}, [bridge]);

	const quit = () => {
		bridge.quit();
		exit();
	};

	useInput((_input, key) => {
		if (key.escape && !busy) {
			setInput('');
			return;
		}
		// Navigate the command palette with the arrow keys while it is open.
		if (paletteOpen && matches.length > 0) {
			if (key.downArrow) {
				setSelected(s => (s + 1) % matches.length);
			} else if (key.upArrow) {
				setSelected(s => (s - 1 + matches.length) % matches.length);
			}
		}
	});

	const handleSubmit = (raw: string) => {
		const text = raw.trim();
		setInput('');
		if (!text) return;

		if (text.startsWith('/')) {
			const parts = text.slice(1).split(/\s+/);
			let cmd = (parts[0] ?? '').toLowerCase();
			const rest = parts.slice(1);
			// If no args were typed, Enter runs the highlighted palette match,
			// so `/he` + Enter runs `help`.
			if (rest.length === 0) {
				const m = filterCommands(parts[0] ?? '', allCommands);
				if (m.length > 0) {
					cmd = m[Math.min(selected, m.length - 1)]!.name;
				}
			}

			if (cmd === 'quit' || cmd === 'exit' || cmd === 'q') {
				quit();
				return;
			}
			if (cmd === 'clear') {
				setItems([]);
				return;
			}
			if (cmd === 'help') {
				push({role: 'info', text: HELP});
				return;
			}
			if (cmd === 'session' || cmd === 'thread') {
				bridge.send({
					type: cmd,
					action: rest[0],
					name: rest.slice(1).join(' ') || undefined,
				});
				return;
			}
			const custom = customCommands.find(c => c.name === cmd);
			if (custom) {
				push({role: 'user', text});
				setBusy(true);
				setStatus('thinking');
				bridge.prompt(expand(custom.prompt, rest.join(' ')));
				return;
			}
			push({role: 'info', text: `Unknown command: /${cmd} — try /help`});
			return;
		}

		push({role: 'user', text});
		setBusy(true);
		setStatus('thinking');
		bridge.prompt(text);
	};

	if (!ready) {
		return (
			<Box padding={1}>
				<Text color={theme.primary}>Starting CrabKey engine…</Text>
			</Box>
		);
	}

	return (
		<Box flexDirection="column" paddingX={1}>
			{/* Banner + completed messages render once and scroll with the terminal. */}
			<Static items={items}>
				{item => <Message key={item.id} item={item} />}
			</Static>

			<Box flexDirection="column">
				<Prompt
					value={input}
					onChange={setInput}
					onSubmit={handleSubmit}
					disabled={busy}
				/>
				{paletteOpen && (
					<CommandPalette commands={matches} selected={selected} />
				)}
				<StatusBar
					status={status}
					activeTool={activeTool}
					tokensIn={tokens.in}
					tokensOut={tokens.out}
					model={ready.model}
					session={session}
					thread={thread}
				/>
			</Box>
		</Box>
	);
}
