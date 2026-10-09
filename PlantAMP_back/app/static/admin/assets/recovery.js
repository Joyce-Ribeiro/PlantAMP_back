"use strict";

(function () {
  const form = $("#recovery-form");
  const msg = $("#msg");

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    hideMsg(msg);
    const { email, recovery_code, new_password, confirm } = formData(form);
    if (!email || !recovery_code) return showMsg(msg, "Preencha e-mail e código.");
    if (new_password !== confirm) return showMsg(msg, "As senhas não conferem.");
    await withBusy(form.querySelector("button"), async () => {
      try {
        const data = await api("/auth/recover", {
          method: "POST", body: { email, recovery_code, new_password }, auth: false,
        });
        Auth.clear();
        form.reset();
        showMsg(msg, data.message + " Redirecionando para o login…", "ok");
        setTimeout(() => location.replace("/admin/login"), 3500);
      } catch (e) {
        showMsg(msg, e.message);
      }
    });
  });
})();
