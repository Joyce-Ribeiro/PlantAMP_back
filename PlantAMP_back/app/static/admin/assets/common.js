// Utilitários compartilhados pelas páginas /admin/*
"use strict";

const TOKEN_KEY = "plantamp_admin_token";

// O token fica no sessionStorage: some ao fechar a aba.
const Auth = {
  get() { try { return sessionStorage.getItem(TOKEN_KEY); } catch (_) { return null; } },
  set(t) { try { sessionStorage.setItem(TOKEN_KEY, t); } catch (_) { /* sem storage */ } },
  clear() { try { sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* sem storage */ } },
};

function errorText(data, status) {
  if (data && typeof data.detail === "string") return data.detail;
  if (data && Array.isArray(data.detail)) {
    return data.detail.map((d) => String(d.msg || "").replace(/^Value error, /, "")).join(" ");
  }
  if (status === 0) return "Sem conexão com o servidor.";
  return "Erro inesperado (" + status + ").";
}

async function api(path, opts) {
  const { method = "GET", body, auth = true } = opts || {};
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = Auth.get();
  if (auth && token) headers["Authorization"] = "Bearer " + token;

  let res;
  try {
    res = await fetch("/api" + path, {
      method, headers, body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (_) {
    throw new Error(errorText(null, 0));
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* sem corpo */ }

  if (res.status === 401 && auth) {
    Auth.clear();
    location.replace("/admin/login");
    throw new Error("Sessão expirada.");
  }
  if (!res.ok) throw new Error(errorText(data, res.status));
  return data;
}

function $(sel, root) { return (root || document).querySelector(sel); }

// Cria elementos sem innerHTML (texto sempre via textContent => sem XSS)
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function showMsg(el, text, kind) {
  el.textContent = text;
  el.className = "msg " + (kind || "error");
  el.hidden = false;
}

function hideMsg(el) { el.hidden = true; }

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

async function withBusy(button, fn) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Aguarde…";
  try { return await fn(); } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

function fmtDate(s) {
  if (!s) return "—";
  const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z"); // API grava em UTC
  return isNaN(d) ? s : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
