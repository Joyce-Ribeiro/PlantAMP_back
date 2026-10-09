"use strict";

(function () {
  const form = $("#forgot-form");
  const msg = $("#msg");

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    hideMsg(msg);
    const { email } = formData(form);
    if (!email) return showMsg(msg, "Informe o e-mail.");
    await withBusy(form.querySelector("button"), async () => {
      try {
        const data = await api("/auth/forgot-password", { method: "POST", body: { email }, auth: false });
        showMsg(msg, data.message + " Confira também a caixa de spam. O link vale por 30 minutos.", "ok");
        form.reset();
      } catch (e) {
        showMsg(msg, e.message);
      }
    });
  });
})();
