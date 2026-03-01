// Run Now
async function runNow() {
    const btn = document.getElementById('btn-run-now');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Starting...';
    }
    try {
        const resp = await fetch('/run-now', { method: 'POST' });
        const data = await resp.json();
        if (btn) btn.textContent = data.message || 'Started';
        setTimeout(() => { if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; } }, 3000);
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = 'Run Now'; }
        alert('Failed to start run: ' + e.message);
    }
}

// Test API Key
async function testApiKey() {
    const key = document.getElementById('anthropic_api_key').value;
    if (!key) { alert('Enter an API key first.'); return; }
    try {
        const resp = await fetch('/scheduler/test-api-key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'anthropic_api_key=' + encodeURIComponent(key)
        });
        const data = await resp.json();
        alert(data.message);
    } catch (e) {
        alert('Test failed: ' + e.message);
    }
}

// Test QB Connection
async function testQbConnection() {
    try {
        const resp = await fetch('/settings/quickbooks/test', { method: 'POST' });
        const data = await resp.json();
        alert(data.message);
    } catch (e) {
        alert('Test failed: ' + e.message);
    }
}

// Toggle Rule
async function toggleRule(ruleId) {
    try {
        const resp = await fetch('/rules/toggle/' + ruleId, { method: 'POST' });
        if (resp.ok) location.reload();
    } catch (e) {
        alert('Toggle failed: ' + e.message);
    }
}

// Resolve Flagged Item
async function resolveItem(itemId, status) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/flagged/resolve';

    const fields = { item_id: itemId, status: status, notes: '' };
    for (const [k, v] of Object.entries(fields)) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = k;
        input.value = v;
        form.appendChild(input);
    }

    document.body.appendChild(form);
    form.submit();
}

// Select All Checkboxes
function toggleAll(source) {
    const checkboxes = document.querySelectorAll('input[name="item_ids"]');
    checkboxes.forEach(cb => cb.checked = source.checked);
}

// Edit Rule (inline redirect)
function editRule(ruleId) {
    // For simplicity, expand an inline edit form
    const row = document.getElementById('rule-' + ruleId);
    if (!row) return;
    // Toggle showing the edit cells
    const cells = row.querySelectorAll('td');
    const pattern = cells[0].textContent.trim();
    const category = cells[1].textContent.trim();
    const description = cells[2].textContent.trim();

    // Create a simple edit form below the row
    const existingForm = document.getElementById('edit-form-' + ruleId);
    if (existingForm) { existingForm.remove(); return; }

    const formRow = document.createElement('tr');
    formRow.id = 'edit-form-' + ruleId;
    formRow.innerHTML = `
        <td colspan="6">
            <form method="post" action="/rules/${ruleId}" style="display:flex;gap:0.5rem;align-items:center;padding:0.5rem 0;">
                <select name="rule_type" class="form-select" style="width:auto;">
                    <option value="vendor_category">Vendor Category</option>
                    <option value="always_ignore">Always Ignore</option>
                    <option value="threshold_flag">Threshold Flag</option>
                    <option value="personal_card_exclude">Personal Card Exclude</option>
                </select>
                <input type="text" name="pattern" class="form-input" value="${pattern}" style="width:150px;">
                <input type="text" name="category" class="form-input" value="${category === '—' ? '' : category}" style="width:150px;">
                <input type="text" name="description" class="form-input" value="${description === '—' ? '' : description}" style="width:200px;">
                <button type="submit" class="btn btn-sm btn-primary">Save</button>
                <button type="button" class="btn btn-sm btn-secondary" onclick="document.getElementById('edit-form-${ruleId}').remove()">Cancel</button>
            </form>
        </td>
    `;
    row.after(formRow);
}
