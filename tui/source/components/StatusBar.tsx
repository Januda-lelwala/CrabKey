import React from 'react';
import {Box, Text} from 'ink';
import Spinner from 'ink-spinner';
import {theme} from '../theme.js';

type Props = {
	status: 'idle' | 'thinking' | 'tool';
	activeTool?: string;
	tokensIn: number;
	tokensOut: number;
	model: string;
	session?: string;
	thread?: string;
};

const fmt = (n: number): string =>
	n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

export function StatusBar({
	status,
	activeTool,
	tokensIn,
	tokensOut,
	model,
	session,
	thread,
}: Props): React.ReactElement {
	const context = [session && `session:${session}`, thread && `thread:${thread}`]
		.filter(Boolean)
		.join(' · ');
	return (
		<Box justifyContent="space-between" paddingX={1}>
			<Box>
				{status === 'idle' ? (
					<Text color={theme.success}>● ready</Text>
				) : (
					<Text color={theme.primary}>
						<Spinner type="dots" />{' '}
						{status === 'tool'
							? `running ${activeTool ?? 'tool'}…`
							: 'thinking…'}
					</Text>
				)}
				{context ? <Text color={theme.dim}>{'  ' + context}</Text> : null}
			</Box>
			<Box>
				<Text color={theme.dim}>
					{model} · ↑{fmt(tokensIn)} ↓{fmt(tokensOut)} tokens
				</Text>
			</Box>
		</Box>
	);
}
