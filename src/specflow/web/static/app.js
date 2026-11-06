// Specflow: postęp na żywo (SSE) i drobne zachowania ekranu projektu.
// Zgodne z CSP: brak skryptów i stylów inline, brak eval. Tekst narracji wstawiamy
// przez textContent (nigdy innerHTML), bo pochodzi z pracy agenta.
(function () {
  "use strict";

  const root = document.getElementById("project");
  if (!root) return;

  const projectId = root.dataset.projectId;
  const mode = root.dataset.mode;
  const startAfter = Number(root.dataset.lastEvent || "0");
  const MAX_FEED = 300;

  // Które zdarzenia odświeżają który fragment strony.
  const CHAT = new Set([
    "chat_message", "gate_opened", "gate_closed", "planning_step", "planning_step_done",
    "planning_blocked", "command_queued", "command_done", "command_failed",
  ]);
  const BOARD = new Set([
    "status_changed", "plan_imported", "run_state_changed", "project_paused",
    "project_resumed", "command_done", "command_failed", "recovery",
  ]);
  const STAGES = new Set(["phase_changed", "gate_opened", "planning_step_done"]);
  const ARTIFACTS = new Set(["planning_step_done", "phase_changed"]);
  const TYPES = [
    ...new Set([...CHAT, ...BOARD, ...STAGES, ...ARTIFACTS]),
    "project_created", "agent_message", "agent_tool_call", "agent_tool_result",
    "agent_file_changed", "agent_usage", "agent_run_finished",
  ];

  function fire(name) {
    document.body.dispatchEvent(new CustomEvent(name));
  }

  function append(list, event) {
    const item = document.createElement("li");
    item.className = "feed-item " + event.narration.level;
    item.dataset.task = event.task_key || "";
    item.textContent = event.narration.text;
    list.appendChild(item);
    while (list.children.length > MAX_FEED) list.removeChild(list.firstChild);
    list.scrollTop = list.scrollHeight;
  }

  function onEvent(message) {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch (_error) {
      return;
    }
    if (event.type === "phase_changed") {
      const to = event.payload && event.payload.to;
      const building = to === "building" || to === "done";
      if (building !== (mode === "build")) {
        window.location.reload(); // inny układ ekranu dla budowy
        return;
      }
    }
    if (event.narration) {
      document.querySelectorAll("[data-feed]").forEach(function (list) {
        const only = list.dataset.task;
        if (!only || only === event.task_key) append(list, event);
      });
    }
    if (CHAT.has(event.type)) fire("sf:chat");
    if (BOARD.has(event.type)) fire("sf:board");
    if (STAGES.has(event.type)) fire("sf:stages");
    if (ARTIFACTS.has(event.type)) fire("sf:artifacts");
    if (event.task_key && event.type === "status_changed") fire("sf:task-" + event.task_key);
  }

  // Przeglądarka sama łączy się ponownie i wysyła Last-Event-ID (serwer nadrabia z bazy).
  const source = new EventSource(
    "/api/projects/" + encodeURIComponent(projectId) + "/events?after=" + startAfter
  );
  TYPES.forEach(function (type) {
    source.addEventListener(type, onEvent);
  });

  function scrollChat() {
    const log = document.getElementById("chat-log");
    if (log) log.scrollTop = log.scrollHeight;
  }
  scrollChat();
  document.querySelectorAll("[data-feed]").forEach(function (list) {
    list.scrollTop = list.scrollHeight;
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target && event.detail.target.id === "chat-log") scrollChat();
  });

  // Po wysłaniu wiadomości czyścimy pole - tylko gdy serwer przyjął polecenie
  // (przy odrzuceniu, np. "poczekaj chwilę", wpisany tekst zostaje).
  document.body.addEventListener("htmx:afterRequest", function (event) {
    const form = event.detail.elt;
    const xhr = event.detail.xhr;
    const rejected = xhr && xhr.getResponseHeader("X-Specflow-Rejected");
    if (form && form.matches && form.matches("[data-reset-on-success]") &&
        event.detail.successful && !rejected) {
      form.reset();
    }
  });

  // Ctrl/Cmd + Enter wysyła wiadomość.
  document.body.addEventListener("keydown", function (event) {
    const field = event.target;
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && field.form) {
      event.preventDefault();
      field.form.requestSubmit();
    }
  });

  document.querySelectorAll("[data-toggle-chat]").forEach(function (button) {
    button.addEventListener("click", function () {
      const open = root.classList.toggle("chat-open");
      button.setAttribute("aria-expanded", String(open));
      if (open) scrollChat();
    });
  });

  document.querySelectorAll("[data-toggle-details]").forEach(function (box) {
    box.addEventListener("change", function () {
      root.classList.toggle("show-details", box.checked);
    });
  });
})();
