/**
 * Minimal, dependency-free markdown renderer for the terminal.
 *
 * Handles the constructs that actually show up in coding-assistant replies:
 * fenced code blocks, headings, bullet/numbered lists, blockquotes, and the
 * inline run of **bold**, *italic*, `code`. It is deliberately small — good
 * enough to read like prose, not a spec-complete parser.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {theme} from './theme.js';

type Segment =
	| {kind: 'text'; value: string}
	| {kind: 'bold'; value: string}
	| {kind: 'italic'; value: string}
	| {kind: 'code'; value: string};

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;

function parseInline(line: string): Segment[] {
	const segments: Segment[] = [];
	let lastIndex = 0;
	for (const match of line.matchAll(INLINE)) {
		const index = match.index ?? 0;
		if (index > lastIndex) {
			segments.push({kind: 'text', value: line.slice(lastIndex, index)});
		}
		const token = match[0];
		if (token.startsWith('**')) {
			segments.push({kind: 'bold', value: token.slice(2, -2)});
		} else if (token.startsWith('`')) {
			segments.push({kind: 'code', value: token.slice(1, -1)});
		} else {
			segments.push({kind: 'italic', value: token.slice(1, -1)});
		}
		lastIndex = index + token.length;
	}
	if (lastIndex < line.length) {
		segments.push({kind: 'text', value: line.slice(lastIndex)});
	}
	return segments;
}

function Inline({line}: {line: string}): React.ReactElement {
	return (
		<Text color={theme.assistant}>
			{parseInline(line).map((seg, i) => {
				if (seg.kind === 'bold') return <Text key={i} bold>{seg.value}</Text>;
				if (seg.kind === 'italic') return <Text key={i} italic>{seg.value}</Text>;
				if (seg.kind === 'code') return <Text key={i} color={theme.accent} backgroundColor="#1F2335">{` ${seg.value} `}</Text>;
				return <Text key={i}>{seg.value}</Text>;
			})}
		</Text>
	);
}

function CodeBlock({code, lang}: {code: string; lang: string}): React.ReactElement {
	return (
		<Box
			flexDirection="column"
			borderStyle="round"
			borderColor={theme.border}
			paddingX={1}
			marginY={0}
		>
			{lang ? <Text color={theme.muted}>{lang}</Text> : null}
			{code.split('\n').map((line, i) => (
				<Text key={i} color={theme.code}>
					{line || ' '}
				</Text>
			))}
		</Box>
	);
}

export function Markdown({content}: {content: string}): React.ReactElement {
	const blocks: React.ReactElement[] = [];
	const lines = content.replace(/\r\n/g, '\n').split('\n');

	let i = 0;
	let key = 0;
	while (i < lines.length) {
		const line = lines[i] ?? '';

		// Fenced code block
		const fence = line.match(/^```(\w*)\s*$/);
		if (fence) {
			const lang = fence[1] ?? '';
			const buf: string[] = [];
			i++;
			while (i < lines.length && !/^```\s*$/.test(lines[i] ?? '')) {
				buf.push(lines[i] ?? '');
				i++;
			}
			i++; // skip closing fence
			blocks.push(<CodeBlock key={key++} code={buf.join('\n')} lang={lang} />);
			continue;
		}

		// Heading
		const heading = line.match(/^(#{1,4})\s+(.*)$/);
		if (heading) {
			blocks.push(
				<Text key={key++} color={theme.primary} bold>
					{heading[2]}
				</Text>,
			);
			i++;
			continue;
		}

		// Blockquote
		if (line.startsWith('> ')) {
			blocks.push(
				<Text key={key++} color={theme.muted} italic>
					{'▏ '}
					{line.slice(2)}
				</Text>,
			);
			i++;
			continue;
		}

		// Bullet list
		const bullet = line.match(/^\s*[-*]\s+(.*)$/);
		if (bullet) {
			blocks.push(
				<Box key={key++}>
					<Text color={theme.primary}>{'  • '}</Text>
					<Inline line={bullet[1] ?? ''} />
				</Box>,
			);
			i++;
			continue;
		}

		// Numbered list
		const numbered = line.match(/^\s*(\d+)\.\s+(.*)$/);
		if (numbered) {
			blocks.push(
				<Box key={key++}>
					<Text color={theme.primary}>{`  ${numbered[1]}. `}</Text>
					<Inline line={numbered[2] ?? ''} />
				</Box>,
			);
			i++;
			continue;
		}

		// Blank line → small spacer
		if (line.trim() === '') {
			blocks.push(<Text key={key++}> </Text>);
			i++;
			continue;
		}

		blocks.push(<Inline key={key++} line={line} />);
		i++;
	}

	return <Box flexDirection="column">{blocks}</Box>;
}
