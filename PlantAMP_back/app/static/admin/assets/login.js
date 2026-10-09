"use strict";

(function () {
  const form = $("#login-form");
  const msg = $("#msg");

  // Já logado? vai direto para o painel
  if (Auth.get()) location.replace("/admin");

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    hideMsg(msg);
    const { email, password } = formData(form);
    if (!email || !password) return showMsg(msg, "Preencha e-mail e senha.");
    await withBusy(form.querySelector("button"), async () => {
      try {
        const data = await api("/auth/login", { method: "POST", body: { email, password }, auth: false });
        Auth.set(data.access_token);
        location.replace("/admin");
      } catch (e) {
        showMsg(msg, e.message);
        form.password.value = "";
        form.password.focus();
      }
    });
  });
})();
