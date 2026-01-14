// latest_report.js
const fetch = require("node-fetch"); // npm install node-fetch@2

const API_URL = "http://localhost:5000/api/violations/latest"; // replace with your backend URL
let lastReportId = null;

async function checkLatest() {
    try {
        const res = await fetch(API_URL);
        const data = await res.json();

        if (data.report_id && data.report_id !== lastReportId) {
            lastReportId = data.report_id;
            console.log("🚨 New violation detected!");
            console.log("Report ID:", data.report_id);
            console.log("Missing PPE:", data.missing_ppe.join(", "));
            console.log("Timestamp:", data.timestamp || "N/A");
            console.log("---------------------------");
        }
    } catch (err) {
        console.error("Failed to fetch latest report:", err.message);
    }
}

// Poll every 3 seconds
setInterval(checkLatest, 3000);
console.log("🖥️ Monitoring latest reports...");
