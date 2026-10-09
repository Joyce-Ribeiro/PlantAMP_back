"use strict";

(function () {
  if (!Auth.get()) { location.replace("/admin/login"); return; }

  const state = {
    me: null,
    matrix: null,        // resposta de /groups/matrix
    edits: new Map(),    // group_id -> Set(perms) com alterações não salvas
    groupNames: [],
  };
  const can = (p) => state.me && state.me.permissions.includes(p);
  const globalMsg = $("#global-msg");

  // ------------------------------------------------------------------
  // Topo / sair
  // ------------------------------------------------------------------
  $("#logout").addEventListener("click", () => {
    Auth.clear();
    location.replace("/admin/login");
  });

  // ------------------------------------------------------------------
  // Minha conta
  // ------------------------------------------------------------------
  function renderMe() {
    const me = state.me;
    $("#who-email").textContent = me.full_name ? me.full_name + " · " + me.email : me.email;
    $("#my-groups").replaceChildren(
      ...(me.groups.length ? me.groups.map((g) => h("span", { class: "chip strong" }, g))
                           : [h("span", { class: "chip" }, "nenhum")]));
    $("#my-perms").replaceChildren(
      ...(me.permissions.length ? me.permissions.map((p) => h("span", { class: "chip" }, p))
                                : [h("span", { class: "chip" }, "nenhuma — apenas leitura pública")]));
  }

  async function loadCodesStatus() {
    const { remaining } = await api("/auth/recovery-codes");
    const el = $("#codes-status");
    el.textContent = remaining === 0
      ? "Você ainda não tem códigos de recuperação ativos."
      : "Você tem " + remaining + " código(s) não utilizado(s).";
    el.className = remaining <= 3 ? "msg warn" : "sub";
  }

  $("#codes-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const msg = $("#codes-msg");
    hideMsg(msg);
    const { current_password } = formData(form);
    if (!current_password) return showMsg(msg, "Confirme sua senha atual.");
    await withBusy(form.querySelector("button"), async () => {
      try {
        const data = await api("/auth/recovery-codes", { method: "POST", body: { current_password } });
        form.reset();
        $("#codes-list").replaceChildren(...data.codes.map((c) => h("span", {}, c)));
        $("#codes-out").hidden = false;
        $("#codes-copy").onclick = () => copy(data.codes.join("\n"), $("#codes-copy"));
        await loadCodesStatus();
      } catch (e) { showMsg(msg, e.message); }
    });
  });

  $("#pw-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const msg = $("#pw-msg");
    hideMsg(msg);
    const { current_password, new_password, confirm } = formData(form);
    if (new_password !== confirm) return showMsg(msg, "As senhas não conferem.");
    await withBusy(form.querySelector("button"), async () => {
      try {
        const data = await api("/auth/change-password", {
          method: "POST", body: { current_password, new_password },
        });
        Auth.set(data.access_token); // as outras sessões caíram; esta continua
        form.reset();
        showMsg(msg, "Senha alterada. Suas outras sessões foram encerradas.", "ok");
      } catch (e) { showMsg(msg, e.message); }
    });
  });

  // ------------------------------------------------------------------
  // Matriz de acesso
  // ------------------------------------------------------------------
  async function loadMatrix() {
    state.matrix = await api("/groups/matrix");
    state.edits.clear();
    state.groupNames = state.matrix.rows.map((r) => r.group);
    renderMatrix();
  }

  function currentPerms(row) {
    if (state.edits.has(row.group_id)) return state.edits.get(row.group_id);
    return new Set(Object.entries(row.permissions).filter(([, v]) => v).map(([k]) => k));
  }

  function renderMatrix() {
    const { permissions, rows } = state.matrix;
    const manage = can("groups:manage");

    const head = h("thead", {}, h("tr", {},
      h("th", {}, "Grupo"),
      permissions.map((p) => h("th", { class: "perm", scope: "col", title: p.description || "" },
        p.code, h("small", {}, p.description || ""))),
      manage ? h("th", {}, "") : null));

    const body = h("tbody", {}, rows.map((row) => {
      const perms = currentPerms(row);
      const dirty = state.edits.has(row.group_id);
      return h("tr", { class: dirty ? "dirty" : "" },
        h("th", { scope: "row" }, row.group, " ",
          row.is_system ? h("span", { class: "chip strong" }, "sistema") : null),
        permissions.map((p) => h("td", { class: "cell" },
          h("input", {
            type: "checkbox",
            "aria-label": row.group + " — " + p.code,
            checked: perms.has(p.code),
            disabled: !manage || row.is_system || !can(p.code),
            onchange: (ev) => {
              const next = new Set(currentPerms(row));
              ev.target.checked ? next.add(p.code) : next.delete(p.code);
              const original = new Set(Object.entries(row.permissions).filter(([, v]) => v).map(([k]) => k));
              const same = next.size === original.size && [...next].every((c) => original.has(c));
              same ? state.edits.delete(row.group_id) : state.edits.set(row.group_id, next);
              renderMatrix();
            },
          }))),
        manage ? h("td", {},
          row.is_system ? null : h("button", {
            class: "danger small", type: "button",
            onclick: () => deleteGroup(row),
          }, "Excluir")) : null);
    }));

    $("#matrix").replaceChildren(head, body);
    const hasEdits = state.edits.size > 0;
    $("#matrix-save").hidden = !hasEdits;
    $("#matrix-reset").hidden = !hasEdits;
  }

  $("#matrix-reset").addEventListener("click", () => { state.edits.clear(); renderMatrix(); });

  $("#matrix-save").addEventListener("click", async (ev) => {
    const msg = $("#matrix-msg");
    hideMsg(msg);
    await withBusy(ev.currentTarget, async () => {
      try {
        for (const [groupId, perms] of state.edits) {
          await api("/groups/" + groupId + "/permissions", { method: "PUT", body: { permissions: [...perms] } });
        }
        await loadMatrix();
        await refreshMe();
        showMsg(msg, "Matriz de acesso atualizada. Vale imediatamente para todos os usuários.", "ok");
      } catch (e) { showMsg(msg, e.message); }
    });
  });

  async function deleteGroup(row) {
    if (!confirm("Excluir o grupo \"" + row.group + "\"? Os membros perdem as permissões dele.")) return;
    const msg = $("#matrix-msg");
    try {
      await api("/groups/" + row.group_id, { method: "DELETE" });
      await loadMatrix();
      if (can("users:read")) await loadUsers();
      showMsg(msg, "Grupo excluído.", "ok");
    } catch (e) { showMsg(msg, e.message); }
  }

  $("#group-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const msg = $("#matrix-msg");
    hideMsg(msg);
    const { name, description } = formData(form);
    try {
      await api("/groups/", { method: "POST", body: { name: name.trim().toLowerCase(), description: description || null, permissions: [] } });
      form.reset();
      await loadMatrix();
      if (can("users:read")) await loadUsers();
      showMsg(msg, "Grupo criado. Marque as permissões dele na matriz e salve.", "ok");
    } catch (e) { showMsg(msg, e.message); }
  });

  // ------------------------------------------------------------------
  // Usuários
  // ------------------------------------------------------------------
  async function loadUsers() {
    const users = await api("/users/");
    if (!state.groupNames.length) {
      state.groupNames = [...new Set(users.flatMap((u) => u.groups))].sort();
    }
    renderUsers(users);
    renderNewUserGroups();
  }

  function statusCell(u) {
    if (!u.is_active) return h("span", { class: "status off" }, "inativo");
    if (u.is_locked) return h("span", { class: "status locked" }, "bloqueado");
    return h("span", { class: "status on" }, "ativo");
  }

  function renderUsers(users) {
    const manage = can("users:manage");
    const head = h("thead", {}, h("tr", {},
      h("th", {}, "Usuário"), h("th", {}, "Grupos"), h("th", {}, "Status"),
      h("th", {}, "Último login"), manage ? h("th", {}, "Ações") : null));

    const body = h("tbody", {}, users.map((u) => {
      const isMe = u.id === state.me.id;
      const groupsCell = manage
        ? h("div", { class: "group-checks" }, state.groupNames.map((g) =>
            h("label", {},
              h("input", {
                type: "checkbox", checked: u.groups.includes(g),
                onchange: (ev) => changeUserGroups(u, g, ev.target),
              }), g)))
        : h("div", { class: "chips" }, u.groups.map((g) => h("span", { class: "chip" }, g)));

      const actions = manage ? h("div", { class: "row" },
        h("button", { class: "secondary small", type: "button", disabled: !u.is_active,
                      onclick: () => resetLink(u) }, "Link de senha"),
        u.is_locked ? h("button", { class: "secondary small", type: "button",
                                    onclick: () => userAction(u, "/unlock", "POST") }, "Desbloquear") : null,
        h("button", { class: "secondary small", type: "button", disabled: isMe,
                      onclick: () => userPatch(u, { is_active: !u.is_active }) },
          u.is_active ? "Desativar" : "Ativar"),
        h("button", { class: "danger small", type: "button", disabled: isMe,
                      onclick: () => deleteUser(u) }, "Excluir")) : null;

      return h("tr", {},
        h("td", {}, h("div", {}, u.email), u.full_name ? h("div", { class: "hint" }, u.full_name) : null,
          isMe ? h("span", { class: "chip strong" }, "você") : null),
        h("td", {}, groupsCell),
        h("td", {}, statusCell(u)),
        h("td", {}, fmtDate(u.last_login_at)),
        manage ? h("td", {}, actions) : null);
    }));
    $("#users").replaceChildren(head, body);
  }

  async function changeUserGroups(u, group, checkbox) {
    const next = new Set(u.groups);
    checkbox.checked ? next.add(group) : next.delete(group);
    if (u.id === state.me.id && group === "admin" && !checkbox.checked &&
        !confirm("Remover você mesmo do grupo admin? Você pode perder acesso a este painel.")) {
      checkbox.checked = true;
      return;
    }
    await userPatch(u, { groups: [...next] }, () => { checkbox.checked = !checkbox.checked; });
  }

  async function userPatch(u, body, onError) {
    const msg = $("#users-msg");
    hideMsg(msg);
    try {
      await api("/users/" + u.id, { method: "PATCH", body });
      await loadUsers();
      if (u.id === state.me.id) await refreshMe();
      if (can("groups:read")) await loadMatrix();
    } catch (e) {
      if (onError) onError();
      showMsg(msg, e.message);
    }
  }

  async function userAction(u, suffix, method) {
    const msg = $("#users-msg");
    hideMsg(msg);
    try {
      const data = await api("/users/" + u.id + suffix, { method });
      await loadUsers();
      showMsg(msg, data.message, "ok");
    } catch (e) { showMsg(msg, e.message); }
  }

  async function deleteUser(u) {
    if (!confirm("Excluir definitivamente " + u.email + "?")) return;
    await userAction(u, "", "DELETE");
  }

  async function resetLink(u) {
    const msg = $("#users-msg");
    hideMsg(msg);
    try {
      const data = await api("/users/" + u.id + "/reset-link", { method: "POST" });
      $("#link-text").textContent = data.reset_link;
      $("#link-exp").textContent = data.expires_in_minutes;
      $("#link-mail").textContent = data.emailed
        ? "Também foi enviado para " + u.email + "."
        : "O e-mail não foi enviado (SMTP não configurado): repasse o link por um canal seguro.";
      $("#link-out").hidden = false;
      $("#link-copy").onclick = () => copy(data.reset_link, $("#link-copy"));
      await loadUsers();
    } catch (e) { showMsg(msg, e.message); }
  }

  function renderNewUserGroups() {
    $("#new-user-groups").replaceChildren(...state.groupNames.map((g) =>
      h("label", {}, h("input", { type: "checkbox", name: "groups", value: g }), g)));
  }

  $("#user-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.currentTarget;
    const msg = $("#users-msg");
    hideMsg(msg);
    const data = new FormData(form);
    const body = {
      email: data.get("email"),
      full_name: data.get("full_name") || null,
      password: data.get("password"),
      groups: data.getAll("groups"),
    };
    await withBusy(form.querySelector("button"), async () => {
      try {
        await api("/users/", { method: "POST", body });
        form.reset();
        await loadUsers();
        showMsg(msg, "Usuário criado.", "ok");
      } catch (e) { showMsg(msg, e.message); }
    });
  });

  // ------------------------------------------------------------------
  // Utilidades
  // ------------------------------------------------------------------
  async function copy(text, button) {
    try {
      await navigator.clipboard.writeText(text);
      const old = button.textContent;
      button.textContent = "Copiado!";
      setTimeout(() => { button.textContent = old; }, 1500);
    } catch (_) { /* navegador sem clipboard: o texto está visível para copiar */ }
  }

  async function refreshMe() {
    state.me = await api("/auth/me");
    renderMe();
  }

  // ------------------------------------------------------------------
  // Início
  // ------------------------------------------------------------------
  (async function init() {
    try {
      await refreshMe();
      $("#app").hidden = false;
      await loadCodesStatus();
      if (can("groups:read")) {
        $("#matrix-panel").hidden = false;
        $("#group-form").hidden = !can("groups:manage");
        await loadMatrix();
      }
      if (can("users:read")) {
        $("#users-panel").hidden = false;
        $("#new-user").hidden = !can("users:manage");
        await loadUsers();
      }
    } catch (e) {
      $("#app").hidden = false;
      showMsg(globalMsg, e.message);
    }
  })();
})();
