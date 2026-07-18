'use strict';

/* ══ AGENT STORE CHAT ══ */
let _agentHistory = [];

async function renderAgent() {
  document.getElementById('main-content').innerHTML = `
    <div class="view-header">
      <div class="view-title">&#129302; AI Assistant</div>
      <div class="view-sub">Chat assistant running on your local model (borrows whatever's loaded). Ask questions or for help using the store.</div>
      <button class="btn-sm" style="margin-top:6px;" onclick="_agentHistory=[];renderAgent()">&#128465; Clear Chat</button>
    </div>
    <div class="agent-chat" id="agent-chat">
      <div class="agent-msgs" id="agent-msgs">
        <div class="agent-msg assistant">👋 Hi! I'm your store assistant, running on your local model. Ask me things like:
• How do I publish a design to Printify?
• What does the Network Security tab do?
• Explain how the resale pricing works
• Help me write a product description
Replies can take a bit on large local models — that's normal.</div>
      </div>
      <div class="agent-input-row">
        <textarea id="agent-input" placeholder="Ask anything about the store… (Enter to send, Shift+Enter for newline)" rows="3"></textarea>
        <button class="btn-sm primary" id="agent-send" style="height:60px;min-width:70px;">&#9658; Send</button>
      </div>
    </div>`;

  const input = document.getElementById('agent-input');
  const sendBtn = document.getElementById('agent-send');

  async function sendMessage() {
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';
    appendAgentMsg('user', msg);
    _agentHistory.push({ role: 'user', content: msg });
    sendBtn.disabled = true;
    const thinkingEl = appendAgentMsg('thinking', '⏳ Thinking…');
    try {
      const resp = await fetch(API + '/api/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, session_key: 'store-dashboard' })
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || 'Request failed');
      }
      const data = await resp.json();
      thinkingEl?.remove();
      appendAgentMsg('assistant', data.reply || '(no reply)');
      _agentHistory.push({ role: 'assistant', content: data.reply || '' });
    } catch(e) {
      thinkingEl?.remove();
      appendAgentMsg('assistant', '❌ Error: ' + e.message);
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  // Re-render previous history
  if (_agentHistory.length) {
    document.getElementById('agent-msgs').innerHTML = '';
    for (const m of _agentHistory) appendAgentMsg(m.role, m.content);
  }
}

function appendAgentMsg(role, text) {
  const msgs = document.getElementById('agent-msgs');
  if (!msgs) return null;
  const div = document.createElement('div');
  div.className = 'agent-msg ' + role;
  div.textContent = text;
  msgs.appendChild(div);
  msgs.scrollTop = msgs.scrollHeight;
  return div;
}
