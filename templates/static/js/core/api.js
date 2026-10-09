/**
 * CORE/API.JS — Lop fetch TRUNG TAM DUY NHAT.
 *
 * Hien tai dashboard.js co getJSON/postJSON nhung 8 cho van goi fetch()
 * tho: upload FormData, DELETE, va /api/kpi-targets. Module nay thay the
 * TOAN BO, ep moi request di qua 1 noi de xu ly loi va dinh dang giong
 * nhau tuyet doi.
 *
 * Dung ES module thuan, khong phu thuoc thu vien ngoai.
 */

class ApiError extends Error {
  constructor(errorCode, message, httpStatus, body) {
    super(message || errorCode);
    this.errorCode = errorCode;
    this.httpStatus = httpStatus;
    this.body = body;
  }
}

async function _handleResponse(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    // Phan hoi khong phai JSON (vd loi mang tra ve HTML) — van tao loi
    // co cau truc thay vi de crash o cho goi.
  }
  if (!res.ok) {
    const code = body?.error_code || `HTTP_${res.status}`;
    const msg = body?.message || `Loi HTTP ${res.status}`;
    throw new ApiError(code, msg, res.status, body);
  }
  return body;
}

function _qs(params) {
  if (!params) return "";
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) usp.set(k, v.join(","));
    else usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export async function getJSON(path, params) {
  const res = await fetch(path + _qs(params), {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  return _handleResponse(res);
}

export async function postJSON(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  return _handleResponse(res);
}

export async function putJSON(path, payload) {
  const res = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  return _handleResponse(res);
}

export async function del(path, params) {
  const res = await fetch(path + _qs(params), {
    method: "DELETE",
    headers: { Accept: "application/json" },
  });
  return _handleResponse(res);
}

/**
 * Upload file (FormData) — thay the moi cho goi fetch() upload thu cong
 * rai rac trong dashboard.js hien tai (import cases, import RFT, import
 * engineering development...).
 */
export async function postForm(path, formData) {
  const res = await fetch(path, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: formData,
  });
  return _handleResponse(res);
}

export { ApiError };
