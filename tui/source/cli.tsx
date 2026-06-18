#!/usr/bin/env node
import React from 'react';
import {render} from 'ink';
import {App} from './App.js';

if (!process.stdin.isTTY) {
	console.error(
		'CrabKey TUI requires an interactive terminal. Run it directly in your shell.',
	);
	process.exit(1);
}

const {waitUntilExit} = render(<App />, {exitOnCtrlC: true});
await waitUntilExit();
