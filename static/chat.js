(function () {
    "use strict";

    let activeConvId = null;
    let sending = false;

    const convList = document.getElementById("conv-list");
    const messagesEl = document.getElementById("chat-messages");
    const welcomeEl = document.getElementById("chat-welcome");
    const inputArea = document.getElementById("chat-input-area");
    const inputEl = document.getElementById("chat-input");
    const sendBtn = document.getElementById("chat-send-btn");
    const newBtn = document.getElementById("new-conv-btn");

    // --- Utilities ---

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function renderMarkdown(text) {
        // Code blocks
        text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
            return "<pre><code>" + escapeHtml(code.trim()) + "</code></pre>";
        });
        // Inline code
        text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
        // Bold
        text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        // Italic
        text = text.replace(/\*(.+?)\*/g, "<em>$1</em>");
        // Headers
        text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>");
        text = text.replace(/^## (.+)$/gm, "<h2>$1</h2>");
        text = text.replace(/^# (.+)$/gm, "<h1>$1</h1>");
        // Unordered lists
        text = text.replace(/^[-*] (.+)$/gm, "<li>$1</li>");
        text = text.replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>");
        // Ordered lists
        text = text.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
        // Paragraphs (simple: double newline)
        text = text.replace(/\n\n/g, "</p><p>");
        // Single newlines to <br> (but not inside pre/code)
        text = text.replace(/\n/g, "<br>");
        return "<p>" + text + "</p>";
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // --- Auto-resize textarea ---

    inputEl.addEventListener("input", function () {
        this.style.height = "auto";
        this.style.height = Math.min(this.scrollHeight, 150) + "px";
    });

    // --- Enter to send, Shift+Enter for newline ---

    inputEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener("click", sendMessage);
    newBtn.addEventListener("click", createConversation);

    // --- Conversation list ---

    convList.addEventListener("click", function (e) {
        const del = e.target.closest(".conv-item-del");
        if (del) {
            e.stopPropagation();
            const item = del.closest(".conv-item");
            deleteConversation(parseInt(item.dataset.id), item);
            return;
        }
        const item = e.target.closest(".conv-item");
        if (item) loadConversation(parseInt(item.dataset.id));
    });

    async function createConversation() {
        const resp = await fetch("/chat/conversations", { method: "POST" });
        const data = await resp.json();
        const li = document.createElement("li");
        li.className = "conv-item";
        li.dataset.id = data.id;
        li.innerHTML =
            '<span class="conv-item-title">' + escapeHtml(data.title) + "</span>" +
            '<button class="conv-item-del" title="Delete">&times;</button>';
        convList.prepend(li);
        loadConversation(data.id);
    }

    async function deleteConversation(id, el) {
        await fetch("/chat/conversations/" + id, { method: "DELETE" });
        el.remove();
        if (activeConvId === id) {
            activeConvId = null;
            showWelcome();
        }
    }

    async function loadConversation(id) {
        activeConvId = id;
        highlightActive();
        messagesEl.innerHTML = "";
        welcomeEl.style.display = "none";
        inputArea.style.display = "flex";
        inputEl.focus();

        const resp = await fetch("/chat/conversations/" + id + "/messages");
        const data = await resp.json();

        data.messages.forEach(function (m) {
            if (m.role === "user") appendUserMsg(m.content);
            else if (m.role === "assistant") appendAssistantMsg(m.content);
            else if (m.role === "tool_call") appendToolCall(m.tool_name, m.content);
            else if (m.role === "tool_result") appendToolResult(m.tool_name, m.content);
        });
        scrollToBottom();
    }

    function highlightActive() {
        convList.querySelectorAll(".conv-item").forEach(function (el) {
            el.classList.toggle("active", parseInt(el.dataset.id) === activeConvId);
        });
    }

    function showWelcome() {
        messagesEl.innerHTML = "";
        messagesEl.appendChild(welcomeEl);
        welcomeEl.style.display = "flex";
        inputArea.style.display = "none";
    }

    // --- Message rendering ---

    function appendUserMsg(text) {
        const div = document.createElement("div");
        div.className = "msg msg-user";
        div.textContent = text;
        messagesEl.appendChild(div);
    }

    function appendAssistantMsg(html) {
        const div = document.createElement("div");
        div.className = "msg msg-assistant";
        div.innerHTML = renderMarkdown(html);
        messagesEl.appendChild(div);
        return div;
    }

    function appendToolCall(name, content) {
        const div = document.createElement("div");
        div.className = "msg-tool";
        div.innerHTML =
            '<div class="msg-tool-header">Tool Call: ' + escapeHtml(name) + "</div>" +
            '<div class="msg-tool-body">' + escapeHtml(content) + "</div>";
        messagesEl.appendChild(div);
    }

    function appendToolResult(name, content) {
        const div = document.createElement("div");
        div.className = "msg-tool";
        div.innerHTML =
            '<div class="msg-tool-header">Result: ' + escapeHtml(name) + "</div>" +
            '<div class="msg-tool-body">' + escapeHtml(content) + "</div>";
        messagesEl.appendChild(div);
    }

    function showTyping() {
        const div = document.createElement("div");
        div.className = "typing-indicator";
        div.id = "typing";
        div.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
        messagesEl.appendChild(div);
        scrollToBottom();
    }

    function hideTyping() {
        const el = document.getElementById("typing");
        if (el) el.remove();
    }

    // --- Send message + SSE streaming ---

    async function sendMessage() {
        if (sending || !activeConvId) return;
        const text = inputEl.value.trim();
        if (!text) return;

        sending = true;
        sendBtn.disabled = true;
        inputEl.value = "";
        inputEl.style.height = "auto";

        appendUserMsg(text);
        scrollToBottom();
        showTyping();

        try {
            const resp = await fetch("/chat/send", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ conversation_id: activeConvId, message: text }),
            });

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let currentAssistantEl = null;
            let currentAssistantText = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop(); // keep incomplete line

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    let evt;
                    try {
                        evt = JSON.parse(line.slice(6));
                    } catch (_) {
                        continue;
                    }

                    if (evt.type === "text") {
                        hideTyping();
                        if (!currentAssistantEl) {
                            currentAssistantEl = document.createElement("div");
                            currentAssistantEl.className = "msg msg-assistant";
                            messagesEl.appendChild(currentAssistantEl);
                        }
                        currentAssistantText += evt.content;
                        currentAssistantEl.innerHTML = renderMarkdown(currentAssistantText);
                        scrollToBottom();

                    } else if (evt.type === "tool_start") {
                        hideTyping();
                        // Finalize current assistant text if any
                        currentAssistantEl = null;
                        currentAssistantText = "";
                        appendToolCall(evt.name, "Calling...");
                        scrollToBottom();

                    } else if (evt.type === "tool_result") {
                        // Replace the last tool call's body with actual result
                        const tools = messagesEl.querySelectorAll(".msg-tool");
                        if (tools.length > 0) {
                            const last = tools[tools.length - 1];
                            const body = last.querySelector(".msg-tool-body");
                            if (body && body.textContent === "Calling...") {
                                body.textContent = evt.content;
                            } else {
                                appendToolResult(evt.name, evt.content);
                            }
                        } else {
                            appendToolResult(evt.name, evt.content);
                        }
                        showTyping();
                        scrollToBottom();

                    } else if (evt.type === "title_update") {
                        // Update sidebar title
                        const item = convList.querySelector('[data-id="' + activeConvId + '"]');
                        if (item) {
                            item.querySelector(".conv-item-title").textContent = evt.title;
                        }

                    } else if (evt.type === "done") {
                        hideTyping();
                        currentAssistantEl = null;
                        currentAssistantText = "";

                    } else if (evt.type === "error") {
                        hideTyping();
                        const div = document.createElement("div");
                        div.className = "msg msg-assistant";
                        div.style.color = "#d63031";
                        div.textContent = "Error: " + evt.content;
                        messagesEl.appendChild(div);
                        scrollToBottom();
                    }
                }
            }
        } catch (err) {
            hideTyping();
            const div = document.createElement("div");
            div.className = "msg msg-assistant";
            div.style.color = "#d63031";
            div.textContent = "Connection error: " + err.message;
            messagesEl.appendChild(div);
        }

        sending = false;
        sendBtn.disabled = false;
        inputEl.focus();
    }
})();
