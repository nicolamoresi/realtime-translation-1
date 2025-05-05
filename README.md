# Real-Time Multilingual Chat & Voice Translation

A cloud-native platform that lets people who speak different languages converse naturally, in real time, by capturing speech, translating on the fly, and rebroadcasting both audio and text back into the same virtual “room.”

## Features

* Multi-language voice & text translation with sub-second latency  
* WebSocket-driven orchestration (FastAPI) and front-end (Next.js)  
* GPT-4o Realtime on Azure AI Foundry for transcription + interpreted audio streams  
* Azure Communication Services for reliable media transport & room management  
* Stateless, auto-scalable containers with in-memory session maps  

## Getting Started

### Prerequisites

- Node.js v14+  
- Python 3.9+  
- Azure Subscription with Communication Services & AI Foundry  

### Installation

1. git clone https://github.com/your-org/realtime-translation.git  
2. cd realtime-translation  
3. npm install            # install front-end dependencies  
4. pip install -r requirements.txt   # install back-end dependencies  

### Quickstart

1. Create `.env.local` in the root and set:  
     • AZURE_COMMUNICATION_CONNECTION_STRING  
     • AZURE_AI_ENDPOINT & AZURE_AI_KEY  
2. Run orchestrator:  
     ```powershell
     cd orchestrator
     uvicorn main:app --host 0.0.0.0 --port 8000
     ```  
3. Start the front-end:  
     ```bash
     cd ../web-ui
     npm run dev
     ```  
4. Open http://localhost:3000, join or create a room, press “P” to speak.

## Demo

A minimal demo is included to illustrate full-stack flow:

1. Ensure both orchestrator and front-end are running.  
2. In two browser tabs, join the same room ID.  
3. Press “P” in one tab, speak; hear interpreted audio & see live transcript in the other tab.  

## Sequence Diagram

![Sequence Diagram](./.assets/sequence%20diagram.png)

**Sequential Chat Flow**  
The first diagram traces a single interpretation cycle. When a user joins a room, the Next.js UI opens audio & text WebSocket channels, tags the session, and renders the chat canvas. The FastAPI orchestrator registers the user in its in-memory map, adds them via Azure Communication Services Rooms API, then buffers incoming PCM until a pause is detected. That chunk is sent to GPT-4o Realtime; translated audio and transcription deltas stream back and are immediately broadcast over the same WebSockets. The UI plays the audio and appends transcript lines to complete one real-time interpreter loop.

**Azure Rooms Service Integration**  
The second diagram highlights the orchestrator’s use of Azure Rooms Service for durable membership and token management. On join, the orchestrator calls the Rooms API to create or retrieve a room, issues time-bound tokens, and enforces permissions. Azure handles WebRTC signaling, NAT traversal, and scalable media endpoints.

**Communication and Orchestration Pipeline**  
The third illustration brings together the static UI, FastAPI orchestrator, GPT-4o Realtime, and Azure Communication Services. The browser captures speech via WebRTC, WebSockets deliver buffered audio to the orchestrator, which debounces and forwards segments to the AI Foundry. The model returns audio and text deltas; the orchestrator multicasts both back to each client. Azure Communication Services underpins signaling, ICE negotiation, and media relay.

**Meeting Controller / Azure Communication Services Orchestration**  
The final diagram positions Azure Communication Services as the call coordinator—issuing tokens, enforcing NAT traversal, and supporting in-call operations. Our Meeting Controller (the orchestrator) brokers authentication, room lifecycle, and AI translation, then injects translated streams into the media plane so every participant hears the interpreted audio.

## Architecture Overview

![C4–C2 Diagram](./.assets/c4%20-%20c2.png)

### Architecture Overview — Real-Time Multilingual Chat & Voice Translation

---

#### Major components

| Layer                             | Technology                                                       | Purpose                                                                                                                                                                          |
| --------------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Chat Room UI**               | Next.js SPA served from Azure Static Web Apps                    | records microphone, renders translated audio/text, opens WebSocket to orchestrator, manages “/username” and “/join” commands                                                     |
| **2. Back-End Orchestrator**      | Containerised FastAPI / Chainlit service on Azure Container Apps | holds per-room maps (`ROOM_EMITTERS`, `USERNAMES`), buffers incoming PCM, detects end-of-utterance, fans out translated streams, maintains WebSocket API consumed by the browser |
| **3. Live Translator**            | GPT-4o-Realtime endpoint (Azure AI Foundry)          | receives buffered audio, runs a strict “interpreter” prompt, streams back translated audio + incremental transcript                                                              |
| **4. Meeting Controller**         | Azure Communication Services (Rooms API + Call Automation)       | issues access tokens, hosts WebRTC media plane, guarantees that every participant’s client can publish/subscribe audio & video at scale                                          |
| **5. Persistent Storage / State** | In-memory dictionaries inside each orchestrator replica          | light-weight: no database in the critical path; rooms are effectively sharded by orchestrator replica                                                                            |

---

#### Strategy for solving the problem

1. **Room-centric session key** – Every browser tab presents a `room_id`. The orchestrator stores a hash-map of `{room_id: {session_id: emitter}}`, so a single broadcast loop fans translated audio/text to every connection in that room without iterating over foreign sessions.

2. **Buffered speech, not raw streaming** – Continuous raw PCM would overload GPT-4o tokens and spike cost. The orchestrator accumulates ~1 MB or 3 s of audio (or until server-side VAD reports silence), then forwards the whole segment to GPT-4o. This shrinks WebSocket chatter and keeps translation coherent.

3. **Horizontal scalability** –
   * **Frontend** is static and can be hosted on any CDN.  
   * **Orchestrator** runs in Container Apps with auto-scale rules on CPU, memory and concurrent WebSocket count. Internal state is per-replica; sticky routing (room-id-based hash) can be added via Revision Traffic if thousands of rooms are expected.  
   * **Live Translator** is fully managed by Azure; each new WebSocket is another GPT-4o session.  
   * **Communication Services** globally distributes TURN/media relay—no custom scaling work needed.

4. **Loose coupling through WebSockets** – The UI, orchestrator and AI translator communicate exclusively through WebSocket protocols, allowing the translation engine to be swapped without touching the browser or Communication Services integration.

5. **Minimal persistent state** – All session data lives in memory and is derived from the client handshake. An orchestrator replica can be killed and replaced instantly; the browser reconnects and re-joins its room with zero manual recovery. Long-lived data (e.g., audit logs) can be streamed to Application Insights or Azure Monitor asynchronously.

6. **Security & isolation** – Rooms Service issues time-bound join tokens; a browser cannot eavesdrop on a room without the token. WebSocket endpoints are protected by the same token and can be fronted by Azure API Management for rate limiting.

7. **Cost control** – GPT-4o Realtime minutes are used only for active speech. Silence detection plus container auto-scale keeps idle cost near zero. Communication Services is billed per active participant-minute, matching actual usage.

With these components in concert, the platform delivers speaker-by-speaker live interpretation, scales horizontally under load, and remains simple to operate: swap container images for new logic, point to a new Azure model deployment for better translation quality, or scale out replicas—all without rewriting the UI or room-management layer.

## Resources

- Azure Communication Services: https://aka.ms/acs  
- Azure AI Foundry & GPT-4o Realtime: https://aka.ms/azure-ai-foundry 
- Sample repository & issue tracker: https://github.com/Azure-Samples/realtime-translation  
- Diagram assets & specs: .assets/
