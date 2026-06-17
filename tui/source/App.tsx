import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Box, Static, Text, useApp, useInput} from 'ink';
import {Bridge, type BridgeEvent, type ReadyEvent} from './backend.js';
import {Message, type ChatItem} from './components/Message.js';
import {Prompt} from './components/Prompt.js';
import {StatusBar} from './components/StatusBar.js';
import {theme} from './theme.js';

type Status = 'idle' | 'thinking' | 'tool';

// Omit must distribute over the ChatItem union so each variant keeps its keys.
type NewChatItem = ChatItem extends infer T
	? T extends {id: number}
		? Omit<T, 'id'>
		: never
	: never;

const HELP = [
	'Slash commands:',
	'  /help          show this help',
	'  /clear         clear the conversation',
	'  /quit, /exit   leave CrabKey',
	'',
	'Tips: Esc cancels the current input · Ctrl+C exits.',
].join('\n');

export function App(): React.ReactElement {
	const {exit} = useApp();
	const bridge = useMemo(() => new Bridge(), []);
	const nextId = useRef(0);
	const make = () => nextId.current++;

	const [items, setItems] = useState<ChatItem[]>([]);
	const [input, setInput] = useState('');
	const [status, setStatus] = useState<Status>('idle');
	const [activeTool, setActiveTool] = useState<string | undefined>();
	const [busy, setBusy] = useState(false);
	const [ready, setReady] = useState<ReadyEvent | null>(null);
	const [tokens, setTokens] = useState({in: 0, out: 0});

	const push = (item: NewChatItem) =>
		setItems(prev => [...prev, {...item, id: make()} as ChatItem]);

	useEffect(() => {
		const onEvent = (evt: BridgeEvent) => {
			switch (evt.type) {
				case 'ready': {
					const r = evt as unknown as ReadyEvent;
					setReady(r);
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
		if (key.escape && !busy) setInput('');
	});

	const handleSubmit = (raw: string) => {
		const text = raw.trim();
		setInput('');
		if (!text) return;

		if (text.startsWith('/')) {
			const cmd = text.slice(1).toLowerCase();
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
				<StatusBar
					status={status}
					activeTool={activeTool}
					tokensIn={tokens.in}
					tokensOut={tokens.out}
					model={ready.model}
				/>
			</Box>
		</Box>
	);
}
