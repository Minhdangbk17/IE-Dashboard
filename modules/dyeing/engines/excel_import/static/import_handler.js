(function () {
    "use strict";

    const modal = document.getElementById("import-modal");
    if (!modal) return;

    const MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024; // 20MB

    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("file-input");
    const label = document.getElementById("dropzone-label");
    const previewArea = document.getElementById("preview-area");
    const previewTable = document.getElementById("preview-table");
    const previewErrors = document.getElementById("preview-errors");
    const result = document.getElementById("import-result");
    const progressTrack = document.getElementById("progress-track");
    const progressFill = document.getElementById("progress-fill");
    const progressLabel = document.getElementById("progress-label");
    const confirmButton = document.getElementById("btn-confirm-import");
    const importUrl = modal.dataset.rawImportUrl;
    const typeSelect = document.getElementById("import-schema-key");
    let selectedFile = null;

    function toastContainer() {
        let el = document.querySelector(".toast-container");
        if (!el) {
            el = document.createElement("div");
            el.className = "toast-container";
            document.body.appendChild(el);
        }
        return el;
    }

    function toast(message, kind) {
        const element = document.createElement("div");
        element.className = `flash flash-${kind || "success"} import-toast`;
        element.textContent = message;
        toastContainer().appendChild(element);
        window.setTimeout(() => element.remove(), 4500);
    }

    function formatBytes(bytes) {
        return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(2)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
    }

    function successToast(data, file) {
        const now = new Date().toLocaleString("en-US");
        const element = document.createElement("div");
        element.className = "flash flash-success import-toast";
        element.innerHTML = `
            <div class="toast-title">✔ Data imported successfully</div>
            <div class="toast-meta">${file.name} · ${formatBytes(file.size)} · ${now}</div>
            <div class="toast-stats">
                <span>Total: <strong>${data.total_rows}</strong></span>
                <span style="color:#3fb950">Valid: <strong>${data.rows_imported}</strong></span>
                <span style="color:#f85149">Invalid: <strong>${data.total_rows - data.rows_imported}</strong></span>
            </div>
            <div class="toast-actions">
                <button type="button" class="btn btn-sm" data-action="view-raw">View Raw Data</button>
                <button type="button" class="btn btn-sm" data-action="upload-another">Upload Another File</button>
            </div>`;
        element.querySelector('[data-action="view-raw"]').addEventListener("click", () => {
            element.remove();
            if (window.rawDataDrawer && data.import_log_id) {
                window.rawDataDrawer.open(data.import_log_id);
            }
        });
        element.querySelector('[data-action="upload-another"]').addEventListener("click", () => {
            element.remove();
            reset();
        });
        toastContainer().appendChild(element);
    }

    function reset() {
        selectedFile = null;
        fileInput.value = "";
        label.textContent = "Drag & drop an Availability or Performance file (.xlsx / .csv)";
        previewArea.classList.add("d-none");
        result.classList.add("d-none");
        confirmButton.disabled = true;
        progressTrack.classList.add("d-none");
        progressFill.classList.remove("is-processing");
        progressFill.style.width = "0%";
        progressLabel.classList.add("d-none");
    }

    function renderPreview(data) {
        previewArea.classList.remove("d-none");
        previewTable.innerHTML = "";
        const head = document.createElement("thead");
        head.innerHTML = `<tr>${data.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
        const body = document.createElement("tbody");
        data.preview.forEach((row) => {
            const tr = document.createElement("tr");
            data.columns.forEach((column) => {
                const td = document.createElement("td");
                td.textContent = row[column] ?? "";
                tr.appendChild(td);
            });
            body.appendChild(tr);
        });
        previewTable.append(head, body);
        previewErrors.innerHTML = data.errors.length
            ? `<div class="flash flash-warn"><strong>${data.errors.length} invalid rows:</strong><ul>${data.errors.slice(0, 20).map((error) => `<li>Row ${error.row}: ${error.error}</li>`).join("")}</ul></div>`
            : `<div class="flash flash-success">${data.file_type}: ${data.valid_rows} valid rows.</div>`;
        confirmButton.disabled = data.valid_rows === 0;
    }

    async function preview(file) {
        const form = new FormData();
        form.append("file", file);
        form.append("data_type", typeSelect ? typeSelect.value : "auto");
        previewErrors.textContent = "Reading headers and generating preview...";
        previewArea.classList.remove("d-none");
        confirmButton.disabled = true;
        try {
            const response = await fetch(`${importUrl}?preview=1`, { method: "POST", body: form });
            const data = await response.json();
            if (!response.ok) throw new Error((data.errors || ["Preview failed."]).join(" "));
            if (data.type_mismatch_message) toast(data.type_mismatch_message, "warn");
            renderPreview(data);
        } catch (error) {
            previewErrors.innerHTML = `<div class="flash flash-error">${error.message}</div>`;
        }
    }

    function selectFile(file) {
        if (!file || !/\.(xlsx|xls|csv)$/i.test(file.name)) {
            toast("Only .xlsx, .xls, or .csv files are supported.", "error");
            return;
        }
        if (file.size > MAX_FILE_SIZE_BYTES) {
            toast(`File too large (${formatBytes(file.size)}). Maximum size is 20MB.`, "error");
            return;
        }
        selectedFile = file;
        label.textContent = `Selected: ${file.name} (${formatBytes(file.size)})`;
        preview(file);
    }

    dropzone.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => selectFile(fileInput.files[0]));
    ["dragenter", "dragover"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add("dragover");
    }));
    ["dragleave", "drop"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove("dragover");
    }));
    dropzone.addEventListener("drop", (event) => selectFile(event.dataTransfer.files[0]));

    confirmButton.addEventListener("click", () => {
        if (!selectedFile) return;
        const uploadedFile = selectedFile;
        const form = new FormData();
        form.append("file", uploadedFile);
        form.append("data_type", typeSelect ? typeSelect.value : "auto");
        const xhr = new XMLHttpRequest();
        xhr.open("POST", importUrl, true);
        progressTrack.classList.remove("d-none");
        progressLabel.classList.remove("d-none");
        progressFill.classList.remove("is-processing");
        confirmButton.disabled = true;
        xhr.upload.onprogress = (event) => {
            if (!event.lengthComputable) return;
            const percent = Math.round(event.loaded * 100 / event.total);
            progressFill.style.width = `${percent}%`;
            progressLabel.textContent = `Uploading... ${percent}%`;
        };
        xhr.upload.onload = () => {
            // Toàn bộ file đã lên server — phần còn lại (parse + validate + ghi DB) không
            // đo được % thật qua XHR, chuyển sang trạng thái "đang xử lý" (animation sọc).
            progressFill.classList.add("is-processing");
            progressLabel.textContent = "Processing data...";
        };
        xhr.onload = () => {
            let data;
            try { data = JSON.parse(xhr.responseText); } catch (error) { data = { errors: ["Invalid response from server."] }; }
            progressFill.classList.remove("is-processing");
            if (xhr.status < 200 || xhr.status >= 300 || data.status === "error") {
                result.classList.remove("d-none");
                result.innerHTML = `<div class="flash flash-error">${(data.errors || ["Import failed."]).join(" ")}</div>`;
                if (data.type_mismatch_message) toast(data.type_mismatch_message, "warn");
                confirmButton.disabled = false;
                return;
            }
            result.classList.remove("d-none");
            const errorCount = (data.total_rows || 0) - (data.rows_imported || 0);
            const cls = errorCount > 0 ? "flash-warn" : "flash-success";
            result.innerHTML = `<div class="flash ${cls}">${data.file_type}: imported <strong>${data.rows_imported}</strong>/<strong>${data.total_rows}</strong> rows${errorCount ? ` (${errorCount} invalid)` : ""}.</div>`;
            successToast(data, uploadedFile);
            if (window.dyeingHub) window.dyeingHub.refreshWidgets();
        };
        xhr.onerror = () => {
            progressFill.classList.remove("is-processing");
            result.classList.remove("d-none");
            result.innerHTML = '<div class="flash flash-error">Failed to connect to the server.</div>';
            confirmButton.disabled = false;
        };
        xhr.send(form);
    });

    document.getElementById("btn-close-import")?.addEventListener("click", reset);
    document.getElementById("btn-cancel-import")?.addEventListener("click", reset);
    reset();
}());
