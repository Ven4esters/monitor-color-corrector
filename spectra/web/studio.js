const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
const icon = (name) =>
  `<svg class="icon" aria-hidden="true"><use href="/assets/icons.svg#${esc(name)}"></use></svg>`;
const pad = (n) => String(n).padStart(2, "0");
document.querySelectorAll("[data-icon]").forEach((el) => {
  el.outerHTML = icon(el.dataset.icon);
});

let data = null,
  busy = false,
  scope = "all",
  profile = "standard",
  amount = 70;
let toastTimer,
  lastPreview = null;
const pages = {
  calibration: [
    "РАБОЧАЯ ОБЛАСТЬ",
    "Калибровка мониторов",
    "Единый цвет и яркость для ваших дисплеев.",
  ],
  profiles: [
    "БИБЛИОТЕКА",
    "Целевые профили",
    "Три ориентира для разных условий освещения и задач.",
  ],
  history: [
    "ЖУРНАЛ ОПЕРАЦИЙ",
    "История изменений",
    "Применённые настройки и сохранённые состояния мониторов.",
  ],
};
const activePage = () =>
  Object.hasOwn(pages, location.hash.slice(1)) ? location.hash.slice(1) : "calibration";
const selected = () => data?.monitors.filter((m) => scope === "all" || m.id === scope) ?? [];
const indexOf = (id) => (data?.monitors.findIndex((m) => m.id === id) ?? -1) + 1;
const recommended = () =>
  data?.recommendations[scope]?.[profile] ?? data?.recommendations.all[profile] ?? 70;
const canApply = () =>
  selected().length > 0 && selected().every((m) => m.adjustable) && !data?.recovery;
const amountSuffix = (n) => (n === 1 ? "монитор" : n > 1 && n < 5 ? "монитора" : "мониторов");
const formatTime = (value) =>
  new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));

function toast(text, error = false) {
  clearTimeout(toastTimer);
  $("toast-text").textContent = text;
  $("toast-icon").innerHTML = icon(error ? "info" : "check");
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  toastTimer = setTimeout(
    () => {
      $("toast").hidden = true;
    },
    error ? 9000 : 4300,
  );
}
function warning(text = "") {
  $("warning").hidden = !text;
  $("warning").innerHTML = text ? `${icon("info")}<span>${esc(text)}</span>` : "";
}
async function api(path, payload) {
  const options = { cache: "no-store" };
  if (payload !== undefined) {
    options.method = "POST";
    options.headers = { "Content-Type": "application/json", "X-Spectra-Request": "1" };
    options.body = JSON.stringify(payload);
  }
  let response;
  try {
    response = await fetch(`/api/${path}`, options);
  } catch {
    throw new Error("Нет связи с локальной студией. Проверьте сервер и обновите устройства.");
  }
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error("Сервер недоступен. Обновите устройства, чтобы повторить подключение.");
  }
  if (!response.ok) throw new Error(body.error || "Не удалось выполнить операцию.");
  return body;
}
function updateActions() {
  $("scan").disabled = busy;
  $("apply").disabled = busy || !canApply();
  $("undo").disabled = busy || !data?.undoId;
  $("undo").title = data?.undoId
    ? "Восстановить все дисплеи последнего применения"
    : "Откат станет доступен после применения настроек";
  $("apply").title = canApply()
    ? "Сохранить исходные значения и применить выбранную коррекцию"
    : "Нет доступной цели для записи";
  $("auto").disabled = $("suggested").disabled = busy || !data;
  ["brightness", "brightness-number"].forEach((id) => {
    $(id).disabled = busy || !data;
  });
  document
    .querySelectorAll(".scope-button,.device-card,.preset-card,.history-undo")
    .forEach((button) => (button.disabled = busy));
}
function renderPage() {
  const current = activePage();
  for (const key of Object.keys(pages)) $(key + "-page").hidden = key !== current;
  [$("eyebrow").textContent, $("page-title").textContent, $("page-description").textContent] =
    pages[current];
  document.title = pages[current][1] + " · Spectra Studio";
  document.querySelectorAll(".nav-item").forEach((link) => {
    const active = link.dataset.page === current;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $("scan").hidden = current !== "calibration";
}
function renderDevices() {
  const devices = data.monitors;
  $("device-count").textContent = pad(devices.length);
  $("device-list").innerHTML =
    devices
      .map(
        (
          m,
          i,
        ) => `<button type="button" class="device-card" data-target="${esc(m.id)}" title="${esc(m.reason || "Выбрать только " + m.name)}" aria-label="Выбрать ${esc(m.name)}">
    <span class="device-top"><span class="device-number">ДИСПЛЕЙ ${pad(i + 1)}</span><span class="connection${m.adjustable ? "" : " readonly"}"><span class="status-dot"></span><span>${m.adjustable ? "В сети" : "Только чтение"}</span></span></span>
    <span class="device-body"><img class="monitor-art" src="/assets/monitor-${i % 2 ? "aqua" : "violet"}.svg" alt="" width="154" height="108"><span class="device-info"><span class="device-name">${esc(m.name)}</span>
    <span class="device-resolution">${m.width} × ${m.height}${m.hz ? ` · ${m.hz} Гц` : ""}</span><span class="device-meta"><span class="device-role">${m.primary ? "Основной" : "Внешний"}</span>${m.brightness === null ? "" : `<span class="device-level" title="${m.brightnessMode === "backlight" ? "Яркость подсветки" : "Уровень видеосигнала"}">${icon("sun")}${m.brightness}%</span>`}</span></span></span></button>`,
      )
      .join("") ||
    '<div class="empty-devices">Нет активных мониторов. Подключите дисплей и обновите устройства.</div>';
  let scopes =
    devices.length > 1
      ? `<button type="button" class="scope-button" data-target="all">${icon("monitors")}${devices.length === 2 ? "Оба сразу" : "Все сразу"}</button>`
      : "";
  scopes += devices
    .map(
      (m, i) =>
        `<button type="button" class="scope-button" data-target="${esc(m.id)}" title="${esc(m.name)}">Дисплей ${i + 1}</button>`,
    )
    .join("");
  $("scope").innerHTML = scopes || '<span class="scope-button">Нет устройств</span>';
}
function renderProfiles() {
  $("presets").innerHTML = Object.entries(data.profiles)
    .map(
      ([id, p]) =>
        `<button type="button" class="preset-card ${id}" data-preset="${id}" title="${esc(p.description)}"><span class="preset-icon">${icon(p.icon)}</span><span class="preset-copy"><span class="preset-title">${esc(p.name)}${id === "standard" ? '<span class="recom">Рекомендуем</span>' : ""}</span><span class="preset-detail">${p.kelvin} K · Гамма ${p.gamma.toFixed(1)}</span></span><span class="radio" aria-hidden="true"></span></button>`,
    )
    .join("");
  $("profile-library").innerHTML = Object.entries(data.profiles)
    .map(
      ([id, p], i) =>
        `<article class="library-card ${id}"><div class="library-art"><small>PROFILE / ${pad(i + 1)}</small>${icon(p.icon)}</div><div class="library-body"><h2>${esc(p.name)}</h2><p>${esc(p.description)}</p><div class="library-values"><span>${p.kelvin} K</span><span>γ ${p.gamma.toFixed(1)}</span><span>${data.recommendations[scope]?.[id] ?? data.recommendations.all[id]} %</span></div><button type="button" class="secondary-button" data-library="${id}">Выбрать профиль${icon("arrow-right")}</button></div></article>`,
    )
    .join("");
}
function renderHistory() {
  if (!data.history.length) {
    $("history-list").innerHTML =
      `<div class="empty-history"><span class="empty-icon">${icon("history")}</span><h2>Изменений пока нет</h2><p>После первого применения здесь появятся профиль, яркость и мониторы, для которых сохранён откат.</p><button type="button" class="secondary-button" data-workspace>К калибровке ${icon("arrow-right")}</button></div>`;
    return;
  }
  const statuses = {
    applied: "Применено",
    undone: "Отменено",
    needs_restore: "Требуется откат",
    pending: "Прервано",
    aborted: "Без изменений",
  };
  let body = `<div class="history-heading"><div class="heading-group">${icon("history")}<h2>Последние операции</h2></div><span class="count">${pad(data.history.length)}</span></div>`;
  body += data.history
    .map((entry) => {
      const p = data.profiles[entry.profile];
      return `<article class="history-row ${esc(entry.profile)}"><span class="preset-icon">${icon(p.icon)}</span><div class="history-info"><strong>${esc(p.name)} · ${entry.brightness} %</strong><p>${entry.names.map(esc).join(" / ")}</p></div><div class="history-side"><span class="history-meta ${esc(entry.status)}">${statuses[entry.status] ?? "Сохранено"}</span><time datetime="${esc(entry.time)}">${formatTime(entry.time)}</time></div></article>${entry.id === data.undoId ? `<button type="button" class="secondary-button history-undo" data-undo>${icon("undo")} Отменить применение</button>` : ""}`;
    })
    .join("");
  $("history-list").innerHTML = body;
}
function filterTable(id, curves, scale = 1) {
  if (!curves) return;
  Array.from($(id).children).forEach((channel, c) =>
    channel.setAttribute("tableValues", curves[c].map((x) => (x * scale).toFixed(5)).join(" ")),
  );
}
function updatePreview() {
  const m = selected()[0],
    p = data?.profiles[profile];
  if (!m || !p) return;
  // Display-referred preview only: native writes happen exclusively in /api/apply.
  const prior =
    lastPreview?.profile === profile && lastPreview.amount === amount
      ? lastPreview.before[m.id]
      : null;
  filterTable("transfer-before", prior || m.before);
  filterTable(
    "transfer-after",
    m.curves[profile],
    ((0.12 + (0.88 * amount) / 100) / (m.previewBase || 1)) ** m.previewPower,
  );
  $("preview-ref").textContent = "ДИСПЛЕЙ " + pad(indexOf(m.id));
  $("zoom-caption").textContent = `${m.name} · ${p.name} · ${amount} %`;
  $("comparison").setAttribute(
    "aria-label",
    `Визуальная оценка на ${m.name}: ${p.name}, ${amount} %`,
  );
}
function renderDraft() {
  if (!data) return;
  const p = data.profiles[profile],
    linked = scope === "all" && data.monitors.length > 1;
  $("sync-state").innerHTML =
    icon(linked ? "link" : "monitor") + `<span>${linked ? "Синхронно" : "Раздельно"}</span>`;
  document.querySelectorAll(".device-card").forEach((btn) => {
    btn.classList.toggle("selected", btn.dataset.target === scope);
    btn.setAttribute("aria-pressed", String(scope === "all" || btn.dataset.target === scope));
  });
  document
    .querySelectorAll(".scope-button[data-target]")
    .forEach((btn) => btn.setAttribute("aria-pressed", String(btn.dataset.target === scope)));
  document
    .querySelectorAll(".preset-card")
    .forEach((btn) => btn.setAttribute("aria-pressed", String(btn.dataset.preset === profile)));
  const brightnessModes = new Set(selected().map((m) => m.brightnessMode));
  $("brightness-mode").textContent =
    brightnessModes.size > 1
      ? "Смешанный режим"
      : brightnessModes.has("backlight")
        ? "Подсветка"
        : "Видеосигнал";
  $("suggested").textContent = recommended() + " %";
  $("readout-kelvin").textContent = p.kelvin;
  $("readout-gamma").textContent = p.gamma.toFixed(1);
  $("readout-space").textContent = p.space;
  $("readout-white").textContent = p.kelvin === 6500 ? "D65" : "D50";
  setAmount(amount);
  if (data.recovery)
    warning(
      "Предыдущее применение прервано. Подключите те же мониторы и нажмите «Отменить изменения», чтобы восстановить сохранённое состояние.",
    );
  else warning(selected().find((m) => !m.adjustable)?.reason || "");
  updateActions();
}
function setAmount(value, typing = false) {
  amount = Math.min(100, Math.max(0, Math.round(value)));
  $("brightness").value = amount;
  $("brightness").style.setProperty("--amount", amount + "%");
  $("brightness").setAttribute("aria-valuetext", amount + " процентов");
  if (!typing) $("brightness-number").value = amount;
  updatePreview();
}
function renderAll(resetAmount = false) {
  if (scope !== "all" && !data.monitors.some((m) => m.id === scope)) scope = "all";
  if (data.monitors.length === 1) scope = data.monitors[0].id;
  if (resetAmount) amount = recommended();
  $("mode-name").textContent = data.demo ? "Демо-режим" : "Локально";
  $("mode").classList.toggle("real", !data.demo);
  $("footer-status").textContent = data.recovery
    ? "Ожидается восстановление"
    : data.monitors.length
      ? "Система готова к работе"
      : "Нет подключённых мониторов";
  renderDevices();
  renderProfiles();
  renderHistory();
  renderDraft();
  renderPage();
}
function chooseTarget(id) {
  if (busy || !data || (id !== "all" && !data.monitors.some((m) => m.id === id))) return;
  scope = id;
  amount = recommended();
  renderProfiles();
  renderDraft();
}
function chooseProfile(id) {
  if (busy || !data || !Object.hasOwn(data.profiles, id)) return;
  profile = id;
  amount = recommended();
  renderDraft();
}
function info(title, body, actionLabel = "Понятно", onConfirm = null) {
  const dialog = $("info-dialog");
  $("dialog-content").innerHTML =
    `<h2 id="dialog-title">${esc(title)}</h2>${body}<button type="button" class="primary-button" id="dialog-confirm">${esc(actionLabel)}</button>`;
  $("dialog-confirm").onclick = () => {
    dialog.close();
    if (onConfirm) onConfirm();
  };
  if (!dialog.open) dialog.showModal();
}
async function change(type, payload) {
  if (busy) return;
  busy = true;
  updateActions();
  const before =
    type === "apply" ? Object.fromEntries(selected().map((m) => [m.id, m.before])) : null;
  if (type === "scan") $("scan").classList.add("working");
  if (type === "apply") $("apply").querySelector("span").textContent = "Применение…";
  try {
    data = await api(type, payload);
    lastPreview = before ? { before, profile, amount } : null;
    renderAll(type !== "apply");
    if (type === "scan")
      toast(`Список обновлён: ${data.monitors.length} ${amountSuffix(data.monitors.length)}.`);
    if (type === "undo") {
      toast("Исходные настройки последней операции восстановлены.");
      $("footer-status").textContent = "Исходные значения восстановлены";
    }
    if (type === "apply") {
      toast(
        `${data.demo ? "Демо: настройки применены" : "Настройки применены"} · ${selected()
          .map((m) => m.name)
          .join(" и ")}.`,
      );
      $("footer-status").textContent = "Настройки применены · откат доступен";
    }
  } catch (e) {
    // Fetch the journal even after a partial driver failure so recovery stays available.
    try {
      data = await api("state");
      renderAll();
    } catch {
      /* connection message below */
    }
    warning(e.message);
    toast(e.message, true);
  } finally {
    busy = false;
    $("scan").classList.remove("working");
    $("apply").querySelector("span").textContent = "Применить настройки";
    updateActions();
  }
}
function apply() {
  if (busy || !canApply()) return;
  const monitors = selected();
  const payload = { ids: monitors.map((m) => m.id), profile, brightness: amount };
  if (data.demo) return change("apply", payload);
  info(
    "Применить коррекцию?",
    `<p><strong>${monitors.map((m) => esc(m.name)).join(" и ")}</strong></p><p>${esc(data.profiles[profile].name)} · яркость ${amount} %. Изменения затронут изображение на выбранных выходах, а не только предпросмотр.</p><p class="dialog-note">Исходные гамма-таблицы и доступные значения подсветки будут сохранены до записи. Вернуть их можно кнопкой «Отменить изменения».</p>`,
    "Применить к мониторам",
    () => change("apply", payload),
  );
}
function undo() {
  if (busy || !data?.undoId) return;
  const entry = data.history.find((e) => e.id === data.undoId);
  if (data.demo) return change("undo", { id: entry.id });
  info(
    "Восстановить состояние?",
    `<p>Будут возвращены сохранённые до применения значения для <strong>${entry.names.map(esc).join(" и ")}</strong>. Текущий выбор дисплея не меняет состав этой операции.</p>`,
    "Восстановить",
    () => change("undo", { id: entry.id }),
  );
}

$("device-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-target]");
  if (b) chooseTarget(b.dataset.target);
});
$("scope").addEventListener("click", (e) => {
  const b = e.target.closest("[data-target]");
  if (b) chooseTarget(b.dataset.target);
});
$("presets").addEventListener("click", (e) => {
  const b = e.target.closest("[data-preset]");
  if (b) chooseProfile(b.dataset.preset);
});
$("profile-library").addEventListener("click", (e) => {
  const b = e.target.closest("[data-library]");
  if (b) {
    chooseProfile(b.dataset.library);
    location.hash = "calibration";
  }
});
$("history-list").addEventListener("click", (e) => {
  if (e.target.closest("[data-workspace]")) location.hash = "calibration";
  if (e.target.closest("[data-undo]")) undo();
});
$("auto").onclick = () => {
  chooseProfile("standard");
  toast(`Нейтральный профиль подобран: D65, гамма 2.2, яркость ${amount} %.`);
};
$("suggested").onclick = () => {
  setAmount(recommended());
  toast("Установлена рекомендованная яркость: " + amount + " %.");
};
$("brightness").oninput = (e) => setAmount(Number(e.target.value));
$("brightness-number").oninput = (e) => {
  if (e.target.value !== "" && Number.isFinite(e.target.valueAsNumber))
    setAmount(e.target.valueAsNumber, true);
};
$("brightness-number").onblur = () => setAmount(amount);
$("brightness-number").onkeydown = (e) => {
  if (e.key === "Enter") e.target.blur();
};
$("compare").onchange = (e) => {
  $("comparison").classList.toggle("solo", !e.target.checked);
  $("split").disabled = !e.target.checked;
};
$("split").oninput = (e) => {
  $("comparison").style.setProperty("--split", e.target.value + "%");
  e.target.setAttribute("aria-valuetext", `${e.target.value} % изображения до коррекции`);
};
$("scene").onchange = (e) => {
  $("comparison").dataset.scene = e.target.value;
};
$("expand").onclick = () => {
  $("zoom-home").append($("comparison"));
  $("zoom-dialog").showModal();
};
$("zoom-dialog").addEventListener("close", () => {
  $("preview-home").append($("comparison"));
  $("expand").focus();
});
$("dismiss-toast").onclick = () => {
  $("toast").hidden = true;
};
$("scan").onclick = () => change("scan", {});
$("apply").onclick = apply;
$("undo").onclick = undo;
$("mode").onclick = () => {
  if (!data) return toast("Подключение к локальному серверу ещё не установлено.", true);
  if (data.demo)
    info(
      "Демонстрационный режим",
      `<p>${esc(data.notice)}</p><p>Два виртуальных монитора позволяют проверить профили, яркость и откат. Физические дисплеи вашего компьютера не изменяются.</p><p class="dialog-note">Чтобы настроить свои мониторы, скачайте приложение для Python 3.12. Установка пакетов не требуется.</p><a class="secondary-button download-app" href="/download/Spectra-Studio.pyz" download="Spectra-Studio.pyz">${icon("download")}Скачать приложение</a><p>Запуск в Windows:</p><code>py -3.12 Spectra-Studio.pyz</code><p>Запуск в Linux (X11):</p><code>python3.12 Spectra-Studio.pyz</code>`,
    );
  else
    info(
      "Локальное подключение",
      `<p>Студия работает на вашем компьютере. Мониторы определяются через системные интерфейсы, а модели и паспортные характеристики — по EDID, если они доступны.</p><p>Активные выходы: <strong>${data.monitors.map((m) => esc(m.name)).join(", ") || "нет"}</strong>.</p>`,
    );
};
$("help").onclick = () =>
  info(
    "Как настроить мониторы",
    `<ol><li><strong>Выберите дисплеи.</strong> В области «Применить к» можно связать все мониторы или настроить отдельный выход.</li><li><strong>Сравните варианты.</strong> Выберите профиль и яркость. Перетаскивайте разделитель на изображении или используйте стрелки клавиатуры.</li><li><strong>Примените результат.</strong> Spectra сохранит исходное состояние каждой цели. «Отменить изменения» вернёт всю последнюю операцию — даже после перезапуска.</li></ol><p class="dialog-note">Предпросмотр — визуальная оценка. Если доступно DDC/CI, яркость меняется через подсветку. Иначе используется уровень видеосигнала: 0 % оставляет безопасный минимум. Способ указан под ползунком. Белая точка и гамма рассчитываются по EDID; без колориметра это не измерение яркости в нитах и не точный ICC-профиль.</p>`,
  );
document
  .querySelectorAll("[data-close]")
  .forEach((b) => (b.onclick = () => b.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((d) =>
  d.addEventListener("click", (e) => {
    if (e.target === d) {
      const r = d.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)
        d.close();
    }
  }),
);
window.addEventListener("hashchange", () => {
  renderPage();
  window.scrollTo(0, 0);
});
renderPage();
try {
  data = await api("state");
  renderAll(true);
} catch (e) {
  warning(e.message);
  $("footer-status").textContent = "Нет связи с сервером";
  toast(e.message, true);
}
