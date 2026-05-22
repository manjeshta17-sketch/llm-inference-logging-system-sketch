let activeConversationId = null;
let conversations = [];
let cancelRequested = false;
let charts = {};

const conversationList = document.getElementById('conversationList');
const messages = document.getElementById('messages');
const conversationTitle = document.getElementById('conversationTitle');
const conversationStatus = document.getElementById('conversationStatus');
const chatForm = document.getElementById('chatForm');
const messageInput = document.getElementById('messageInput');
const providerSelect = document.getElementById('providerSelect');
const modelInput = document.getElementById('modelInput');
const newConversationButton = document.getElementById('newConversationButton');
const cancelButton = document.getElementById('cancelButton');
const resumeButton = document.getElementById('resumeButton');

function escapeHtml(text) {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderConversations() {
  if (!conversationList) return;
  conversationList.innerHTML = conversations.map((conversation) => `
    <button class="conversation-item ${conversation.id === activeConversationId ? 'active' : ''}" data-id="${conversation.id}">
      <div class="panel-title">${escapeHtml(conversation.title)}</div>
      <div class="meta-label">${escapeHtml(conversation.provider)} / ${escapeHtml(conversation.model)}</div>
      <div class="meta-label">${escapeHtml(conversation.status)}</div>
    </button>
  `).join('');

  conversationList.querySelectorAll('.conversation-item').forEach((button) => {
    button.addEventListener('click', async () => {
      await selectConversation(button.dataset.id);
    });
  });
}

function renderMessages(items) {
  if (!messages) return;
  messages.innerHTML = items.map((message) => `
    <div class="message ${message.role}">
      <div class="meta-label">${escapeHtml(message.role)}</div>
      <div>${escapeHtml(message.content)}</div>
    </div>
  `).join('');
  messages.scrollTop = messages.scrollHeight;
}

async function loadConversations() {
  const response = await fetch('/api/conversations');
  const data = await response.json();
  conversations = data.items || [];
  renderConversations();
  if (!activeConversationId && conversations.length > 0) {
    await selectConversation(conversations[0].id);
  }
}

async function loadMessages(conversationId) {
  const response = await fetch(`/api/conversations/${conversationId}/messages`);
  const data = await response.json();
  renderMessages(data.items || []);
}

async function selectConversation(conversationId) {
  activeConversationId = conversationId;
  const conversation = conversations.find((item) => item.id === conversationId);
  if (conversationTitle) {
    conversationTitle.textContent = conversation ? conversation.title : conversationId;
  }
  if (conversationStatus) {
    conversationStatus.textContent = conversation ? conversation.status : 'active';
  }
  renderConversations();
  await loadMessages(conversationId);
}

async function createConversation() {
  const provider = providerSelect?.value || 'mock';
  const model = modelInput?.value || 'mock-chat';
  const response = await fetch('/api/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'New conversation', provider, model }),
  });
  const conversation = await response.json();
  conversations.unshift(conversation);
  await selectConversation(conversation.id);
  renderConversations();
}

async function sendMessage(content) {
  if (!activeConversationId) {
    await createConversation();
  }

  const conversation = conversations.find((item) => item.id === activeConversationId);
  const priorMessages = await fetchMessages(activeConversationId);
  const userMessage = { role: 'user', content };
  const assistantMessage = { role: 'assistant', content: '' };
  renderMessages([...priorMessages, userMessage, assistantMessage]);

  const response = await fetch(`/api/conversations/${activeConversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });

  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(error.detail || 'Request failed');
  }

  if (conversationStatus) {
    conversationStatus.textContent = 'streaming';
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let assistantText = '';
  let rendered = false;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    if (cancelRequested) {
      await reader.cancel();
      break;
    }
    assistantText += decoder.decode(value, { stream: true });
    rendered = true;
    renderMessages([...priorMessages, userMessage, { role: 'assistant', content: assistantText }]);
  }

  if (!rendered) {
    renderMessages([...priorMessages, userMessage, { role: 'assistant', content: assistantText }]);
  }

  cancelRequested = false;
  await loadConversations();
  await loadMessages(activeConversationId);
  if (conversationStatus) {
    conversationStatus.textContent = conversation ? conversation.status : 'active';
  }
}

async function fetchMessages(conversationId) {
  const response = await fetch(`/api/conversations/${conversationId}/messages`);
  const data = await response.json();
  return data.items || [];
}

async function refreshConversationStatus() {
  if (!activeConversationId) return;
  const response = await fetch(`/api/conversations/${activeConversationId}`);
  if (!response.ok) return;
  const conversation = await response.json();
  if (conversationStatus) {
    conversationStatus.textContent = conversation.status;
  }
  conversations = conversations.map((item) => (item.id === conversation.id ? conversation : item));
  renderConversations();
}

async function cancelConversation() {
  if (!activeConversationId) return;
  cancelRequested = true;
  await fetch(`/api/conversations/${activeConversationId}/cancel`, { method: 'POST' });
  await loadConversations();
  await refreshConversationStatus();
}

async function resumeConversation() {
  if (!activeConversationId) return;
  await fetch(`/api/conversations/${activeConversationId}/resume`, { method: 'POST' });
  await loadConversations();
  await refreshConversationStatus();
}

async function loadDashboard() {
  if (!document.getElementById('summaryCards')) return;
  const response = await fetch('/api/dashboard/summary');
  const data = await response.json();
  const totals = data.totals || {};
  const summaryCards = document.getElementById('summaryCards');
  summaryCards.innerHTML = [
    ['Logs', totals.total_logs || 0],
    ['Successes', totals.successes || 0],
    ['Errors', totals.errors || 0],
    ['Avg latency', `${Math.round(totals.avg_latency || 0)} ms`],
  ].map(([label, value]) => `<div><div class="meta-label">${label}</div><h2>${value}</h2></div>`).join('');

  const throughput = data.latency_points || [];
  const providers = data.by_provider || [];
  if (charts.throughput) charts.throughput.destroy();
  if (charts.provider) charts.provider.destroy();

  charts.throughput = new Chart(document.getElementById('throughputChart'), {
    type: 'line',
    data: {
      labels: throughput.map((item) => item.hour_bucket),
      datasets: [{
        label: 'Requests',
        data: throughput.map((item) => item.count),
        borderColor: '#7c3aed',
        backgroundColor: 'rgba(124, 58, 237, 0.15)',
        fill: true,
        tension: 0.35,
      }],
    },
    options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#95a3bc' } }, y: { ticks: { color: '#95a3bc' } } } },
  });

  charts.provider = new Chart(document.getElementById('providerChart'), {
    type: 'doughnut',
    data: {
      labels: providers.map((item) => item.provider),
      datasets: [{
        data: providers.map((item) => item.count),
        backgroundColor: ['#7c3aed', '#22c55e', '#38bdf8', '#f97316'],
      }],
    },
    options: { plugins: { legend: { labels: { color: '#e5eefc' } } } },
  });

  const recentLogs = document.getElementById('recentLogs');
  if (recentLogs) {
    recentLogs.innerHTML = (data.recent_logs || []).map((log) => `
      <div class="log-row">
        <div class="meta-label">${escapeHtml(log.provider)} / ${escapeHtml(log.model)} / ${escapeHtml(log.status)}</div>
        <div>${escapeHtml(log.request_id)} · ${escapeHtml(String(log.latency_ms || 0))} ms · ${escapeHtml(log.created_at)}</div>
      </div>
    `).join('');
  }
}

if (newConversationButton) {
  newConversationButton.addEventListener('click', createConversation);
}
if (cancelButton) {
  cancelButton.addEventListener('click', cancelConversation);
}
if (resumeButton) {
  resumeButton.addEventListener('click', resumeConversation);
}
if (chatForm) {
  chatForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const content = messageInput.value.trim();
    if (!content) return;
    messageInput.value = '';
    try {
      await sendMessage(content);
    } catch (error) {
      alert(error.message);
    }
  });
}

(async function bootstrap() {
  if (window.__INITIAL_CONVERSATIONS__) {
    conversations = window.__INITIAL_CONVERSATIONS__;
    renderConversations();
    if (conversations.length > 0) {
      await selectConversation(conversations[0].id);
    }
  } else {
    await loadConversations();
  }
  await loadDashboard();
})();
