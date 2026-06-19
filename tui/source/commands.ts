/**
 * Slash commands available in the TUI, plus a fuzzy/substring filter used to
 * drive the command palette (type `/` to see all, keep typing to narrow).
 */

export type SlashCommand = {
	name: string;
	description: string;
};

export const SLASH_COMMANDS: SlashCommand[] = [
	{name: 'help', description: 'Show available commands and tips'},
	{name: 'session', description: 'Manage sessions: new | list | switch <name>'},
	{name: 'thread', description: 'Manage threads: new | list | exit'},
	{name: 'clear', description: 'Clear the conversation'},
	{name: 'quit', description: 'Exit CrabKey'},
];

/**
 * Return the commands matching `query` (the text typed after the leading `/`).
 * An empty query returns everything; otherwise it's a case-insensitive substring
 * match on the command name, so typing narrows the list like a search.
 */
export function filterCommands(
	query: string,
	commands: SlashCommand[] = SLASH_COMMANDS,
): SlashCommand[] {
	const q = query.trim().toLowerCase();
	if (q === '') return commands;
	return commands.filter(c => c.name.toLowerCase().includes(q));
}

/** Substitute user args into a custom command template (mirrors the Python side). */
export function expand(template: string, args: string): string {
	if (template.includes('{{args}}')) return template.replaceAll('{{args}}', args);
	return args ? `${template}\n\n${args}` : template;
}
