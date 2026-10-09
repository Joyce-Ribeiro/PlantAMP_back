"use strict";

(function () {
  const form = $("#reset-form");
  const msg = $("#msg");

  // O token vem depois do "#": nunca é enviado ao servidor em logs/referer.
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("token");
  // Remove o token da barra de endereço/histórico
  history.replaceState(null, "", location.pathname);

  if (!token) {
    $("#no-token").hidden = false;
    form.hidden = true;
    return;
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    hideMsg(msg);
    const { new_password, confirm } = formData(form);
    if (new_password !== confirm) return showMsg(msg, "As senhas não conferem.");
    await withBusy(form.querySelector("button"), async () => {
      try {
        const data = await api("/auth/reset-password", {
          method: "POST", body: { token, new_password }, auth: false,
        });
        Auth.clear();
        form.hidden = true;
        showMsg(msg, data.message, "ok");
        msg.hidden = false;
        form.after(msg);
        setTimeout(() => location.replace("/admin/login"), 2500);
      } catch (e) {
        showMsg(msg, e.message);
      }
    });
  });
})();
