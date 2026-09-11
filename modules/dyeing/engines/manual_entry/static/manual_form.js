(function () {
    "use strict";
    const form = document.getElementById("manual-form");
    if (!form) return;
    const start = document.getElementById("start_time");
    const end = document.getElementById("end_time");
    const planned = document.getElementById("planned-preview");
    const downtime = document.getElementById("downtime-preview");
    const inputs = [...document.querySelectorAll(".downtime-input")];

    function recalculate() {
        const total = inputs.reduce((sum, input) => sum + Math.max(0, Number(input.value) || 0), 0);
        const hours = start.value && end.value ? (new Date(end.value) - new Date(start.value)) / 3600000 : 0;
        planned.textContent = Math.max(0, hours).toFixed(2);
        downtime.textContent = total.toFixed(2);
        return { total, hours };
    }
    [...form.querySelectorAll("input, select")].forEach((input) => input.addEventListener("input", recalculate));
    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const values = recalculate();
        const result = document.getElementById("manual-result");
        if (!start.value || !end.value || values.hours <= 0) {
            result.innerHTML = '<div class="flash flash-error">End Time must be after Start Time.</div>';
            return;
        }
        const payload = Object.fromEntries(new FormData(form).entries());
        inputs.forEach((input) => { payload[input.name] = Number(input.value) || 0; });
        payload.capacity_kg = Number(payload.capacity_kg) || 0;
        try {
            const response = await fetch(form.dataset.apiUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Failed to save data.");
            result.innerHTML = `<div class="flash flash-success">Saved. Production Date: ${data.production_date}</div>`;
            form.reset();
            inputs.forEach((input) => { input.value = "0"; });
            recalculate();
        } catch (error) { result.innerHTML = `<div class="flash flash-error">${error.message}</div>`; }
    });
}());
