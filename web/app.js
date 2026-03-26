const CONFIG_ENDPOINT = "/api/config";
const HISTORY_ENDPOINT = "/api/history";
const CHAT_ENDPOINT = "/api/chat";
const IMAGE_ENDPOINT = "/api/image";
const SUMMARIZE_ENDPOINT = "/api/summarize";
const REINDEX_ENDPOINT = "/api/reindex";

const SESSION_KEY = "omniquerybot.local.session";
const TRANSCRIPT_PREFIX = "omniquerybot.local.transcript.";

let sessionId = loadOrCreateSessionId();
let transcript = loadTranscript(sessionId);
let latestSources = [];
let selectedImage = null;
let pending = false;

const chatFeed = document.getElementById("chat-feed");
const emptyState = document.getElementById("empty-state");
const runtimeBadges = document.getElementById("runtime-badges");
const sourceList = document.getElementById("source-list");
const actionStatus = document.getElementById("action-status");
const attachmentPreview = document.getElementById("attachment-preview");
const messageInput = document.getElementById("message-input");
const imageInput = document.getElementById("image-input");
const toast = document.getElementById("toast");

document.getElementById("attach-button").addEventListener("click", () => imageInput.click());
document.getElementById("send-button").addEventListener("click", handleSend);
document.getElementById("new-chat-button").addEventListener("click", startNewChat);
document.getElementById("summarize-button").addEventListener("click", summarizeLast);
document.getElementById("reindex-button").addEventListener("click", reindexKnowledgeBase);
imageInput.addEventListener("change", handleImageSelection);
messageInput.addEventListener("keydown", handleComposerKeydown);
messageInput.addEventListener("input", autoResizeTextarea);

for (const button of document.querySelectorAll(".suggestion-chip")) {
  button.addEventListener("click", () => {
    messageInput.value = button.dataset.example || "";
    autoResizeTextarea();
    messageInput.focus();
  });
}

initialize();


async function initialize() {
  await loadConfig();
  if (transcript.length === 0) {
    transcript = await loadHistoryOrWelcome();
    persistTranscript();
  }
  renderChat();
  renderSources();
  autoResizeTextarea();
}


async function loadConfig() {
  try {
    const response = await fetch(CONFIG_ENDPOINT);
    const config = await response.json();
    runtimeBadges.innerHTML = "";
    runtimeBadges.appendChild(createBadge("Model", config.model));
    runtimeBadges.appendChild(createBadge("Top K", String(config.top_k)));
    runtimeBadges.appendChild(createBadge("History", String(config.history_window)));
    runtimeBadges.appendChild(createBadge("Knowledge Base", config.knowledge_base));
  } catch (error) {
    showToast("Failed to load runtime config.");
  }
}


async function loadHistoryOrWelcome() {
  try {
    const response = await fetch(`${HISTORY_ENDPOINT}?session_id=${encodeURIComponent(sessionId)}`);
    const payload = await response.json();
    if (Array.isArray(payload.messages) && payload.messages.length > 0) {
      return payload.messages.map((message) => ({
        id: createMessageId(),
        role: message.role,
        kind: message.kind || "ask",
        content: message.content,
      }));
    }
  } catch (error) {
    showToast("History sync failed. Starting a fresh chat.");
  }
  return [welcomeMessage()];
}


async function handleSend() {
  if (pending) {
    return;
  }

  const message = messageInput.value.trim();
  const imageFile = selectedImage;
  if (!message && !imageFile) {
    return;
  }

  messageInput.value = "";
  autoResizeTextarea();

  if (imageFile) {
    await sendImage(imageFile);
    clearSelectedImage();
  }

  if (message) {
    await sendTextMessage(message);
  }
}


async function sendTextMessage(message) {
  transcript.push({
    id: createMessageId(),
    role: "user",
    kind: "ask",
    content: message,
  });
  const typingId = addTypingBubble();

  persistTranscript();
  renderChat();
  setPending(true, "Thinking...");

  try {
    const response = await fetch(CHAT_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Text request failed.");
    }

    latestSources = Array.isArray(payload.sources) ? payload.sources : [];
    replaceTypingBubble(typingId, {
      id: createMessageId(),
      role: "assistant",
      kind: "ask",
      content: payload.reply,
    });
    renderSources();
  } catch (error) {
    replaceTypingBubble(typingId, errorMessage(error.message));
  } finally {
    setPending(false, "Ready.");
  }
}


async function sendImage(file) {
  const dataUrl = await fileToDataUrl(file);
  transcript.push({
    id: createMessageId(),
    role: "user",
    kind: "image",
    content: file.name,
    imageUrl: dataUrl,
  });
  const typingId = addTypingBubble();
  persistTranscript();
  renderChat();
  setPending(true, "Describing image...");

  const formData = new FormData();
  formData.append("session_id", sessionId);
  formData.append("file", file);

  try {
    const response = await fetch(IMAGE_ENDPOINT, {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Image request failed.");
    }

    replaceTypingBubble(typingId, {
      id: createMessageId(),
      role: "assistant",
      kind: "image",
      content: payload.reply,
      tags: payload.tags || [],
    });
  } catch (error) {
    replaceTypingBubble(typingId, errorMessage(error.message));
  } finally {
    setPending(false, "Ready.");
  }
}


async function summarizeLast() {
  if (pending) {
    return;
  }

  const typingId = addTypingBubble();
  renderChat();
  setPending(true, "Summarizing...");

  try {
    const response = await fetch(SUMMARIZE_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Summarize request failed.");
    }

    replaceTypingBubble(typingId, {
      id: createMessageId(),
      role: "assistant",
      kind: "summary",
      content: payload.reply,
    });
  } catch (error) {
    replaceTypingBubble(typingId, errorMessage(error.message));
  } finally {
    setPending(false, "Ready.");
  }
}


async function reindexKnowledgeBase() {
  if (pending) {
    return;
  }
  setPending(true, "Reindexing knowledge base...");
  try {
    const response = await fetch(REINDEX_ENDPOINT, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Reindex failed.");
    }
    const stats = payload.stats || {};
    actionStatus.textContent =
      `Indexed ${stats.files_seen || 0} files, refreshed ${stats.files_reindexed || 0}, wrote ${stats.chunks_written || 0} chunks.`;
    showToast("Knowledge base refreshed.");
  } catch (error) {
    actionStatus.textContent = error.message;
    showToast(error.message);
  } finally {
    setPending(false, actionStatus.textContent);
  }
}


function startNewChat() {
  sessionId = createSessionId();
  localStorage.setItem(SESSION_KEY, sessionId);
  transcript = [welcomeMessage()];
  latestSources = [];
  clearSelectedImage();
  persistTranscript();
  renderChat();
  renderSources();
  actionStatus.textContent = "Started a fresh local session.";
  showToast("New chat ready.");
}


function handleImageSelection(event) {
  const [file] = event.target.files || [];
  if (!file) {
    clearSelectedImage();
    return;
  }
  if (!file.type.startsWith("image/")) {
    showToast("Please choose a valid image file.");
    clearSelectedImage();
    return;
  }
  selectedImage = file;
  renderSelectedImage();
}


function handleComposerKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    handleSend();
  }
}


function addTypingBubble() {
  const typingMessage = {
    id: createMessageId(),
    role: "assistant",
    kind: "typing",
    content: "",
    typing: true,
  };
  transcript.push(typingMessage);
  persistTranscript();
  return typingMessage.id;
}


function replaceTypingBubble(typingId, nextMessage) {
  transcript = transcript.map((message) => (message.id === typingId ? nextMessage : message));
  persistTranscript();
  renderChat();
}


function renderChat() {
  chatFeed.innerHTML = "";
  const visibleMessages = transcript.filter((message) => message.content || message.typing);
  emptyState.style.display = visibleMessages.length > 1 ? "none" : "block";

  for (const message of visibleMessages) {
    const row = document.createElement("article");
    row.className = `message-row ${message.role}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const role = document.createElement("div");
    role.className = "message-role";
    role.textContent = message.role === "user" ? "You" : "OmniQueryBot";
    bubble.appendChild(role);

    if (message.typing) {
      const typing = document.createElement("div");
      typing.className = "typing-dots";
      typing.innerHTML = "<span></span><span></span><span></span>";
      bubble.appendChild(typing);
    } else {
      const body = document.createElement("div");
      body.className = "message-body";
      body.textContent = message.content;
      bubble.appendChild(body);

      if (message.imageUrl) {
        const image = document.createElement("img");
        image.className = "message-image";
        image.src = message.imageUrl;
        image.alt = message.content || "Uploaded image";
        bubble.appendChild(image);
      }

      if (Array.isArray(message.tags) && message.tags.length > 0) {
        const tags = document.createElement("div");
        tags.className = "message-tags";
        for (const tag of message.tags) {
          const pill = document.createElement("span");
          pill.className = "message-tag";
          pill.textContent = tag;
          tags.appendChild(pill);
        }
        bubble.appendChild(tags);
      }
    }

    row.appendChild(bubble);
    chatFeed.appendChild(row);
  }

  window.requestAnimationFrame(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  });
}


function renderSources() {
  sourceList.innerHTML = "";
  if (latestSources.length === 0) {
    sourceList.className = "source-list empty-state-copy";
    sourceList.textContent = "Ask a question to inspect the matching chunks.";
    return;
  }

  sourceList.className = "source-list";
  for (const source of latestSources) {
    const card = document.createElement("div");
    card.className = "source-card";

    const topLine = document.createElement("div");
    topLine.className = "source-topline";

    const title = document.createElement("div");
    title.className = "source-title";
    title.textContent = `${source.file_name} / ${source.heading}`;

    const score = document.createElement("div");
    score.className = "source-score";
    score.textContent = `score ${source.score}`;

    topLine.appendChild(title);
    topLine.appendChild(score);
    card.appendChild(topLine);

    const snippet = document.createElement("div");
    snippet.className = "source-snippet";
    snippet.textContent = source.snippet;
    card.appendChild(snippet);
    sourceList.appendChild(card);
  }
}


async function renderSelectedImage() {
  if (!selectedImage) {
    attachmentPreview.classList.add("hidden");
    attachmentPreview.innerHTML = "";
    return;
  }

  const dataUrl = await fileToDataUrl(selectedImage);
  attachmentPreview.classList.remove("hidden");
  attachmentPreview.innerHTML = `
    <div class="preview-card">
      <img src="${dataUrl}" alt="${escapeHtml(selectedImage.name)}" />
      <div>
        <div class="preview-name">${escapeHtml(selectedImage.name)}</div>
        <div class="preview-meta">Image queued for captioning in this chat.</div>
      </div>
      <button class="remove-preview" type="button">Remove</button>
    </div>
  `;
  attachmentPreview.querySelector(".remove-preview").addEventListener("click", clearSelectedImage);
}


function clearSelectedImage() {
  selectedImage = null;
  imageInput.value = "";
  attachmentPreview.classList.add("hidden");
  attachmentPreview.innerHTML = "";
}


function setPending(isPending, statusText) {
  pending = isPending;
  actionStatus.textContent = statusText;
  document.getElementById("send-button").disabled = isPending;
  document.getElementById("summarize-button").disabled = isPending;
  document.getElementById("reindex-button").disabled = isPending;
  document.getElementById("new-chat-button").disabled = isPending;
}


function persistTranscript() {
  localStorage.setItem(`${TRANSCRIPT_PREFIX}${sessionId}`, JSON.stringify(transcript));
}


function loadTranscript(currentSessionId) {
  const raw = localStorage.getItem(`${TRANSCRIPT_PREFIX}${currentSessionId}`);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}


function loadOrCreateSessionId() {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) {
    return existing;
  }
  const next = createSessionId();
  localStorage.setItem(SESSION_KEY, next);
  return next;
}


function createSessionId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `local-${window.crypto.randomUUID()}`;
  }
  return `local-${Date.now()}`;
}


function createMessageId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `message-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


function welcomeMessage() {
  return {
    id: createMessageId(),
    role: "assistant",
    kind: "system",
    content:
      "Ask about the local knowledge base, attach an image in the composer, or summarize the latest interaction from the sidebar.",
  };
}


function errorMessage(content) {
  return {
    id: createMessageId(),
    role: "assistant",
    kind: "error",
    content,
  };
}


function createBadge(label, value) {
  const badge = document.createElement("div");
  badge.className = "badge";
  badge.innerHTML = `
    <div class="badge-key">${escapeHtml(label)}</div>
    <div class="badge-value">${escapeHtml(value)}</div>
  `;
  return badge;
}


function autoResizeTextarea() {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 180)}px`;
}


function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Image preview failed."));
    reader.readAsDataURL(file);
  });
}


function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  window.clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    toast.classList.add("hidden");
  }, 2600);
}


function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
