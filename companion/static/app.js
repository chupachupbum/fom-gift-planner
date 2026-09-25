// companion/static/app.js

let currentPlan = null;
let currentSettings = null;
let debounceTimers = {};

// Toast helper
function showToast(message, duration = 2500) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), duration);
}

// ---------------------------------------------------------------------------
// 1. Server-Sent Events (SSE) Live Sync
// ---------------------------------------------------------------------------

function setupEventSource() {
  const liveIndicator = document.getElementById("liveIndicator");
  const liveText = document.getElementById("liveText");

  const evtSource = new EventSource("/api/events");

  evtSource.addEventListener("connected", () => {
    if (liveText) liveText.textContent = "LIVE SYNC";
    if (liveIndicator) liveIndicator.style.color = "#a3e635";
  });

  evtSource.addEventListener("plan_updated", (event) => {
    try {
      const payload = JSON.parse(event.data);
      renderPlan(payload.data);
      showToast("🎮 Game save updated — plan refreshed!");
    } catch (e) {
      console.error("Error parsing plan_updated event:", e);
    }
  });

  evtSource.onerror = () => {
    if (liveText) liveText.textContent = "OFFLINE";
    if (liveIndicator) liveIndicator.style.color = "#ef4444";
    evtSource.close();
    // Reconnect after 3 seconds
    setTimeout(setupEventSource, 3000);
  };
}

// ---------------------------------------------------------------------------
// 2. Fetch and Render Plan
// ---------------------------------------------------------------------------

async function fetchPlan() {
  try {
    const res = await fetch("/api/plan");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderPlan(data);
  } catch (err) {
    console.error("Failed to fetch plan:", err);
    showError("Could not load plan: " + err.message);
  }
}

function showError(msg) {
  const banner = document.getElementById("errorBanner");
  if (banner) {
    banner.textContent = msg;
    banner.classList.add("active");
  }
}

function clearError() {
  const banner = document.getElementById("errorBanner");
  if (banner) {
    banner.textContent = "";
    banner.classList.remove("active");
  }
}

function renderPlan(data) {
  if (!data) return;
  currentPlan = data;

  if (data.error) {
    showError(data.error);
  } else {
    clearError();
  }

  // 1. Date & Header
  renderHeader(data);

  // 2. Bag Plan Section
  renderBagPlan(data.bag_plan || [], data.stats || {});

  // 3. Focus Suggestions Section
  renderFocusSuggestions(data.focus_suggestions || []);

  // 4. Infused Items
  renderInfusedItems(data.infused_items);

  // 5. Sidebar Summary
  renderSidebarSummary(data);
}

function renderHeader(data) {
  const dateInfo = data.in_game_date || {};
  const seasonTag = document.getElementById("seasonTag");
  const dateText = document.getElementById("dateText");
  const festivalPill = document.getElementById("festivalPill");
  const playerFarmBadge = document.getElementById("playerFarmBadge");

  const season = (dateInfo.season || "Spring").toLowerCase();
  if (seasonTag) {
    seasonTag.textContent = season.toUpperCase();
    seasonTag.className = `season-tag season-${season}`;
  }

  if (dateText) {
    let dayStr = `Day ${dateInfo.day || 1} (${dateInfo.day_of_week || 'Weekday'})`;
    if (dateInfo.is_saturday) {
      dayStr += " ★ SATURDAY MARKET";
    }
    dateText.textContent = dayStr;
  }

  if (festivalPill) {
    if (dateInfo.festival_name) {
      festivalPill.textContent = `🎉 ${dateInfo.festival_name}`;
      festivalPill.style.display = "inline-block";
    } else {
      festivalPill.style.display = "none";
    }
  }

  if (playerFarmBadge && data.save_info) {
    const pName = data.save_info.player_name || "Player";
    const fName = data.save_info.farm_name || "Farm";
    playerFarmBadge.textContent = `🌾 ${pName} @ ${fName}`;
  }
}

function renderBagPlan(bagPlan, stats) {
  const grid = document.getElementById("bagGrid");
  const badge = document.getElementById("bagSlotsBadge");

  const maxSlots = stats.max_slots || 20;
  if (badge) {
    badge.textContent = `${bagPlan.length} / ${maxSlots} Slots`;
  }

  if (!grid) return;
  if (bagPlan.length === 0) {
    grid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-muted); font-style: italic; padding: 24px; text-align: center; background: white; border-radius: 8px;">No items required in your bag today! All eligible NPCs covered or already gifted.</p>`;
    return;
  }

  grid.innerHTML = bagPlan.map(item => {
    let statusClass = "status-have";
    if (item.status === "CRAFT") statusClass = "status-craft";
    else if (item.status === "NEED") statusClass = "status-need";

    const recipientsHtml = (item.recipients || []).map(r => {
      const isLove = r.preference.includes("LOVE");
      const prefClass = isLove ? "pref-love" : "pref-like";
      const heartIcon = isLove ? "💖" : "🌟";
      const vendorTag = r.is_vendor ? `<span class="vendor-tag">MARKET</span>` : "";
      const npcAvatar = `/assets/sprites/npcs/${r.npc_id || 'default'}`;

      return `
        <span class="npc-chip ${prefClass}">
          <span class="pref-heart">${heartIcon}</span>
          <img class="npc-chip-avatar" src="${npcAvatar}" alt="${r.name}" loading="lazy" />
          <span class="npc-name">${r.name}</span>
          ${vendorTag}
        </span>
      `;
    }).join("");

    const infusedHtml = item.is_infused
      ? `<span class="infused-tag">🔮 ${item.infusion || 'Infused'}</span>`
      : "";

    let craftingHtml = "";
    if (item.crafting_steps && item.crafting_steps.length > 0) {
      craftingHtml = `
        <div class="crafting-chain">
          <div style="font-weight: 700; margin-bottom: 3px;">🔨 Crafting Steps:</div>
          ${item.crafting_steps.map(s => {
            const ings = (s.ingredients || []).map(ing => `${ing.count}× ${ing.name}`).join(", ");
            const ingText = ings ? ` <span style="color:var(--text-light); font-size:0.75rem;">[← ${ings}]</span>` : "";
            return `<div class="craft-step">• Craft <strong>${s.product_name}</strong>${ingText}</div>`;
          }).join("")}
        </div>
      `;
    } else if (item.crafting_summary && item.crafting_summary.trim().length > 0) {
      craftingHtml = `
        <div class="crafting-chain">
          <div style="font-weight: 700; margin-bottom: 3px;">🔨 Crafting:</div>
          <div class="craft-step">• ${item.crafting_summary}</div>
        </div>
      `;
    }

    const spriteUrl = item.sprite_url || (`/assets/sprites/items/${item.item_id || 'default'}`);

    return `
      <div class="item-card">
        <div class="card-top">
          <img class="item-sprite" src="${spriteUrl}" alt="${item.item_name}" loading="lazy" />
          <div class="item-meta">
            <div class="item-title-row">
              <span class="item-name">${item.item_name}</span>
              <span class="item-qty">x${item.quantity}</span>
            </div>
            <div>
              <span class="status-badge ${statusClass}">${item.status_badge || item.status}</span>
              ${infusedHtml}
            </div>
          </div>
        </div>

        <div class="recipients-container">
          <div class="recipients-title">Target Recipients (${(item.recipients || []).length})</div>
          <div class="recipients-chips">
            ${recipientsHtml || '<span style="color:var(--text-muted); font-size:0.8rem;">None</span>'}
          </div>
        </div>

        ${craftingHtml}
      </div>
    `;
  }).join("");
}

function renderFocusSuggestions(focusItems) {
  const grid = document.getElementById("focusGrid");
  const badge = document.getElementById("focusCountBadge");

  if (badge) {
    badge.textContent = `${focusItems.length} Blocker Items`;
  }

  if (!grid) return;
  if (focusItems.length === 0) {
    grid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-muted); font-style: italic; padding: 20px; text-align: center; background: white; border-radius: 8px;">No material shortages found! You have all ingredients needed for gifts.</p>`;
    return;
  }

  grid.innerHTML = focusItems.map(f => {
    const seasonsStr = (f.seasons && f.seasons.length > 0) ? f.seasons.join(", ") : "All Seasons";
    const blockedNpcsHtml = (f.blocked_npcs && f.blocked_npcs.length > 0)
      ? f.blocked_npcs.map(name => {
          const nid = name.toLowerCase().replace(/[^a-z0-9_]/g, '');
          return `<span class="npc-mini-tag"><img class="npc-mini-avatar" src="/assets/sprites/npcs/${nid}" alt="${name}" loading="lazy" /><span>${name}</span></span>`;
        }).join(" ")
      : 'Various NPCs';

    return `
      <div class="focus-card">
        <div class="focus-header">
          <img class="item-sprite" src="${f.sprite_url}" alt="${f.item_name}" loading="lazy" />
          <div style="flex: 1; display: flex; justify-content: space-between; align-items: center;">
            <strong style="color: var(--text-main);">${f.item_name}</strong>
            <span class="deficit-badge">Need: ${f.deficit}</span>
          </div>
        </div>

        <div class="focus-details">
          <div><strong>📍 Source:</strong> ${f.location || 'Gather / Farm'}</div>
          <div><strong>📅 Season:</strong> ${seasonsStr}</div>
          <div><strong>🔒 Unlocks Gifts For:</strong> ${blockedNpcsHtml}</div>
        </div>
      </div>
    `;
  }).join("");
}

function renderInfusedItems(infused) {
  const section = document.getElementById("section-infused");
  const container = document.getElementById("infusedContainer");
  if (!section || !container) return;

  if (!infused || (typeof infused === 'object' && Object.keys(infused).length === 0)) {
    section.style.display = "none";
    return;
  }

  let html = "";
  for (const [k, v] of Object.entries(infused)) {
    if (!v || v.length === 0) continue;
    let itemsList = "";
    if (Array.isArray(v)) {
      itemsList = v.map(i => {
        if (typeof i === 'object' && i !== null) {
          const rawId = i.item_name || i.name || i.item_id || "";
          const name = rawId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
          const cnt = (i.count && i.count > 1) ? ` (x${i.count})` : "";
          return name + cnt;
        }
        return String(i).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
      }).filter(Boolean).join(", ");
    } else if (typeof v === 'object' && v !== null) {
      itemsList = Object.entries(v).map(([id, cnt]) => {
        const name = id.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
        return `${name} (x${cnt})`;
      }).join(", ");
    } else {
      itemsList = String(v);
    }
    if (itemsList) {
      html += `<div style="margin-bottom: 6px;"><strong>✨ ${k.toUpperCase()}:</strong> ${itemsList}</div>`;
    }
  }

  if (html) {
    container.innerHTML = html;
    section.style.display = "block";
  } else {
    section.style.display = "none";
  }
}

function renderSidebarSummary(data) {
  const saveFilename = document.getElementById("saveFilename");
  const coverageSummary = document.getElementById("coverageSummary");
  const activeStrategy = document.getElementById("activeStrategy");
  const activeMode = document.getElementById("activeMode");

  if (saveFilename && data.save_info) {
    saveFilename.textContent = data.save_info.filename || "Sample Save";
    saveFilename.title = data.save_info.path || "";
  }

  if (coverageSummary && data.stats) {
    coverageSummary.textContent = `${data.stats.covered_npcs_count || 0} / ${data.stats.target_npcs_count || 0} NPCs`;
  }

  if (activeStrategy && data.config) {
    activeStrategy.textContent = (data.config.strategy || "journal").toUpperCase();
  }

  if (activeMode && data.config) {
    activeMode.textContent = (data.config.mode || "auto").toUpperCase();
  }
}

// ---------------------------------------------------------------------------
// 3. Dynamic Settings Accordion
// ---------------------------------------------------------------------------

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentSettings = data.config;
    renderSettingsAccordion(data.schema, data.config);
  } catch (err) {
    console.error("Failed to load settings:", err);
  }
}

function renderSettingsAccordion(schema, config) {
  const accordion = document.getElementById("settingsAccordion");
  if (!accordion || !schema) return;

  accordion.innerHTML = schema.map((group, idx) => {
    const openAttr = idx === 0 ? "open" : "";
    const fieldsHtml = (group.fields || []).map(f => renderField(f, config[f.key])).join("");

    return `
      <details class="settings-group" ${openAttr}>
        <summary>${group.group}</summary>
        <div class="settings-fields">
          ${fieldsHtml}
        </div>
      </details>
    `;
  }).join("");

  // Attach input listeners
  schema.forEach(group => {
    (group.fields || []).forEach(f => {
      const el = document.getElementById(`setting_${f.key}`);
      if (!el) return;

      if (f.type === "checkbox") {
        el.addEventListener("change", () => {
          submitSettingUpdate(f.key, el.checked);
        });
      } else if (f.type === "range") {
        const valSpan = document.getElementById(`val_${f.key}`);
        el.addEventListener("input", () => {
          if (valSpan) valSpan.textContent = el.value;
        });
        el.addEventListener("change", () => {
          submitSettingUpdate(f.key, parseFloat(el.value));
        });
      } else if (f.type === "select") {
        el.addEventListener("change", () => {
          submitSettingUpdate(f.key, el.value);
        });
      } else {
        // Debounced text/number inputs
        el.addEventListener("input", () => {
          clearTimeout(debounceTimers[f.key]);
          debounceTimers[f.key] = setTimeout(() => {
            const val = f.type === "number" ? (el.value === "" ? null : parseFloat(el.value)) : el.value;
            submitSettingUpdate(f.key, val);
          }, 450);
        });
      }
    });
  });
}

function renderField(field, currentVal) {
  const id = `setting_${field.key}`;

  if (field.type === "checkbox") {
    const checked = currentVal ? "checked" : "";
    return `
      <div class="checkbox-group">
        <input type="checkbox" id="${id}" ${checked} />
        <label for="${id}">${field.label}</label>
      </div>
    `;
  }

  if (field.type === "select") {
    const optionsHtml = (field.options || []).map(opt => {
      const sel = opt.value === currentVal ? "selected" : "";
      return `<option value="${opt.value}" ${sel}>${opt.label}</option>`;
    }).join("");

    return `
      <div class="field-group">
        <label for="${id}">${field.label}</label>
        <select id="${id}">${optionsHtml}</select>
      </div>
    `;
  }

  if (field.type === "range") {
    const val = currentVal ?? field.min;
    return `
      <div class="field-group">
        <label for="${id}">${field.label}</label>
        <div class="range-wrap">
          <input type="range" id="${id}" min="${field.min}" max="${field.max}" step="${field.step}" value="${val}" />
          <span class="range-val" id="val_${field.key}">${val}</span>
        </div>
      </div>
    `;
  }

  const inputType = field.type === "number" ? "number" : "text";
  const valAttr = (currentVal !== null && currentVal !== undefined) ? `value="${currentVal}"` : "";
  const placeholderAttr = field.placeholder ? `placeholder="${field.placeholder}"` : "";
  const minMaxAttr = field.type === "number" ? `min="${field.min ?? ''}" max="${field.max ?? ''}" step="${field.step ?? '1'}"` : "";

  return `
    <div class="field-group">
      <label for="${id}">${field.label}</label>
      <input type="${inputType}" id="${id}" ${valAttr} ${placeholderAttr} ${minMaxAttr} />
    </div>
  `;
}

async function submitSettingUpdate(key, value) {
  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [key]: value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const resData = await res.json();
    if (resData.plan) {
      renderPlan(resData.plan);
    }
    showToast(`Setting "${key}" updated`);
  } catch (err) {
    console.error("Failed to update setting:", err);
    showToast(`Error updating ${key}: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// 4. Initialisation
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  setupEventSource();
  fetchPlan();
  loadSettings();

  const refreshBtn = document.getElementById("refreshBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      refreshBtn.disabled = true;
      try {
        const res = await fetch("/api/plan/refresh", { method: "POST" });
        const data = await res.json();
        renderPlan(data);
        showToast("Plan refreshed manually");
      } catch (err) {
        showToast("Error refreshing plan: " + err.message);
      } finally {
        refreshBtn.disabled = false;
      }
    });
  }
});
