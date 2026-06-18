import React from 'react';
import {Box, Text} from 'ink';
import TextInput from 'ink-text-input';
import {theme} from '../theme.js';

type Props = {
	value: string;
	onChange: (value: string) => void;
	onSubmit: (value: string) => void;
	disabled: boolean;
};

export function Prompt({
	value,
	onChange,
	onSubmit,
	disabled,
}: Props): React.ReactElement {
	return (
		<Box
			borderStyle="round"
			borderColor={disabled ? theme.border : theme.primary}
			paddingX={1}
		>
			<Text color={disabled ? theme.dim : theme.primary} bold>
				{'❯ '}
			</Text>
			{disabled ? (
				<Text color={theme.dim}>{value || 'working…'}</Text>
			) : (
				<TextInput
					value={value}
					onChange={onChange}
					onSubmit={onSubmit}
					placeholder="Ask CrabKey to build, fix, or explain something…"
				/>
			)}
		</Box>
	);
}
