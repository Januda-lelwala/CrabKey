import React from 'react';
import {Box, Text} from 'ink';
import {theme} from '../theme.js';
import type {SlashCommand} from '../commands.js';

type Props = {
	commands: SlashCommand[];
	selected: number;
};

/**
 * Dropdown shown beneath the prompt while the user is typing a slash command.
 * The selected entry is highlighted; ↑/↓ move it and Enter runs it.
 */
export function CommandPalette({
	commands,
	selected,
}: Props): React.ReactElement {
	if (commands.length === 0) {
		return (
			<Box paddingX={2}>
				<Text color={theme.dim}>No matching commands</Text>
			</Box>
		);
	}

	return (
		<Box flexDirection="column" paddingX={2}>
			{commands.map((cmd, i) => {
				const active = i === selected;
				return (
					<Box key={cmd.name}>
						<Text color={active ? theme.primary : theme.muted} bold={active}>
							{(active ? '❯ ' : '  ') + '/' + cmd.name}
						</Text>
						<Text color={theme.dim}>{'   ' + cmd.description}</Text>
					</Box>
				);
			})}
		</Box>
	);
}
