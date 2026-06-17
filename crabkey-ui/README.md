# CrabKey UI - Terminal Frontend

A professional terminal UI for CrabKey built with **Ink** (React for the Terminal) and TypeScript.

## Architecture

This is the frontend layer for CrabKey. It communicates with the Python backend via WebSocket/JSON-RPC, similar to how the Hermes TUI gateway works.

```
┌─────────────────────┐
│   CrabKey UI        │  (TypeScript + Ink + React)
│   (This folder)     │
└──────────┬──────────┘
           │ WebSocket/JSON-RPC
           ▼
┌─────────────────────┐
│  CrabKey Backend    │  (Python)
│  crabkey/           │
└─────────────────────┘
```

## Setup

### Prerequisites
- Node.js 18+ and npm
- Python 3.11+ with CrabKey installed

### Install Dependencies

```bash
cd crabkey-ui
npm install
```

### Development

Start the development server:

```bash
npm run dev
```

This watches for file changes and automatically reloads.

### Build

```bash
npm run build
```

Creates optimized bundle in `dist/`.

## Project Structure

```
crabkey-ui/
├── src/
│   ├── entry.tsx              # Entry point
│   ├── app.tsx                # Main App component
│   ├── components/
│   │   ├── AppLayout.tsx      # Main layout container
│   │   ├── SessionDetails.tsx # Session info panel
│   │   ├── ChatMessage.tsx    # Message display
│   │   └── ChatInput.tsx      # Input box
│   ├── app/                   # App-level state and hooks
│   └── lib/                   # Utilities and helpers
├── package.json
├── tsconfig.json
└── README.md
```

## Technologies

- **Ink** - React for terminal UIs
- **React** - Component framework
- **TypeScript** - Type safety
- **nanostores** - State management (when needed)
- **ink-text-input** - Text input component

## Next Steps

1. ✅ Basic Ink app structure with components
2. ⏳ Connect to Python backend via WebSocket
3. ⏳ Implement state management (nanostores)
4. ⏳ Build out remaining UI components
5. ⏳ Add message persistence and threading
6. ⏳ Implement slash commands
