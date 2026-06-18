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
};

const fmt = (n: number): string =>
	n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

export function StatusBar({
	status,
	activeTool,
	tokensIn,
	tokensOut,
	model,
}: Props): React.ReactElement {
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
			</Box>
			<Box>
				<Text color={theme.dim}>
					{model} · ↑{fmt(tokensIn)} ↓{fmt(tokensOut)} tokens
				</Text>
			</Box>
		</Box>
	);
}
