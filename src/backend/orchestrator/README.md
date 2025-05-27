# Orchestrator Backend Overview

This backend orchestrates real-time audio and text translation using Azure OpenAI, Azure Communication Services (ACS), and Event Grid. It manages user sessions, WebSocket audio streaming, ACS call automation events, and coordinates translation using the Command and Observer patterns.

## Application Lifecycle and Lifespan Logic

The application uses FastAPI's `lifespan` context to manage global resources and background tasks:

- **room_user_observer**: A singleton observer instance is created for the entire app. It manages all rooms, users, ACS calls, and translation invokers.
- **Background Tasks**:
  - `resource_cleanup_task`: Runs every 60 seconds. It checks all active ACS sessions (using `room_user_observer._connection_session` as the source of truth). If a session is inactive (no audio/video for 5+ minutes), it unregisters the websocket, removes the session, and hangs up the ACS call to avoid extra spend.
  - `translation_orchestration_task`: Runs every second. It supervises all active translation invoker tasks, restarting any that are missing or have crashed.
- On shutdown, both background tasks are cancelled and awaited for graceful cleanup.

## WebSocket Endpoint and Bot Awareness

The `/ws` endpoint handles real-time audio streaming. For full integration with ACS calls and the Interpreter bot:
- The websocket should be registered with the observer and associated with the correct ACS call and session. This allows the translation invoker to route audio/events to the correct websocket and bot.
- (If not yet implemented, update the `/ws` logic to register the websocket with `room_user_observer.register_websocket(session_id, websocket)` and map the call connection.)

## Incoming Call Handling and Bot Orchestration

- The `/incoming-call` endpoint receives Event Grid events for new ACS calls.
  - It answers the call, registers the call in the observer, and pre-registers an Interpreter bot for the room/call.
  - The call connection is mapped to the session for later lookup.
- The `/callbacks/{contextId}` endpoint receives ACS callback events (e.g., CallConnected, MediaStreamingStarted).
  - On `CallConnected`, it adds the bot as a participant and, if a websocket is registered, starts a translation invoker for the call.

## Session Cleanup Logic

- The cleanup task uses `room_user_observer._connection_session` as the authoritative list of active ACS sessions.
- For each session, it checks the last activity timestamp on the associated websocket.
- If inactive for 5+ minutes, it unregisters the websocket, removes the session, and hangs up the ACS call.
- This ensures orphaned or idle sessions are cleaned up and resources are released both in the app and in ACS.

## Summary Table

| Component                | What it Does                                                                                  | Scope                |
|--------------------------|----------------------------------------------------------------------------------------------|----------------------|
| `lifespan`               | Initializes observer, starts cleanup and translation tasks, manages app lifecycle            | Whole app            |
| `resource_cleanup_task`  | Cleans up inactive ACS sessions, unregisters websockets, hangs up calls                      | All sessions/calls   |
| `translation_orchestration_task` | Supervises translation invokers, restarts if needed                                  | All calls            |
| `/ws` endpoint           | Handles websocket connections, should link to bot/call/session (update if needed)            | Per websocket/client |
| `/incoming-call` handler | Answers ACS calls, registers bot, maps call to session, notifies observer                   | Per ACS call         |
| `/callbacks/{contextId}` | Handles ACS call events, adds bot, starts translation when possible                         | Per ACS call         |

## Recommendations

- Ensure the `/ws` endpoint registers websockets with the observer and associates them with the correct call/session for full orchestration.
- The observer and background tasks ensure robust, scalable, and cost-effective management of all translation and call resources.
