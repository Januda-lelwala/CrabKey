import React from 'react';
import {Box, Text} from 'ink';
import Gradient from 'ink-gradient';
import BigText from 'ink-big-text';
import {brandGradient, theme} from '../theme.js';

type Props = {
	provider: string;
	model: string;
	cwd: string;
};

export function Banner({provider, model, cwd}: Props): React.ReactElement {
	const home = process.env['HOME'] ?? '';
	const prettyCwd = home && cwd.startsWith(home) ? '~' + cwd.slice(home.length) : cwd;

	return (
		<Box flexDirection="column" marginBottom={1}>
			<Gradient colors={brandGradient}>
				<BigText text="CrabKey" font="tiny" />
			</Gradient>
			<Box marginTop={-1} marginLeft={1} flexDirection="column">
				<Text color={theme.muted}>
					{'🦀 '}
					<Text color={theme.accent}>model-agnostic agentic coding</Text>
				</Text>
				<Text color={theme.muted}>
					{'   '}
					<Text color={theme.primary}>{provider}</Text>
					{' · '}
					<Text color={theme.assistant}>{model}</Text>
					{'  '}
					<Text color={theme.dim}>{prettyCwd}</Text>
				</Text>
			</Box>
			<Box marginTop={1} marginLeft={1}>
				<Text color={theme.dim}>
					Type a message and press <Text color={theme.accent}>↵</Text>. Slash
					commands: <Text color={theme.accent}>/help</Text>{' '}
					<Text color={theme.accent}>/clear</Text>{' '}
					<Text color={theme.accent}>/quit</Text>
				</Text>
			</Box>
		</Box>
	);
}
