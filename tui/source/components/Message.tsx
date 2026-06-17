import React from 'react';
import {Box, Text} from 'ink';
import {theme} from '../theme.js';
import {Markdown} from '../markdown.js';
import {Banner} from './Banner.js';

export type ChatItem =
	| {id: number; role: 'user'; text: string}
	| {id: number; role: 'assistant'; text: string}
	| {id: number; role: 'error'; text: string}
	| {id: number; role: 'info'; text: string}
	| {id: number; role: 'banner'; provider: string; model: string; cwd: string}
	| {
			id: number;
			role: 'tool';
			tool: string;
			args: string;
			result?: string;
			isError?: boolean;
	  };

function summarize(text: string, max = 240): string {
	const oneLine = text.replace(/\s+/g, ' ').trim();
	return oneLine.length > max ? oneLine.slice(0, max) + '…' : oneLine;
}

export function Message({item}: {item: ChatItem}): React.ReactElement {
	if (item.role === 'banner') {
		return <Banner provider={item.provider} model={item.model} cwd={item.cwd} />;
	}

	if (item.role === 'user') {
		return (
			<Box marginBottom={1}>
				<Text color={theme.user} bold>
					{'❯ '}
				</Text>
				<Text color={theme.user}>{item.text}</Text>
			</Box>
		);
	}

	if (item.role === 'assistant') {
		return (
			<Box marginBottom={1} flexDirection="row">
				<Text color={theme.primary} bold>
					{'🦀 '}
				</Text>
				<Box flexDirection="column">
					<Markdown content={item.text} />
				</Box>
			</Box>
		);
	}

	if (item.role === 'error') {
		return (
			<Box
				marginBottom={1}
				borderStyle="round"
				borderColor={theme.error}
				paddingX={1}
			>
				<Text color={theme.error}>{'✗ '}</Text>
				<Text color={theme.error}>{item.text}</Text>
			</Box>
		);
	}

	if (item.role === 'info') {
		return (
			<Box marginBottom={1}>
				<Text color={theme.muted}>{item.text}</Text>
			</Box>
		);
	}

	// tool
	const args = summarize(item.args, 80);
	return (
		<Box marginBottom={1} flexDirection="column">
			<Box>
				<Text color={theme.tool} bold>
					{'⚙ '}
				</Text>
				<Text color={theme.tool}>{item.tool}</Text>
				<Text color={theme.dim}>{`(${args})`}</Text>
			</Box>
			{item.result === undefined ? null : (
				<Box marginLeft={2}>
					<Text color={item.isError ? theme.error : theme.toolResult}>
						{item.isError ? '✗ ' : '↳ '}
					</Text>
					<Text color={item.isError ? theme.error : theme.dim}>
						{summarize(item.result)}
					</Text>
				</Box>
			)}
		</Box>
	);
}
