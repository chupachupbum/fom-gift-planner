// companion/static/app.js

let currentPlan = null;
let currentSettings = null;
let currentSchema = null;
let debounceTimers = {};

// HTML escape helper
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

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
      if (typeof resetReadyToCraftChecks === "function") {
        resetReadyToCraftChecks();
      }
      renderPlan(payload.data);
      showToast("Game save updated — plan refreshed!");
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

  if (typeof syncReadyToCraftSaveIdentity === "function") {
    syncReadyToCraftSaveIdentity(data);
  }

  if (data.error) {
    showError(data.error);
  } else {
    clearError();
  }

  // 1. Date & Header
  renderHeader(data);

  // 1.5 Overview Statistics Dashboard
  renderStatsDashboard(data);

  // 2. Bag Plan Section
  renderBagPlan(data.bag_plan || [], data.stats || {});

  // 3. Focus Suggestions Section
  renderFocusSuggestions(data.focus_suggestions || [], data.focus_trees || [], data.source_priority || null);

  // 4. Infused Items
  renderInfusedItems(data.infused_items);

  // 5. Sidebar Summary
  renderSidebarSummary(data);

  // 6. Almanac Planner Section
  if (data.almanac) {
    renderAlmanacPlanner(data.almanac);
  }
}

// ---------------------------------------------------------------------------
// 1. Header & Calendar Bar
// ---------------------------------------------------------------------------
function renderHeader(data) {
  const dateInfo = data.in_game_date || {};
  const seasonTag = document.getElementById("seasonTag");
  const dateText = document.getElementById("dateText");
  const festivalPill = document.getElementById("festivalPill");
  const overridePill = document.getElementById("overridePill");
  const playerFarmBadge = document.getElementById("playerFarmBadge");
  const dateBadge = document.getElementById("dateBadge");

  const season = (dateInfo.season || "Spring").toLowerCase();
  if (seasonTag) {
    seasonTag.textContent = season.toUpperCase();
    seasonTag.className = `season-tag season-${season}`;
  }

  if (dateText) {
    let dayStr = `Day ${dateInfo.day || 1} (${dateInfo.day_of_week || 'Weekday'})`;
    if (dateInfo.is_saturday) {
      dayStr += " • SATURDAY MARKET";
    }
    dateText.textContent = dayStr;
  }

  if (festivalPill) {
    if (dateInfo.festival_name) {
      festivalPill.innerHTML = `<img class="inline-icon" src="/static/icons/ui/icon_festival.png" alt="Festival"> ${dateInfo.festival_name}`;
      festivalPill.style.display = "inline-block";
    } else {
      festivalPill.style.display = "none";
    }
  }

  if (overridePill) {
    if (dateInfo.is_overridden) {
      overridePill.style.display = "inline-flex";
      overridePill.title = dateInfo.save_date ? `Save Date: ${dateInfo.save_date.season} Day ${dateInfo.save_date.day}, Year ${dateInfo.save_date.year}` : "Date is overridden";
    } else {
      overridePill.style.display = "none";
    }
  }

  if (dateBadge) {
    if (dateInfo.is_overridden && dateInfo.save_date) {
      dateBadge.title = `Target Date: Year ${dateInfo.year}, ${dateInfo.season} Day ${dateInfo.day} (OVERRIDDEN)\nGame Save: Year ${dateInfo.save_date.year}, ${dateInfo.save_date.season} Day ${dateInfo.save_date.day}\nClick to open Fields of Mistria Calendar`;
    } else {
      dateBadge.title = `Date: Year ${dateInfo.year || 1}, ${dateInfo.season || 'Spring'} Day ${dateInfo.day || 1}\nClick to open Fields of Mistria Calendar`;
    }
  }

  if (playerFarmBadge && data.save_info) {
    const pName = data.save_info.player_name || "Player";
    const fName = data.save_info.farm_name || "Farm";
    playerFarmBadge.innerHTML = `<img class="inline-icon" src="/static/icons/ui/icon_wheat.png" alt="Farm"> ${pName} @ ${fName}`;
  }
}

// ---------------------------------------------------------------------------
// 1.5 Statistics Dashboard State & Renderers
// ---------------------------------------------------------------------------
let activeStatsDrawer = null; // 'completed' | 'incomplete' | 'recipes' | null
let recipesExpanded = false;
let incompleteSearchFilter = "";
let recipeSearchFilter = "";

function renderStatsDashboard(data) {
  const stats = data.stats || {};
  const overallBadge = document.getElementById("statsOverallBadge");
  const giftProgressVal = document.getElementById("statGiftProgressVal");
  const giftProgressFill = document.getElementById("statGiftProgressFill");
  const giftProgressSub = document.getElementById("statGiftProgressSub");

  const completedVal = document.getElementById("statCompletedNpcsVal");
  const completedSub = document.getElementById("statCompletedNpcsSub");
  const drawerCompletedCount = document.getElementById("drawerCompletedCount");

  const incompleteVal = document.getElementById("statIncompleteNpcsVal");
  const incompleteSub = document.getElementById("statIncompleteNpcsSub");
  const drawerIncompleteCount = document.getElementById("drawerIncompleteCount");

  const recipesVal = document.getElementById("statRecipesVal");
  const recipesSub = document.getElementById("statRecipesSub");
  const drawerRecipesCount = document.getElementById("drawerRecipesCount");

  // 1. Overall Gift Progress
  const overallPct = stats.overall_gift_progress_pct !== undefined ? stats.overall_gift_progress_pct : 0;
  const givenTotal = stats.game_given_total || 0;
  const totalPrefs = stats.game_total_preferences || 0;

  if (overallBadge) overallBadge.textContent = `${overallPct}% Discovered`;
  if (giftProgressVal) giftProgressVal.textContent = `${overallPct}%`;
  if (giftProgressFill) giftProgressFill.style.width = `${Math.min(100, Math.max(0, overallPct))}%`;
  if (giftProgressSub) giftProgressSub.textContent = `${givenTotal} / ${totalPrefs} preferences recorded`;

  // 2. Completed NPCs
  const completedList = data.completed_npcs_details || stats.completed_npcs_details || [];
  const completedCount = stats.completed_npcs_count !== undefined ? stats.completed_npcs_count : completedList.length;
  const incompleteList = data.incomplete_npcs_details || stats.incomplete_npcs_details || [];
  const incompleteCount = stats.incomplete_npcs_count !== undefined ? stats.incomplete_npcs_count : incompleteList.length;
  const totalNpcs = stats.total_npcs_count || (completedCount + incompleteCount);

  if (completedVal) completedVal.textContent = `${completedCount} / ${totalNpcs}`;
  if (completedSub) completedSub.textContent = (completedCount === totalNpcs && totalNpcs > 0) ? "All villagers 100% completed!" : "100% gift journal complete";
  if (drawerCompletedCount) drawerCompletedCount.textContent = completedCount;

  // 3. Incomplete NPCs
  if (incompleteVal) incompleteVal.textContent = `${incompleteCount} / ${totalNpcs}`;
  if (incompleteSub) incompleteSub.textContent = incompleteCount === 0 ? "All villager gifts discovered!" : `${incompleteCount} villagers pending loved/liked gifts`;
  if (drawerIncompleteCount) drawerIncompleteCount.textContent = incompleteCount;

  // 4. Recipes
  const recipeStats = data.recipe_stats || {};
  const unobtainedRecipes = data.unobtained_recipes || [];
  const lockedCount = recipeStats.locked_count !== undefined ? recipeStats.locked_count : unobtainedRecipes.length;
  const unlockedCount = recipeStats.unlocked_count || 0;
  const totalCooking = recipeStats.total_cooking || (lockedCount + unlockedCount);

  if (recipesVal) recipesVal.textContent = `${lockedCount} Locked`;
  if (recipesSub) recipesSub.textContent = `${unlockedCount} / ${totalCooking} cooking recipes unlocked`;
  if (drawerRecipesCount) drawerRecipesCount.textContent = lockedCount;

  // Refresh active drawer content if open
  if (activeStatsDrawer === "completed") {
    renderCompletedDrawerContent(completedList);
  } else if (activeStatsDrawer === "incomplete") {
    renderIncompleteDrawerContent(incompleteList);
  } else if (activeStatsDrawer === "recipes") {
    renderRecipesDrawerContent(unobtainedRecipes);
  }
}

function setStatsDrawer(drawerName) {
  if (activeStatsDrawer === drawerName) {
    activeStatsDrawer = null; // Toggle closed
  } else {
    activeStatsDrawer = drawerName;
  }

  const drawerCompleted = document.getElementById("drawerCompleted");
  const drawerIncomplete = document.getElementById("drawerIncomplete");
  const drawerRecipes = document.getElementById("drawerRecipes");

  const btnCompleted = document.getElementById("toggleCompletedBtn");
  const btnIncomplete = document.getElementById("toggleIncompleteBtn");
  const btnRecipes = document.getElementById("toggleRecipesBtn");

  if (drawerCompleted) drawerCompleted.style.display = activeStatsDrawer === "completed" ? "block" : "none";
  if (drawerIncomplete) drawerIncomplete.style.display = activeStatsDrawer === "incomplete" ? "block" : "none";
  if (drawerRecipes) drawerRecipes.style.display = activeStatsDrawer === "recipes" ? "block" : "none";

  if (btnCompleted) {
    btnCompleted.classList.toggle("active", activeStatsDrawer === "completed");
    btnCompleted.innerHTML = activeStatsDrawer === "completed" ? `<span>Collapse</span> <span class="arrow">▲</span>` : `<span>View Completed</span> <span class="arrow">▼</span>`;
    btnCompleted.setAttribute("aria-expanded", activeStatsDrawer === "completed");
  }
  if (btnIncomplete) {
    btnIncomplete.classList.toggle("active", activeStatsDrawer === "incomplete");
    btnIncomplete.innerHTML = activeStatsDrawer === "incomplete" ? `<span>Collapse</span> <span class="arrow">▲</span>` : `<span>View Details</span> <span class="arrow">▼</span>`;
    btnIncomplete.setAttribute("aria-expanded", activeStatsDrawer === "incomplete");
  }
  if (btnRecipes) {
    btnRecipes.classList.toggle("active", activeStatsDrawer === "recipes");
    btnRecipes.innerHTML = activeStatsDrawer === "recipes" ? `<span>Collapse</span> <span class="arrow">▲</span>` : `<span>View Recipes</span> <span class="arrow">▼</span>`;
    btnRecipes.setAttribute("aria-expanded", activeStatsDrawer === "recipes");
  }

  if (currentPlan) {
    if (activeStatsDrawer === "completed") {
      renderCompletedDrawerContent(currentPlan.completed_npcs_details || (currentPlan.stats && currentPlan.stats.completed_npcs_details) || []);
    } else if (activeStatsDrawer === "incomplete") {
      renderIncompleteDrawerContent(currentPlan.incomplete_npcs_details || (currentPlan.stats && currentPlan.stats.incomplete_npcs_details) || []);
    } else if (activeStatsDrawer === "recipes") {
      renderRecipesDrawerContent(currentPlan.unobtained_recipes || []);
    }
  }

  // Smooth scroll into view when opened
  if (activeStatsDrawer) {
    const targetEl = document.getElementById(`drawer${drawerName.charAt(0).toUpperCase() + drawerName.slice(1)}`);
    if (targetEl) {
      targetEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }
}

function renderCompletedDrawerContent(list) {
  const container = document.getElementById("completedGrid");
  if (!container) return;

  if (!list || list.length === 0) {
    container.innerHTML = `<div class="empty-state-notice">No villagers have 100% completed gift journals yet. Keep gifting!</div>`;
    return;
  }

  container.innerHTML = list.map(npc => `
    <div class="completed-npc-chip">
      <img class="completed-npc-avatar" src="${npc.portrait_url}" alt="${npc.name}" onerror="this.src='/assets/sprites/npcs/fallback'" />
      <div class="completed-npc-info">
        <span class="completed-npc-name" title="${npc.name}">${npc.name}</span>
        <span class="completed-npc-badge"><img class="inline-icon" src="/static/icons/ui/icon_check.png" alt="Complete"> 100% Complete</span>
      </div>
    </div>
  `).join("");
}

function renderIncompleteDrawerContent(list) {
  const container = document.getElementById("incompleteGrid");
  if (!container) return;

  if (!list || list.length === 0) {
    container.innerHTML = `<div class="empty-state-notice"><img class="inline-icon" src="/static/icons/ui/icon_festival.png" alt="Complete"> All villagers have their gift journals 100% completed!</div>`;
    return;
  }

  const query = (incompleteSearchFilter || "").trim().toLowerCase();
  const filtered = query
    ? list.filter(npc => (npc.name && npc.name.toLowerCase().includes(query)) || (npc.npc_id && npc.npc_id.toLowerCase().includes(query)))
    : list;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state-notice">No incomplete villagers found matching "${incompleteSearchFilter}".</div>`;
    return;
  }

  container.innerHTML = filtered.map(npc => {
    const lovedChips = (npc.remaining_loved || []).map(item => `
      <span class="gift-item-chip loved" title="${item.name}">
        <img class="gift-item-chip-img" src="${item.sprite_url}" alt="${item.name}" onerror="this.src='/assets/sprites/items/fallback'" />
        <span>${item.name}</span>
      </span>
    `).join("");

    const likedChips = (npc.remaining_liked || []).map(item => `
      <span class="gift-item-chip liked" title="${item.name}">
        <img class="gift-item-chip-img" src="${item.sprite_url}" alt="${item.name}" onerror="this.src='/assets/sprites/items/fallback'" />
        <span>${item.name}</span>
      </span>
    `).join("");

    const vendorPill = npc.is_vendor ? `<span class="festival-pill" style="font-size: 0.65rem; padding: 1px 5px; margin-left: 4px;">Market</span>` : "";

    return `
      <div class="incomplete-npc-card">
        <div class="incomplete-card-top">
          <img class="incomplete-npc-avatar" src="${npc.portrait_url}" alt="${npc.name}" onerror="this.src='/assets/sprites/npcs/fallback'" />
          <div class="incomplete-npc-meta">
            <div class="incomplete-npc-title-row">
              <span class="incomplete-npc-name" title="${npc.name}">${npc.name}${vendorPill}</span>
              <span class="incomplete-npc-pct">${npc.pct_total_done}% done</span>
            </div>
            <div class="incomplete-mini-bar">
              <div class="incomplete-mini-fill" style="width: ${Math.min(100, Math.max(0, npc.pct_total_done))}%"></div>
            </div>
            <div style="font-size: 0.72rem; color: var(--text-light); margin-top: 2px;">
              ${npc.total_remaining} gift${npc.total_remaining === 1 ? '' : 's'} remaining
            </div>
          </div>
        </div>

        <div class="incomplete-npc-gifts-section">
          <div class="gift-type-row">
            <span class="gift-type-label loved"><img class="inline-icon" src="/static/icons/ui/heart_loved.png" alt="Loved"> Remaining Loved (${(npc.remaining_loved || []).length})</span>
            <div class="gift-chips-container">
              ${lovedChips || '<span style="font-size: 0.72rem; color: var(--text-light); font-style: italic;">All loved gifts discovered!</span>'}
            </div>
          </div>
          <div class="gift-type-row" style="margin-top: 4px;">
            <span class="gift-type-label liked"><img class="inline-icon" src="/static/icons/ui/heart_liked.png" alt="Liked"> Remaining Liked (${(npc.remaining_liked || []).length})</span>
            <div class="gift-chips-container">
              ${likedChips || '<span style="font-size: 0.72rem; color: var(--text-light); font-style: italic;">All liked gifts discovered!</span>'}
            </div>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function renderRecipesDrawerContent(allRecipes) {
  const container = document.getElementById("recipesGrid");
  const moreBtn = document.getElementById("toggleMoreRecipesBtn");
  const paginationRow = document.getElementById("recipesPaginationRow");
  const searchInput = document.getElementById("recipeSearchInput");
  if (!container) return;

  if (!allRecipes || allRecipes.length === 0) {
    container.innerHTML = `<div class="empty-state-notice"><img class="inline-icon" src="/static/icons/ui/icon_festival.png" alt="Complete"> All cooking recipes have been obtained!</div>`;
    if (paginationRow) paginationRow.style.display = "none";
    if (searchInput) searchInput.style.display = "none";
    return;
  }

  const query = (recipeSearchFilter || "").trim().toLowerCase();
  let toDisplay = allRecipes;

  if (recipesExpanded) {
    if (searchInput) searchInput.style.display = "inline-block";
    if (query) {
      toDisplay = allRecipes.filter(r => 
        (r.display_name && r.display_name.toLowerCase().includes(query)) ||
        (r.unlock_source && r.unlock_source.toLowerCase().includes(query))
      );
    }
  } else {
    if (searchInput) searchInput.style.display = "none";
    toDisplay = allRecipes.slice(0, 5);
  }

  if (paginationRow) {
    paginationRow.style.display = allRecipes.length > 5 ? "flex" : "none";
    if (moreBtn) {
      if (recipesExpanded) {
        moreBtn.innerHTML = `<span>Collapse to Top 5 ▲</span>`;
      } else {
        moreBtn.innerHTML = `<span>Show More Recipes (${allRecipes.length - 5} more) ▼</span>`;
      }
    }
  }

  if (toDisplay.length === 0) {
    container.innerHTML = `<div class="empty-state-notice">No un-obtained recipes found matching "${recipeSearchFilter}".</div>`;
    return;
  }

  container.innerHTML = toDisplay.map(r => `
    <div class="recipe-card">
      <img class="recipe-card-sprite" src="${r.sprite_url}" alt="${r.display_name}" onerror="this.src='/assets/sprites/items/fallback'" />
      <div class="recipe-card-body">
        <div class="recipe-card-top">
          <span class="recipe-card-name" title="${r.display_name}">${r.display_name}</span>
          ${r.impact > 0 ? `<span class="recipe-impact-badge" title="Unlocks gift preferences for ${r.impact} villager(s)"><img class="inline-icon" src="/static/icons/ui/icon_gift.png" alt="Gift"> Unlocks ${r.impact} villager${r.impact === 1 ? '' : 's'}</span>` : ''}
        </div>
        <div class="recipe-source-row">
          <img class="inline-icon" src="/static/icons/ui/icon_location_pin.png" alt="Location">
          <span class="recipe-source-badge" title="How to obtain: ${r.unlock_source}">${r.unlock_source || 'Unknown'}</span>
        </div>
      </div>
    </div>
  `).join("");
}

function renderBagPlan(bagPlan, stats) {
  renderBagPresetToolbar();
  const grid = document.getElementById("bagGrid");
  const badge = document.getElementById("bagSlotsBadge");

  const maxSlots = stats.max_slots || 20;
  if (badge) {
    badge.textContent = `${bagPlan.length} / ${maxSlots} Slots`;
  }

  if (!grid) return;
  if (bagPlan.length === 0) {
    grid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-muted); font-style: italic; padding: 24px; text-align: center; background: white; border-radius: 8px;">No items required in your bag today! All eligible villagers covered or already gifted.</p>`;
    return;
  }

  grid.innerHTML = bagPlan.map(item => {
    let statusClass = "status-have";
    if (item.status === "CRAFT") statusClass = "status-craft";
    else if (item.status === "NEED") statusClass = "status-need";

    const recipientsHtml = (item.recipients || []).map(r => {
      const isLove = r.preference.includes("LOVE");
      const prefClass = isLove ? "pref-love" : "pref-like";
      const heartIcon = isLove ? '<img class="inline-icon" src="/static/icons/ui/heart_loved.png" alt="Love">' : '<img class="inline-icon" src="/static/icons/ui/heart_liked.png" alt="Like">';
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
      ? `<span class="infused-tag"><img class="inline-icon" src="/static/icons/ui/icon_perk_essence.png" alt="Infused"> ${item.infusion || 'Infused'}</span>`
      : "";

    let craftingHtml = "";
    if (item.crafting_steps && item.crafting_steps.length > 0) {
      craftingHtml = `
        <div class="crafting-chain">
          <div style="font-weight: 700; margin-bottom: 3px;"><img class="inline-icon" src="/static/icons/ui/icon_hammer.png" alt="Crafting"> Crafting Steps:</div>
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
          <div style="font-weight: 700; margin-bottom: 3px;"><img class="inline-icon" src="/static/icons/ui/icon_hammer.png" alt="Crafting"> Crafting:</div>
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

function renderBlockedNpcs(blockedNpcs) {
  if (!blockedNpcs || !Array.isArray(blockedNpcs)) {
    return 'Various villagers';
  }

  const validNpcs = blockedNpcs
    .map(name => (typeof name === 'string' ? name : (name ? String(name) : '')).trim())
    .filter(name => name.length > 0);

  if (validNpcs.length === 0) {
    return 'Various villagers';
  }

  const formatTag = (name) => {
    const nid = name.toLowerCase().replace(/[^a-z0-9_]/g, '');
    return `<span class="npc-mini-tag"><img class="npc-mini-avatar" src="/assets/sprites/npcs/${nid}" alt="${name}" loading="lazy" /><span>${name}</span></span>`;
  };

  if (validNpcs.length <= 3) {
    return validNpcs.map(formatTag).join(" ");
  }

  const initialNpcs = validNpcs.slice(0, 3).map(formatTag).join(" ");
  const extraCount = validNpcs.length - 3;
  const extraNpcs = validNpcs.slice(3).map(formatTag).join(" ");

  return `
    <span class="blocked-npcs-wrapper">
      <span class="blocked-npcs-initial">${initialNpcs}</span>
      <span class="blocked-npcs-extra" style="display: none;"> ${extraNpcs}</span>
      <button type="button" class="npc-toggle-btn npc-expand-btn" onclick="toggleBlockedNpcs(this, true)" title="Show ${extraCount} more villagers">and +${extraCount} more</button>
      <button type="button" class="npc-toggle-btn npc-collapse-btn" onclick="toggleBlockedNpcs(this, false)" style="display: none;" title="Collapse list">Collapse</button>
    </span>
  `;
}

function toggleBlockedNpcs(btnOrWrapper, expand) {
  const wrapper = btnOrWrapper?.classList?.contains('blocked-npcs-wrapper')
    ? btnOrWrapper
    : btnOrWrapper?.closest?.('.blocked-npcs-wrapper');
  if (!wrapper) return;

  const isAlreadyExpanded = wrapper.classList.contains('is-expanded');
  if (expand === isAlreadyExpanded) return;

  wrapper.classList.toggle('is-expanded', expand);
  const extra = wrapper.querySelector('.blocked-npcs-extra');
  const expandBtn = wrapper.querySelector('.npc-expand-btn');
  const collapseBtn = wrapper.querySelector('.npc-collapse-btn');

  if (extra) extra.style.display = expand ? 'inline' : 'none';
  if (expandBtn) expandBtn.style.display = expand ? 'none' : 'inline-flex';
  if (collapseBtn) collapseBtn.style.display = expand ? 'inline-flex' : 'none';
}
window.toggleBlockedNpcs = toggleBlockedNpcs;
window.renderBlockedNpcs = renderBlockedNpcs;

const ALT_SOURCE_EMOJI = {
  shop: "Shop",
  inn: "Inn",
  market_stall: "Market",
  chicken_statue: "Chicken Statue",
  mimic: "Mimic",
  mill: "Mill",
  fishing: "Fishing",
  wishing_well: "Well",
  festival: "Festival",
  date: "Date",
  quest: "Quest",
  museum: "Museum",
  living_off_the_land: "Forage",
};

function renderCraftingTree(tree, depth = 0) {
  if (!tree) return '';
  return '';
}

// ---------------------------------------------------------------------------
// D3 Interactive Collapsible Crafting Tree Modal
// ---------------------------------------------------------------------------

let _treeModalZoom = null;
let _treeModalSvg = null;
let _treeModalRoot = null;
let _treeModalUpdate = null;

function openCraftingTreeModal(rawTreeData, deficit) {
  if (!rawTreeData || typeof d3 === 'undefined') return;

  const modal = document.getElementById('treeModal');
  const body = document.getElementById('treeModalBody');
  const titleEl = document.getElementById('treeModalTitle');
  const deficitEl = document.getElementById('treeModalDeficit');
  const searchInput = document.getElementById('treeSearchInput');
  if (!modal || !body) return;

  // Set title & deficit
  titleEl.textContent = `Crafting Tree: ${rawTreeData.item_name || 'Unknown'}`;
  if (deficit) {
    deficitEl.textContent = `Need: ${deficit}`;
    deficitEl.style.display = 'inline-block';
  } else {
    deficitEl.style.display = 'none';
  }

  if (searchInput) searchInput.value = '';

  // Show modal
  modal.style.display = 'flex';
  modal.classList.remove('closing');
  document.body.style.overflow = 'hidden';

  // Clear previous SVG
  body.innerHTML = '';

  // 1. Preprocess tree data (group direct recipes when mixed with intermediates)
  const treeData = prepareTreeData(rawTreeData);

  // 2. Build D3 hierarchy
  const root = d3.hierarchy(treeData, d => d.children);
  _treeModalRoot = root;
  root.x0 = 0;
  root.y0 = 0;

  // 3. Set initial collapsed state
  initCollapse(root);

  const CARD_W = 220;

  function getCardHeight(d) {
    const data = d.data;
    const isRoot = d.depth === 0;
    if (data.is_quest_group) return 56;
    if (data.is_group) return 56;

    if (data.is_quest) {
      let h = 44 + 24; // header (44px) + badges row (24px)
      if (data.requester) h += 24;
      if (data.via_item_name) h += 18;
      return Math.max(68, Math.min(110, h));
    }

    let h = 44; // base header
    if (isRoot && deficit) h += 24; // deficit badge

    // Almanac missing slot badge
    if (data.is_almanac_missing !== undefined) {
      h += 24;
    }

    // Category pill
    if (data.category && !data.is_group && !data.is_quest) {
      h += 20;
    }

    if (data.alt_sources && data.alt_sources.length > 0) {
      h += Math.min(data.alt_sources.length, 3) * 26 + 4;
    }

    if (data.gift_npcs && data.gift_npcs.length > 0) {
      const rows = Math.ceil(data.gift_npcs.length / 2);
      h += rows * 22 + 4;
    }

    const hasChildren = (d.children && d.children.length > 0) || (d._children && d._children.length > 0);
    if (hasChildren && !isRoot) {
      h += 26; // toggle pill
    }

    return Math.max(h, 60);
  }

  // 4. Create SVG and Zoom
  const svgW = body.clientWidth || 1200;
  const svgH = body.clientHeight || 680;

  const svg = d3.select(body)
    .append('svg')
    .attr('width', svgW)
    .attr('height', svgH);

  _treeModalSvg = svg;

  const g = svg.append('g');

  const zoom = d3.zoom()
    .scaleExtent([0.25, 2.5])
    .on('zoom', (event) => {
      g.attr('transform', event.transform);
    });

  svg.call(zoom);
  _treeModalZoom = zoom;

  // Tree layout with separation based on actual card heights
  const treeLayout = d3.tree()
    .nodeSize([100, CARD_W + 80])
    .separation((a, b) => {
      const hA = getCardHeight(a);
      const hB = getCardHeight(b);
      const needed = (hA + hB) / 2 + 16;
      const factor = Math.max(1, needed / 100);
      return a.parent === b.parent ? factor : factor * 1.25;
    });

  const linkGen = d3.linkHorizontal()
    .x(d => d.y)
    .y(d => d.x);

  let nodeIdSeq = 0;

  // 5. Update function for collapsible transitions
  function update(source) {
    const treeDataNodes = treeLayout(root);
    const nodes = treeDataNodes.descendants();
    const links = treeDataNodes.links();

    // Update nodes
    const node = g.selectAll('g.tree-node-group')
      .data(nodes, d => d.id || (d.id = ++nodeIdSeq));

    // ENTER: spawn from source position
    const nodeEnter = node.enter()
      .append('g')
      .attr('class', 'tree-node-group')
      .attr('transform', () => `translate(${source.y0 || source.y},${source.x0 || source.x})`)
      .style('opacity', 0);

    // Append foreignObject for cards
    nodeEnter.each(function(d) {
      const nodeEl = d3.select(this);
      const data = d.data;
      const isRoot = d.depth === 0;
      const isQuestGroup = !!data.is_quest_group;
      const isGroup = !!data.is_group;
      const isQuest = !!data.is_quest;
      const isGift = !isGroup && !isQuest && data.gift_npcs && data.gift_npcs.length > 0;
      const hasChildren = (d.children && d.children.length > 0) || (d._children && d._children.length > 0);
      const isIntermediate = !isRoot && !isGroup && !isQuest && hasChildren;

      let cardClass = 'd3-tree-node';
      if (isRoot) cardClass += ' is-root';
      else if (isQuestGroup) cardClass += ' is-group is-quest-group';
      else if (isGroup) cardClass += ' is-group';
      else if (isQuest) cardClass += ' is-quest';
      else if (isIntermediate) cardClass += ' is-intermediate';
      else if (isGift) cardClass += ' is-gift';
      if (data.is_almanac_missing === true) cardClass += ' is-almanac-missing';

      const cardH = getCardHeight(d);

      const fo = nodeEl.append('foreignObject')
        .attr('class', 'node-foreign-object')
        .attr('width', CARD_W)
        .attr('height', cardH + 16)
        .attr('x', -CARD_W / 2)
        .attr('y', -cardH / 2);

      const cardDiv = fo.append('xhtml:div')
        .attr('class', cardClass)
        .style('min-height', `${cardH}px`)
        .on('click', (event) => {
          event.stopPropagation();
          toggleNode(d);
        });

      let bodyHtml = "";

      if (isQuest) {
        // Quest node rendering
        const cat = data.quest_category || data.quest_type || 'Request';
        const catSlug = String(cat).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

        let requesterHtml = "";
        if (data.requester) {
          const reqSlug = String(data.requester).toLowerCase().trim();
          requesterHtml = `
            <div class="d3-quest-requester" title="Requester: ${escapeHtml(data.requester)}">
              <img class="d3-requester-portrait" src="/assets/sprites/npcs/${reqSlug}" onerror="this.src='/static/icons/ui/icon_npc.png';" alt="${escapeHtml(data.requester)}" />
              <span class="d3-requester-name">${escapeHtml(data.requester)}</span>
            </div>
          `;
        }

        let viaHtml = "";
        if (data.via_item_name) {
          viaHtml = `<div class="d3-quest-via" title="Needed via ${escapeHtml(data.via_item_name)}">via ${escapeHtml(data.via_item_name)}</div>`;
        }

        bodyHtml = `
          <div class="d3-node-header">
            <span class="d3-quest-icon" style="font-size: 1.1rem; line-height: 1; margin-right: 4px;">📜</span>
            <span class="d3-node-name" title="${escapeHtml(data.item_name)}">${escapeHtml(data.item_name)}</span>
          </div>
          <div class="d3-quest-badges">
            <span class="d3-quest-badge quest-cat-${catSlug}">${escapeHtml(cat)}</span>
            <span class="d3-quest-amount">Required: ×${data.quest_amount || 1}</span>
          </div>
          ${requesterHtml}
          ${viaHtml}
        `;
      } else {
        // Header row: sprite + title
        let headerHtml = `<div class="d3-node-header">`;
        if (isQuestGroup) {
          headerHtml += `<span class="d3-quest-icon" style="font-size: 1.1rem; line-height: 1; margin-right: 4px;">📜</span>`;
        } else if (isGroup) {
          headerHtml += `<img class="d3-node-sprite" src="/static/icons/ui/icon_recipe.png" alt="Recipe" />`;
        } else {
          headerHtml += `<img class="d3-node-sprite" src="${data.sprite_url || '/assets/sprites/items/' + data.item_id}" alt="${escapeHtml(data.item_name)}" onerror="this.style.display='none'" />`;
        }
        headerHtml += `<span class="d3-node-name" title="${escapeHtml(data.item_name)}">${escapeHtml(data.item_name)}</span>`;
        headerHtml += `</div>`;
        bodyHtml = headerHtml;

        // Deficit badge on root
        if (isRoot && deficit) {
          bodyHtml += `<span class="d3-node-deficit">Need: ${deficit}</span>`;
        }

        // Almanac slot status badge
        if (data.is_almanac_missing === true) {
          bodyHtml += `<span class="d3-node-almanac-badge is-missing" title="Unobtained in Almanac">📖 Missing Slot</span>`;
        } else if (data.is_almanac_missing === false) {
          bodyHtml += `<span class="d3-node-almanac-badge is-obtained" title="Already Acquired in Almanac">✓ Acquired</span>`;
        }

        // Category badge
        if (data.category && !isGroup && !isQuest) {
          const catName = data.category.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
          bodyHtml += `<span class="d3-node-cat-badge">${escapeHtml(catName)}</span>`;
        }

        // Alt source badges
        if (data.alt_sources && data.alt_sources.length > 0) {
          bodyHtml += `<div class="d3-node-alt-sources">`;
          data.alt_sources.slice(0, 3).forEach(s => {
            const iconUrl = `/assets/sprites/locations/${s.icon || s.type}`;
            const label = s.vendor || s.location || (s.type === 'chicken_statue' ? 'Chicken Statue' : (s.type === 'wishing_well' ? 'Wishing Well' : (s.type === 'living_off_the_land' ? 'Living Off The Land' : (s.type || '').replace(/_/g, ' '))));
            const cost = (s.cost !== null && s.cost !== undefined)
              ? ` ${s.cost}${s.currency === 'tesserae' ? 't' : (s.currency === 'shiny_beads' ? ' beads' : ' ' + (s.currency || ''))}`
              : '';
            const note = s.note ? ` (${s.note})` : '';
            const fullTitle = `${label}${cost}${note}`.replace(/"/g, '&quot;');

            bodyHtml += `<span class="d3-node-alt-badge" title="${fullTitle}">
              <img class="source-icon" src="${iconUrl}" onerror="this.src='/static/icons/ui/icon_location_pin.png';" alt="${s.type}" />
              <span class="badge-text">${label}${cost}</span>
            </span>`;
          });
          bodyHtml += `</div>`;
        }

        // NPC recipient chips
        if (data.gift_npcs && data.gift_npcs.length > 0) {
          bodyHtml += `<div class="d3-node-npcs">`;
          data.gift_npcs.forEach(npc => {
            bodyHtml += `<span class="d3-node-npc-chip">→ ${escapeHtml(npc)}</span>`;
          });
          bodyHtml += `</div>`;
        }

        // Collapse / Expand toggle button pill
        if (hasChildren && !isRoot) {
          const childCount = (d.children ? d.children.length : (d._children ? d._children.length : 0));
          const isCollapsed = !!d._children;
          const toggleIcon = isCollapsed ? '▶' : '▼';
          const labelSuffix = isQuestGroup ? 'quests' : 'products';
          const toggleText = isCollapsed ? `${toggleIcon} ${childCount} ${labelSuffix}` : `${toggleIcon} Collapse`;
          bodyHtml += `<div class="d3-node-toggle ${isCollapsed ? 'is-collapsed' : ''}">${toggleText}</div>`;
        }
      }

      cardDiv.html(bodyHtml);
    });

    // UPDATE: transition to new positions
    const nodeUpdate = nodeEnter.merge(node);

    nodeUpdate.transition()
      .duration(300)
      .attr('transform', d => `translate(${d.y},${d.x})`)
      .style('opacity', 1);

    // Update toggle pills and heights on existing cards
    nodeUpdate.each(function(d) {
      const card = d3.select(this).select('.d3-tree-node');
      const toggleEl = card.select('.d3-node-toggle');
      const hasChildren = (d.children && d.children.length > 0) || (d._children && d._children.length > 0);

      if (hasChildren && d.depth > 0) {
        const childCount = (d.children ? d.children.length : (d._children ? d._children.length : 0));
        const isCollapsed = !!d._children;
        const toggleIcon = isCollapsed ? '▶' : '▼';
        const labelSuffix = d.data.is_quest_group ? 'quests' : 'products';
        const toggleText = isCollapsed ? `${toggleIcon} ${childCount} ${labelSuffix}` : `${toggleIcon} Collapse`;

        if (!toggleEl.empty()) {
          toggleEl.text(toggleText).classed('is-collapsed', isCollapsed);
        }
      }

      // Keep foreignObject dimensions matching current card
      const cardH = getCardHeight(d);
      d3.select(this).select('foreignObject')
        .attr('height', cardH + 16)
        .attr('y', -cardH / 2);
    });

    // EXIT: transition to source position and remove
    node.exit().transition()
      .duration(250)
      .attr('transform', () => `translate(${source.y},${source.x})`)
      .style('opacity', 0)
      .remove();

    // UPDATE LINKS
    const link = g.selectAll('path.tree-link')
      .data(links, d => `${d.source.id}->${d.target.id}`);

    const linkEnter = link.enter()
      .insert('path', 'g')
      .attr('class', 'tree-link')
      .attr('d', () => {
        const o = { y: source.y0 || source.y, x: source.x0 || source.x };
        return linkGen({ source: o, target: o });
      });

    linkEnter.merge(link).transition()
      .duration(300)
      .attr('d', d => {
        const sourcePoint = {
          y: d.source.y + CARD_W / 2,
          x: d.source.x
        };
        const targetPoint = {
          y: d.target.y - CARD_W / 2,
          x: d.target.x
        };
        return linkGen({ source: sourcePoint, target: targetPoint });
      });

    link.exit().transition()
      .duration(250)
      .attr('d', () => {
        const o = { y: source.y, x: source.x };
        return linkGen({ source: o, target: o });
      })
      .remove();

    // Stash old positions for transitions
    nodes.forEach(d => {
      d.x0 = d.x;
      d.y0 = d.y;
    });
  }

  _treeModalUpdate = update;

  function toggleNode(d) {
    if (d.children) {
      d._children = d.children;
      d.children = null;
    } else if (d._children) {
      d.children = d._children;
      d._children = null;
    }
    update(d);
  }

  // Initial draw
  update(root);

  // Auto-fit with clamped min-scale so text is NEVER microscopic
  _fitTreeToViewSmart(svg, g, root, svgW, svgH, zoom);

  // Setup Controls (Zoom, Fit, Expand/Collapse All, Search)
  _setupTreeModalControlsEnhanced(svg, g, root, svgW, svgH, zoom, update);
}

// ---------------------------------------------------------------------------
// Tree Preprocessing & Collapsing Helpers
// ---------------------------------------------------------------------------

function prepareTreeData(rawTree) {
  if (!rawTree) return null;
  const clone = JSON.parse(JSON.stringify(rawTree));

  function processNode(node) {
    if (!node.children || node.children.length === 0) {
      node.children = [];
      return;
    }

    node.children.forEach(processNode);

    // Separate quest children from recipe children
    const questChildren = node.children.filter(c => c.is_quest === true);
    const nonQuestChildren = node.children.filter(c => !c.is_quest);

    let effectiveChildren = nonQuestChildren;

    // If node has intermediate items (with children) AND direct leaves (children: [])
    const intermediates = nonQuestChildren.filter(c => (c.children && c.children.length > 0) || (c._children && c._children.length > 0));
    const leaves = nonQuestChildren.filter(c => (!c.children || c.children.length === 0) && (!c._children || c._children.length === 0));

    // Group leaves if there are intermediates AND leaves count > 5
    if (intermediates.length > 0 && leaves.length > 5) {
      const groupNode = {
        item_id: `_group_direct_${node.item_id}`,
        item_name: `Direct Recipes (${leaves.length})`,
        is_group: true,
        children: leaves,
        gift_npcs: [],
        alt_sources: []
      };
      effectiveChildren = [...intermediates, groupNode];
    }

    // When node has direct quest children with count > 4: group them into a single collapsible node
    if (questChildren.length > 4) {
      const questGroupNode = {
        item_id: `_group_quests_${node.item_id}`,
        item_name: `Quests (${questChildren.length})`,
        is_group: true,
        is_quest_group: true,
        children: questChildren,
        gift_npcs: [],
        alt_sources: []
      };
      node.children = [...effectiveChildren, questGroupNode];
    } else {
      node.children = [...effectiveChildren, ...questChildren];
    }
  }

  processNode(clone);
  return clone;
}

function countDescendants(n) {
  const ch = n.children || n._children || [];
  return ch.reduce((acc, c) => acc + 1 + countDescendants(c), 0);
}

function initCollapse(d, depth = 0) {
  if (!d.children || d.children.length === 0) return;

  d.children.forEach(c => initCollapse(c, depth + 1));

  if (depth === 0) {
    const total = countDescendants(d);
    // If total descendants exceed 8, collapse sub-children on initial view
    if (total > 8) {
      d.children.forEach(c => {
        if (c.children && c.children.length > 0) {
          c._children = c.children;
          c.children = null;
        }
      });
    }
  } else {
    d._children = d.children;
    d.children = null;
  }
}

function _fitTreeToViewSmart(svg, g, root, svgW, svgH, zoom) {
  const gNode = g.node();
  if (!gNode) return;

  requestAnimationFrame(() => {
    const bbox = gNode.getBBox();
    if (!bbox || bbox.width === 0 || bbox.height === 0) return;

    const pad = 80;
    const fullW = bbox.width + pad * 2;
    const fullH = bbox.height + pad * 2;

    // Smart Scale: Do NOT shrink below 0.70x so text remains crisp and readable!
    const idealScale = Math.min(svgW / fullW, svgH / fullH, 1.05);
    const scale = Math.max(idealScale, 0.72);

    let tx, ty;
    if (scale <= idealScale) {
      // Entire tree fits comfortably within bounds
      tx = svgW / 2 - (bbox.x + bbox.width / 2) * scale;
      ty = svgH / 2 - (bbox.y + bbox.height / 2) * scale;
    } else {
      // Tree is large: anchor root on left margin with ample padding, centered vertically
      tx = pad;
      ty = svgH / 2 - (root.x || 0) * scale;
    }

    svg.transition()
      .duration(400)
      .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
  });
}

function _setupTreeModalControlsEnhanced(svg, g, root, svgW, svgH, zoom, update) {
  const zoomInBtn = document.getElementById('treeZoomIn');
  const zoomOutBtn = document.getElementById('treeZoomOut');
  const fitBtn = document.getElementById('treeFitBtn');
  const expandAllBtn = document.getElementById('treeExpandAllBtn');
  const collapseAllBtn = document.getElementById('treeCollapseAllBtn');
  const searchInput = document.getElementById('treeSearchInput');

  function replaceBtn(el) {
    if (!el) return null;
    const clone = el.cloneNode(true);
    el.parentNode.replaceChild(clone, el);
    return clone;
  }

  const newZoomIn = replaceBtn(zoomInBtn);
  const newZoomOut = replaceBtn(zoomOutBtn);
  const newFit = replaceBtn(fitBtn);
  const newExpandAll = replaceBtn(expandAllBtn);
  const newCollapseAll = replaceBtn(collapseAllBtn);
  const newSearch = replaceBtn(searchInput);

  if (newZoomIn) {
    newZoomIn.addEventListener('click', () => {
      svg.transition().duration(200).call(zoom.scaleBy, 1.3);
    });
  }

  if (newZoomOut) {
    newZoomOut.addEventListener('click', () => {
      svg.transition().duration(200).call(zoom.scaleBy, 0.7);
    });
  }

  if (newFit) {
    newFit.addEventListener('click', () => {
      _fitTreeToViewSmart(svg, g, root, svgW, svgH, zoom);
    });
  }

  if (newExpandAll) {
    newExpandAll.addEventListener('click', () => {
      function expandAll(d) {
        if (d._children) {
          d.children = d._children;
          d._children = null;
        }
        if (d.children) d.children.forEach(expandAll);
      }
      expandAll(root);
      update(root);
      _fitTreeToViewSmart(svg, g, root, svgW, svgH, zoom);
    });
  }

  if (newCollapseAll) {
    newCollapseAll.addEventListener('click', () => {
      function collapseAll(d) {
        if (d.children && d.depth > 0) {
          d._children = d.children;
          d.children = null;
        }
        const ch = d.children || d._children;
        if (ch) ch.forEach(collapseAll);
      }
      collapseAll(root);
      update(root);
      _fitTreeToViewSmart(svg, g, root, svgW, svgH, zoom);
    });
  }

  if (newSearch) {
    newSearch.addEventListener('input', (e) => {
      const term = (e.target.value || '').trim().toLowerCase();

      if (!term) {
        svg.selectAll('.d3-tree-node').classed('is-match', false).classed('is-dimmed', false);
        _fitTreeToViewSmart(svg, g, root, svgW, svgH, zoom);
        return;
      }

      function isNodeMatch(data) {
        if (!data) return false;
        const name = (data.item_name || '').toLowerCase();
        const npcs = (data.gift_npcs || []).join(' ').toLowerCase();
        const alts = (data.alt_sources || []).map(s => s.vendor || s.location || s.type).join(' ').toLowerCase();
        const qType = (data.quest_type || '').toLowerCase();
        const qCat = (data.quest_category || '').toLowerCase();
        const qReq = (data.requester || '').toLowerCase();
        const qVia = (data.via_item_name || '').toLowerCase();
        return name.includes(term) || npcs.includes(term) || alts.includes(term) ||
               qType.includes(term) || qCat.includes(term) || qReq.includes(term) || qVia.includes(term);
      }

      // Auto-expand any collapsed ancestors of matching nodes
      function expandMatches(n) {
        const isSelfMatch = isNodeMatch(n.data);

        const allChildren = (n.children || []).concat(n._children || []);
        let childMatched = false;
        allChildren.forEach(c => {
          if (expandMatches(c)) childMatched = true;
        });

        if (childMatched && n._children) {
          n.children = n._children;
          n._children = null;
        }

        return isSelfMatch || childMatched;
      }

      expandMatches(root);
      update(root);

      let firstMatch = null;
      svg.selectAll('.d3-tree-node').each(function(d) {
        const isMatch = isNodeMatch(d.data);

        d3.select(this)
          .classed('is-match', isMatch)
          .classed('is-dimmed', !isMatch);

        if (isMatch && !firstMatch && d.depth > 0) {
          firstMatch = d;
        }
      });

      // Smoothly pan camera to center the first match for effortless navigation
      if (firstMatch) {
        const targetScale = Math.max(0.85, Math.min(1.05, svgW / 1200));
        const tx = svgW / 2 - firstMatch.y * targetScale;
        const ty = svgH / 2 - firstMatch.x * targetScale;
        svg.transition()
          .duration(350)
          .call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(targetScale));
      }
    });
  }
}

function closeTreeModal() {
  const modal = document.getElementById('treeModal');
  if (!modal) return;
  modal.classList.add('closing');
  setTimeout(() => {
    modal.style.display = 'none';
    modal.classList.remove('closing');
    document.body.style.overflow = '';
    const body = document.getElementById('treeModalBody');
    if (body) body.innerHTML = '';
  }, 200);
}

// Modal dismiss handlers
document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('treeModal');
  const closeBtn = document.getElementById('treeModalClose');

  if (closeBtn) closeBtn.addEventListener('click', closeTreeModal);

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) closeTreeModal();
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const modal = document.getElementById('treeModal');
      if (modal && modal.style.display !== 'none') {
        closeTreeModal();
      }
    }
  });
});

function toggleCraftingTree(btn, treeData, deficit) {
  if (treeData) {
    openCraftingTreeModal(treeData, deficit);
  }
}
window.toggleCraftingTree = toggleCraftingTree;
window.openCraftingTreeModal = openCraftingTreeModal;
window.closeTreeModal = closeTreeModal;
window.renderCraftingTree = renderCraftingTree;

function renderSourceSummary(sourcePriority, focusItemsCount) {
  const panel = document.getElementById("sourceSummaryPanel");
  if (!panel) return;

  // Visibility rule: If !focusItemsCount || !sourcePriority || sourcePriority.length === 0: hide panel
  if (!focusItemsCount || !sourcePriority) {
    panel.style.display = "none";
    panel.innerHTML = "";
    return;
  }

  let quickSources = [];
  let grindSources = [];
  let farmSources = [];

  if (Array.isArray(sourcePriority)) {
    sourcePriority.forEach(s => {
      const t = String(s.tier || 'grind').toLowerCase();
      if (t === 'quick') quickSources.push(s);
      else if (t === 'farm') farmSources.push(s);
      else grindSources.push(s);
    });
  } else if (typeof sourcePriority === 'object' && sourcePriority !== null) {
    quickSources = sourcePriority.quick || [];
    grindSources = sourcePriority.grind || [];
    farmSources = sourcePriority.farm || [];
  }

  const totalSources = quickSources.length + grindSources.length + farmSources.length;
  if (totalSources === 0) {
    panel.style.display = "none";
    panel.innerHTML = "";
    return;
  }

  panel.style.display = "block";

  const renderTier = (tierKey, title, icon, subtext, sources) => {
    if (!sources || sources.length === 0) return "";
    const tierScore = sources.reduce((acc, s) => acc + (s.total_score || 0), 0);

    const sourceCardsHtml = sources.map(s => {
      const itemsHtml = (s.items || []).map(item => `
        <div class="source-item-chip">
          <img class="source-item-sprite" src="${item.sprite_url || '/assets/sprites/items/' + item.item_id}" alt="${item.item_name}" onerror="this.style.display='none'" />
          <span class="source-item-name">${item.item_name}</span>
          <span class="source-item-deficit">Need: ${item.deficit}</span>
          <span class="source-item-pairs" title="${item.blocked_pairs} blocked villager-gift combinations">(${item.blocked_pairs} pairs)</span>
        </div>
      `).join("");

      const npcsHtml = renderBlockedNpcs(s.benefited_npcs || []);

      return `
        <div class="source-card">
          <div class="source-card-header">
            <div class="source-card-title">
              <img class="inline-icon" src="/static/icons/ui/icon_location_pin.png" alt="Location">
              <strong>${s.source_name}</strong>
            </div>
            <div class="source-card-badges">
              <span class="tier-badge-pill tier-pill-${tierKey}">${tierKey.toUpperCase()}</span>
              <span class="source-score-badge" title="Total blocked villager gifts unlocked">Score: ${s.total_score || 0}</span>
            </div>
          </div>

          <div class="source-items-section">
            <div class="source-label">Blocker Items (${(s.items || []).length}):</div>
            <div class="source-items-chips">${itemsHtml}</div>
          </div>

          <div class="source-benefited-section">
            <div class="source-label">Benefited Villagers:</div>
            <div class="source-npcs-chips">${npcsHtml}</div>
          </div>
        </div>
      `;
    }).join("");

    return `
      <details class="source-tier-accordion tier-${tierKey}">
        <summary class="source-tier-summary">
          <div class="tier-summary-title">
            <span class="tier-icon">${icon}</span>
            <span class="tier-name">${title}</span>
            <span class="tier-subtext">${subtext}</span>
          </div>
          <div class="tier-summary-stats">
            <span class="tier-stat-badge">${sources.length} sources</span>
            <span class="tier-stat-badge tier-score-badge">Score: ${tierScore}</span>
            <span class="tier-chevron">▼</span>
          </div>
        </summary>
        <div class="source-tier-content">
          ${sourceCardsHtml}
        </div>
      </details>
    `;
  };

  panel.innerHTML = `
    <div class="source-summary-header">
      <div class="source-summary-title">
        <img class="section-icon" src="/static/icons/ui/icon_location_pin.png" alt="Sources">
        <h3>Acquisition Source Priority</h3>
        <span class="badge-beta">BETA</span>
      </div>
      <span class="source-summary-subtitle">Ranked by blocked villager gift impact</span>
    </div>
    <div class="source-tiers-wrapper">
      ${renderTier("quick", "Quick Acquisition", '<img class="inline-icon" src="/static/icons/ui/tier_quick.png" alt="Quick">', "— Instant / Purchasable (Shops, Mill, Forge, Cook)", quickSources)}
      ${renderTier("grind", "Grind Acquisition", '<img class="inline-icon" src="/static/icons/ui/tier_grind.png" alt="Grind">', "— Repeatable / Exploration (Mines, Fishing, Foraging)", grindSources)}
      ${renderTier("farm", "Farm & Ranch", '<img class="inline-icon" src="/static/icons/ui/tier_farm.png" alt="Farm">', "— Seasonal / Planning (Crops, Animals, Feed)", farmSources)}
    </div>
  `;
}
window.renderSourceSummary = renderSourceSummary;

const FUTURE_WIFE_CANDIDATES = [
  { id: "none", label: "None / Undecided", dish: null, dish_id: null, title: "Hide all 'A Craving' marriage quests until you decide" },
  { id: "adeline", label: "Adeline", dish: "Lemon Pie", dish_id: "lemon_pie", title: "Adeline — A Craving: Lemon Pie" },
  { id: "celine", label: "Celine", dish: "Spring Salad", dish_id: "spring_salad", title: "Celine — A Craving: Spring Salad" },
  { id: "juniper", label: "Juniper", dish: "Pizza", dish_id: "pizza", title: "Juniper — A Craving: Pizza" },
  { id: "reina", label: "Reina", dish: "Ice Cream Sundae", dish_id: "ice_cream_sundae", title: "Reina — A Craving: Ice Cream Sundae" },
  { id: "seridia", label: "Seridia", dish: "Ice Cream Sundae", dish_id: "ice_cream_sundae", title: "Seridia — A Craving: Ice Cream Sundae" },
  { id: "valen", label: "Valen", dish: "Grilled Cheese", dish_id: "grilled_cheese", title: "Valen — A Craving: Grilled Cheese" },
  { id: "all", label: "All 6", dish: null, dish_id: null, title: "Include 'A Craving' quests for all 6 bachelorettes" },
];

function renderFutureWifeBanner() {
  const banner = document.getElementById("futureWifeBanner");
  if (!banner) return;

  const rawSelected = currentSettings?.future_wife || currentPlan?.config?.future_wife || "none";
  const selected = String(rawSelected).trim().toLowerCase() || "none";

  const sidebarSelect = document.getElementById("setting_future_wife");
  if (sidebarSelect && sidebarSelect.value !== selected) {
    sidebarSelect.value = selected;
  }

  const activeCand = FUTURE_WIFE_CANDIDATES.find(c => c.id === selected) || FUTURE_WIFE_CANDIDATES[0];
  let statusBadgeHtml = "";
  if (selected === "none") {
    statusBadgeHtml = `<span class="future-wife-status-badge is-none">Quests Hidden</span>`;
  } else if (selected === "all") {
    statusBadgeHtml = `<span class="future-wife-status-badge is-all">Tracking All 6 Cravings</span>`;
  } else {
    statusBadgeHtml = `<span class="future-wife-status-badge is-active">Tracking: ${escapeHtml(activeCand.label)} (${escapeHtml(activeCand.dish || "")})</span>`;
  }

  const pillsHtml = FUTURE_WIFE_CANDIDATES.map(c => {
    const isActive = (c.id === selected);
    const activeClass = isActive ? "active" : "";
    if (c.dish_id) {
      return `
        <button type="button" class="future-wife-pill ${activeClass}" data-wife="${c.id}" title="${escapeHtml(c.title)}">
          <img class="future-wife-portrait" src="/assets/sprites/npcs/${c.id}" alt="${escapeHtml(c.label)}" onerror="this.onerror=null; this.src='/assets/sprites/npcs/fallback';" />
          <span class="future-wife-name">${escapeHtml(c.label)}</span>
          <span class="future-wife-dish">
            <img class="future-wife-dish-icon" src="/assets/sprites/items/${c.dish_id}" alt="${escapeHtml(c.dish)}" onerror="this.style.display='none';" />
            ${escapeHtml(c.dish)}
          </span>
        </button>
      `;
    }
    const icon = c.id === "all" ? "💍" : "🚫";
    return `
      <button type="button" class="future-wife-pill future-wife-pill-meta ${activeClass}" data-wife="${c.id}" title="${escapeHtml(c.title)}">
        <span>${icon} ${escapeHtml(c.label)}</span>
      </button>
    `;
  }).join("");

  banner.innerHTML = `
    <div class="future-wife-banner-top">
      <div class="future-wife-info">
        <span class="future-wife-title">💍 Marriage-Exclusive Quest Filter: <strong>"A Craving"</strong></span>
        <span class="future-wife-desc">Post-marriage quest exclusive to your spouse (requires a cooked dish from one of the 6 bachelorettes). Choose your future wife so only her quest is tracked:</span>
      </div>
      ${statusBadgeHtml}
    </div>
    <div class="future-wife-pills" id="futureWifePills">
      ${pillsHtml}
    </div>
  `;
}
window.renderFutureWifeBanner = renderFutureWifeBanner;

function initFutureWifeBannerEvents() {
  const banner = document.getElementById("futureWifeBanner");
  if (!banner || banner._hasFutureWifeEvents) return;
  banner._hasFutureWifeEvents = true;

  banner.addEventListener("click", async (e) => {
    const pill = e.target.closest(".future-wife-pill");
    if (!pill || !pill.dataset.wife) return;
    const val = pill.dataset.wife;
    if (currentSettings) currentSettings.future_wife = val;
    const sidebarSelect = document.getElementById("setting_future_wife");
    if (sidebarSelect) sidebarSelect.value = val;
    renderFutureWifeBanner();
    await submitSettingUpdate("future_wife", val);
  });
}

function renderFocusSuggestions(focusItems, focusTrees = [], sourcePriority = null) {
  const grid = document.getElementById("focusGrid");
  const badge = document.getElementById("focusCountBadge");

  if (typeof renderFutureWifeBanner === "function") {
    renderFutureWifeBanner();
  }

  if (badge) {
    badge.textContent = `${focusItems.length} Blocker Items`;
  }

  // Render Source Priority Summary panel (visibility handled inside renderSourceSummary)
  renderSourceSummary(sourcePriority, focusItems ? focusItems.length : 0);

  if (!grid) return;
  if (focusItems.length === 0) {
    grid.innerHTML = `<p style="grid-column: 1/-1; color: var(--text-muted); font-style: italic; padding: 20px; text-align: center; background: white; border-radius: 8px;">No material shortages found! You have all ingredients needed for gifts.</p>`;
    return;
  }

  const treeMap = new Map((focusTrees || []).map(t => [String(t.item_id || '').toLowerCase(), t]));

  // Store trees globally so modal onclick can access them
  window._craftingTreeData = window._craftingTreeData || {};

  grid.innerHTML = focusItems.map((f, idx) => {
    const seasonsStr = (f.seasons && f.seasons.length > 0) ? f.seasons.join(", ") : "All Seasons";
    const blockedNpcsHtml = renderBlockedNpcs(f.blocked_npcs);
    const fId = String(f.item_id || '').toLowerCase();
    let tree = treeMap.get(fId);
    if (!tree) {
      if (fId === 'milk') tree = treeMap.get('cow_milk');
      else if (fId === 'cow_milk') tree = treeMap.get('milk');
      else if (fId === 'wood') tree = treeMap.get('basic_wood');
      else if (fId === 'basic_wood') tree = treeMap.get('wood');
    }

    // Only show "View crafting tree" button if the item has at least one branch in its crafting tree
    const hasBranches = Boolean(tree && Array.isArray(tree.children) && tree.children.length > 0);
    let treeHtml = "";
    if (hasBranches) {
      const treeKey = `tree_${fId}_${idx}`;
      window._craftingTreeData[treeKey] = tree;
      const hasQuests = Boolean((f.quest_count && f.quest_count > 0) || (f.quest_demand && f.quest_demand > 0) || (tree && Array.isArray(tree.children) && tree.children.some(c => c.is_quest)));
      const treeBtnText = hasQuests ? 'View crafting & quest tree' : 'View crafting tree';
      treeHtml = `
        <div class="tree-section">
          <button type="button" class="tree-toggle" onclick="openCraftingTreeModal(window._craftingTreeData['${treeKey}'], ${f.deficit || 0})"><img class="inline-icon" src="/static/icons/ui/icon_tree.png" alt="Tree"> ${treeBtnText}</button>
        </div>
      `;
    }

    // Resolve and render all alternate acquisition sources for this focus item
    const altSources = (f.alt_sources && Array.isArray(f.alt_sources) && f.alt_sources.length > 0)
      ? f.alt_sources
      : (tree && Array.isArray(tree.alt_sources) ? tree.alt_sources : []);

    let altSourcesHtml = "";
    if (altSources && altSources.length > 0) {
      const badgesHtml = altSources.map(s => {
        const iconUrl = `/assets/sprites/locations/${s.icon || s.type}`;
        const label = s.vendor || s.location || (s.type === 'chicken_statue' ? 'Chicken Statue' : (s.type === 'wishing_well' ? 'Wishing Well' : (s.type === 'living_off_the_land' ? 'Living Off The Land' : (s.type || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()))));
        const cost = (s.cost !== null && s.cost !== undefined)
          ? ` (${s.cost}${s.currency === 'tesserae' ? 't' : (s.currency === 'shiny_beads' ? ' beads' : ' ' + (s.currency || ''))})`
          : '';
        const note = s.note ? ` [${s.note}]` : '';
        const fullTitle = `${label}${cost}${note}`.replace(/"/g, '&quot;');
        return `
          <span class="focus-alt-badge" title="${fullTitle}">
            <img class="source-icon" src="${iconUrl}" onerror="this.src='/static/icons/ui/icon_location_pin.png';" alt="${s.type || 'source'}" />
            <span class="badge-text">${label}${cost}${note ? ' - ' + s.note : ''}</span>
          </span>
        `;
      }).join("");

      altSourcesHtml = `
        <div class="focus-alt-sources-row">
          <div><strong><img class="inline-icon" src="/static/icons/ui/icon_sparkle.png" alt="Alt Sources"> Alt Sources:</strong></div>
          <div class="focus-alt-badges">${badgesHtml}</div>
        </div>
      `;
    }

    // Deficit badge
    const giftDeficit = (f.gift_deficit !== undefined && f.gift_deficit !== null) ? f.gift_deficit : (f.deficit - (f.quest_demand || 0));
    const deficitBadgeText = (f.quest_demand && f.quest_demand > 0)
      ? `Need: ${f.deficit} (${giftDeficit} Gifts + ${f.quest_demand} Quests)`
      : `Need: ${f.deficit}`;

    // Quest reminder row inside focus-details
    let questRowHtml = "";
    if ((f.quest_count && f.quest_count > 0) || (f.quest_demand && f.quest_demand > 0)) {
      const questCount = f.quest_count || 0;
      const questDemand = f.quest_demand || 0;
      const catEntries = Object.entries(f.quest_categories || {});
      const catPills = catEntries.map(([category, count]) => {
        const catSlug = String(category).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
        return `<span class="quest-cat-pill quest-cat-${catSlug}">${escapeHtml(category)}: ${count}</span>`;
      }).join("");

      const summaryLines = (f.quest_summary || []).map(q => {
        const amt = q.amount ? ` ×${q.amount}` : '';
        const viaTarget = q.via_item_name || q.target_item_name;
        const via = (!q.is_direct && viaTarget) ? ` via ${viaTarget}` : '';
        const req = q.requester ? ` (${q.requester})` : '';
        return `• ${q.quest_name}${amt}${via}${req}`;
      });
      const summaryTooltip = summaryLines.join('\n');

      questRowHtml = `
        <div class="focus-quest-row" title="${escapeHtml(summaryTooltip)}">
          <div class="focus-quest-header">
            <strong>📜 Future Quests: ${questCount} ${questCount === 1 ? 'quest' : 'quests'} (+${questDemand} needed)</strong>
          </div>
          ${catPills ? `<div class="focus-quest-pills" title="${escapeHtml(summaryTooltip)}">${catPills}</div>` : ''}
        </div>
      `;
    }

    return `
      <div class="focus-card">
        <div class="focus-header">
          <img class="item-sprite" src="${f.sprite_url}" alt="${f.item_name}" loading="lazy" />
          <div style="flex: 1; display: flex; justify-content: space-between; align-items: center;">
            <strong style="color: var(--text-main);">${f.item_name}</strong>
            <span class="deficit-badge">${deficitBadgeText}</span>
          </div>
        </div>

        <div class="focus-details">
          <div><strong><img class="inline-icon" src="/static/icons/ui/icon_location_pin.png" alt="Source"> Source:</strong> ${f.location || 'Gather / Farm'}</div>
          <div><strong><img class="inline-icon" src="/static/icons/ui/icon_calendar.png" alt="Season"> Season:</strong> ${seasonsStr}</div>
          <div><strong><img class="inline-icon" src="/static/icons/ui/icon_lock.png" alt="Unlocks"> Unlocks Gifts For:</strong> ${blockedNpcsHtml}</div>
          ${questRowHtml}
          ${altSourcesHtml}
        </div>
        ${treeHtml}
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
      html += `<div style="margin-bottom: 6px;"><strong><img class="inline-icon" src="/static/icons/ui/icon_sparkle.png" alt="Perk"> ${k.toUpperCase()}:</strong> ${itemsList}</div>`;
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
    coverageSummary.textContent = `${data.stats.covered_npcs_count || 0} / ${data.stats.target_npcs_count || 0} Villagers`;
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
    currentSchema = data.schema;
    const savedActivePresetId = localStorage.getItem("fom_companion_active_preset_id");
    if (savedActivePresetId && currentSettings.mode === "custom") {
      const preset = getCustomPresetById(savedActivePresetId);
      if (preset) {
        currentSettings.active_preset_id = savedActivePresetId;
      } else {
        currentSettings.mode = "auto";
        currentSettings.active_preset_id = null;
        currentSettings.custom_preset_npcs = "";
        localStorage.removeItem("fom_companion_active_preset_id");
      }
    } else if (currentSettings.mode === "custom" && !currentSettings.custom_preset_npcs) {
      currentSettings.mode = "auto";
      currentSettings.active_preset_id = null;
    }
    // Defensive check: if focus mode is enabled but no focus npcs, disable it
    if (currentSettings.focus_mode_enabled && !currentSettings.focus_npcs) {
      currentSettings.focus_mode_enabled = false;
    }
    renderSettingsAccordion(data.schema, currentSettings);
    renderBagPresetToolbar();
    renderFutureWifeBanner();
  } catch (err) {
    console.error("Failed to load settings:", err);
  }
}

function renderSettingsAccordion(schema, config) {
  const accordion = document.getElementById("settingsAccordion");
  if (!accordion || !schema) return;

  accordion.innerHTML = schema.map((group, idx) => {
    const groupId = group.id || (group.group === "Almanac Planner" ? "almanac" : group.group === "Focus Suggestions" ? "focus_suggestions" : "planning");
    const openAttr = (idx === 0 || groupId === "almanac") ? "open" : "";
    const fieldsHtml = (group.fields || []).map(f => renderField(f, config[f.key], config)).join("");

    return `
      <details class="settings-group" data-settings-group="${escapeHtml(groupId)}" ${openAttr}>
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

      if (f.key === "focus_mode_enabled") {
        el.addEventListener("change", () => {
          const container = document.getElementById("focusNpcContainer");
          if (container) {
            container.style.display = el.checked ? "" : "none";
          }
          submitSettingUpdate("focus_mode_enabled", el.checked);
        });
        return;
      }

      if (f.key === "focus_npcs" || f.type === "focus_npc_picker" || f.key === "exclude_npcs" || f.type === "exclude_npc_picker") {
        return;
      }

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
          if (f.key === "mode") {
            handleModeSelectChange(el);
          } else {
            submitSettingUpdate(f.key, el.value);
          }
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

  // Sidebar Presets Controls (Edit / Delete active custom preset if present)
  const presetFieldGroup = (accordion && typeof accordion.querySelector === "function")
    ? accordion.querySelector(".preset-field-group")
    : (typeof document !== "undefined" && typeof document.querySelector === "function" ? document.querySelector(".preset-field-group") : null);

  if (presetFieldGroup && typeof presetFieldGroup.querySelectorAll === "function") {
    presetFieldGroup.querySelectorAll(".sidebar-btn-edit-preset").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openPresetModal(btn.dataset.id);
      });
    });

    presetFieldGroup.querySelectorAll(".sidebar-btn-del-preset").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await deleteCustomPresetById(btn.dataset.id);
      });
    });
  }

  // Focus Mode Toggle (defensive listener if not attached in schema loop)
  const focusModeToggle = document.getElementById("setting_focus_mode_enabled");
  const focusNpcContainer = document.getElementById("focusNpcContainer");
  if (focusModeToggle && focusNpcContainer && !focusModeToggle._hasFocusListener) {
    focusModeToggle._hasFocusListener = true;
    focusModeToggle.addEventListener("change", () => {
      focusNpcContainer.style.display = focusModeToggle.checked ? "" : "none";
      submitSettingUpdate("focus_mode_enabled", focusModeToggle.checked);
    });
  }

  // Focus NPC Checkbox changes
  const focusNpcGrid = document.getElementById("focusNpcGrid");
  const counterBadge = document.getElementById("focusNpcCounterBadge");
  if (focusNpcGrid) {
    focusNpcGrid.addEventListener("change", (e) => {
      if (e.target && e.target.classList.contains("focus-npc-cb")) {
        const card = e.target.closest(".focus-npc-card");
        if (card) {
          card.classList.toggle("is-checked", e.target.checked);
          card.classList.toggle("active", e.target.checked);
        }

        const checkedBoxes = Array.from(focusNpcGrid.querySelectorAll(".focus-npc-cb:checked"));
        const selectedIds = checkedBoxes.map(cb => cb.value);
        if (counterBadge) {
          const total = focusNpcGrid.querySelectorAll(".focus-npc-cb").length;
          counterBadge.textContent = `${selectedIds.length} / ${total}`;
        }
        submitSettingUpdate("focus_npcs", selectedIds.join(","));
      }
    });
  }

  // Focus Select All & Deselect All Buttons
  const selectAllBtn = document.getElementById("focusNpcSelectAll");
  if (selectAllBtn && focusNpcGrid) {
    selectAllBtn.addEventListener("click", () => {
      const allBoxes = Array.from(focusNpcGrid.querySelectorAll(".focus-npc-cb"));
      allBoxes.forEach(cb => {
        cb.checked = true;
        const card = cb.closest(".focus-npc-card");
        if (card) {
          card.classList.add("is-checked");
          card.classList.add("active");
        }
      });
      const allIds = allBoxes.map(cb => cb.value);
      if (counterBadge) counterBadge.textContent = `${allIds.length} / ${allBoxes.length}`;
      submitSettingUpdate("focus_npcs", allIds.join(","));
    });
  }

  const deselectAllBtn = document.getElementById("focusNpcDeselectAll");
  if (deselectAllBtn && focusNpcGrid) {
    deselectAllBtn.addEventListener("click", () => {
      const allBoxes = Array.from(focusNpcGrid.querySelectorAll(".focus-npc-cb"));
      allBoxes.forEach(cb => {
        cb.checked = false;
        const card = cb.closest(".focus-npc-card");
        if (card) {
          card.classList.remove("is-checked");
          card.classList.remove("active");
        }
      });
      if (counterBadge) counterBadge.textContent = `0 / ${allBoxes.length}`;
      submitSettingUpdate("focus_npcs", "");
    });
  }

  // Exclude NPC Checkbox changes
  const excludeNpcGrid = document.getElementById("excludeNpcGrid");
  const excludeCounterBadge = document.getElementById("excludeNpcCounterBadge");
  if (excludeNpcGrid) {
    excludeNpcGrid.addEventListener("change", (e) => {
      if (e.target && e.target.classList.contains("exclude-npc-cb")) {
        const card = e.target.closest(".focus-npc-card");
        if (card) {
          card.classList.toggle("is-checked", e.target.checked);
          card.classList.toggle("active", e.target.checked);
        }

        const checkedBoxes = Array.from(excludeNpcGrid.querySelectorAll(".exclude-npc-cb:checked"));
        const selectedIds = checkedBoxes.map(cb => cb.value);
        if (excludeCounterBadge) {
          const total = excludeNpcGrid.querySelectorAll(".exclude-npc-cb").length;
          excludeCounterBadge.textContent = `${selectedIds.length} / ${total} Excluded`;
        }
        submitSettingUpdate("exclude_npcs", selectedIds.join(","));
      }
    });
  }

  // Exclude Select All & Deselect All Buttons
  const excludeSelectAllBtn = document.getElementById("excludeNpcSelectAll");
  if (excludeSelectAllBtn && excludeNpcGrid) {
    excludeSelectAllBtn.addEventListener("click", () => {
      const allBoxes = Array.from(excludeNpcGrid.querySelectorAll(".exclude-npc-cb"));
      allBoxes.forEach(cb => {
        cb.checked = true;
        const card = cb.closest(".focus-npc-card");
        if (card) {
          card.classList.add("is-checked");
          card.classList.add("active");
        }
      });
      const allIds = allBoxes.map(cb => cb.value);
      if (excludeCounterBadge) excludeCounterBadge.textContent = `${allIds.length} / ${allBoxes.length} Excluded`;
      submitSettingUpdate("exclude_npcs", allIds.join(","));
    });
  }

  const excludeDeselectAllBtn = document.getElementById("excludeNpcDeselectAll");
  if (excludeDeselectAllBtn && excludeNpcGrid) {
    excludeDeselectAllBtn.addEventListener("click", () => {
      const allBoxes = Array.from(excludeNpcGrid.querySelectorAll(".exclude-npc-cb"));
      allBoxes.forEach(cb => {
        cb.checked = false;
        const card = cb.closest(".focus-npc-card");
        if (card) {
          card.classList.remove("is-checked");
          card.classList.remove("active");
        }
      });
      if (excludeCounterBadge) excludeCounterBadge.textContent = `0 / ${allBoxes.length} Excluded`;
      submitSettingUpdate("exclude_npcs", "");
    });
  }

  // Tooltip tap toggle for mobile/touch
  if (accordion && !accordion._hasHelpTooltipListener) {
    accordion._hasHelpTooltipListener = true;
    accordion.addEventListener("click", (e) => {
      const btn = e.target.closest(".param-help-btn");
      const wrap = e.target.closest(".param-help-wrap");
      if (btn && wrap) {
        e.preventDefault();
        e.stopPropagation();
        const wasActive = wrap.classList.contains("is-active");
        document.querySelectorAll(".param-help-wrap.is-active").forEach(w => w.classList.remove("is-active"));
        if (!wasActive) {
          wrap.classList.add("is-active");
        }
      }
    });
  }

  // Attach listeners for sidebar date override card actions
  const sidebarOpenCalBtn = document.getElementById("sidebarOpenCalBtn");
  if (sidebarOpenCalBtn) {
    sidebarOpenCalBtn.addEventListener("click", (e) => {
      e.preventDefault();
      openCalendarModal();
    });
  }

  const sidebarResetDateBtn = document.getElementById("sidebarResetDateBtn");
  if (sidebarResetDateBtn) {
    sidebarResetDateBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      await resetDateOverride();
    });
  }

  // Adjust all parameter help tooltips so they don't overflow the right border
  updateAllHelpTooltipPositions();
  if (typeof updateSidebarForPlannerMode === "function") {
    updateSidebarForPlannerMode(activePlannerMode);
  }
}

// ---------------------------------------------------------------------------
// 4. Save File Management & Quick Selector
// ---------------------------------------------------------------------------

async function loadAvailableSaves() {
  try {
    const res = await fetch("/api/saves");
    if (!res.ok) return;
    const data = await res.json();
    populateSaveDropdown(data);
  } catch (e) {
    console.error("Failed to load saves list:", e);
  }
}

function populateSaveDropdown(data) {
  const select = document.getElementById("saveSelectDropdown");
  const resetBtn = document.getElementById("quickResetBtn");
  if (!select) return;

  const currentPath = data.current_save_path;
  const isAuto = data.is_auto;

  if (resetBtn) {
    resetBtn.style.display = isAuto ? "none" : "inline-flex";
  }

  let optionsHtml = `<option value="__auto__" ${isAuto ? "selected" : ""}>Auto-Detect (Latest save)</option>`;

  if (data.saves && data.saves.length > 0) {
    optionsHtml += `<optgroup label="Discovered Game Saves (${data.saves.length})">`;
    data.saves.forEach(s => {
      const isSelected = (!isAuto && currentPath === s.path) ? "selected" : "";
      const label = s.modified ? `${s.filename} (${s.modified})` : s.filename;
      optionsHtml += `<option value="${s.path}" ${isSelected}>${label}</option>`;
    });
    optionsHtml += `</optgroup>`;
  }

  optionsHtml += `<option value="__browse__">Browse & Import .sav File...</option>`;
  select.innerHTML = optionsHtml;
}

async function uploadSaveFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".sav")) {
    showToast("Invalid file! Please select a Fields of Mistria .sav file.");
    return;
  }

  showToast(`Importing "${file.name}"...`, 4000);

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/save/upload", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        errMsg = errJson.detail || errMsg;
      } catch (e) {}
      throw new Error(errMsg);
    }

    const resData = await res.json();
    if (resData.config) {
      currentSettings = resData.config;
      currentSettings.mode = "auto";
      currentSettings.active_preset_id = null;
      currentSettings.custom_preset_npcs = "";
      currentSettings.focus_mode_enabled = false;
    }
    localStorage.removeItem("fom_companion_active_preset_id");
    if (typeof resetReadyToCraftChecks === "function") {
      resetReadyToCraftChecks();
    }
    if (resData.plan) {
      renderPlan(resData.plan);
    }
    await loadAvailableSaves();
    if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
    renderBagPresetToolbar();
    showToast(`Save "${resData.filename || file.name}" imported successfully!`);
  } catch (err) {
    console.error("Save upload error:", err);
    showToast(`Import error: ${err.message}`);
  }
}

const DEFAULT_34_NPCS = [
  { id: "adeline", name: "Adeline" },
  { id: "balor", name: "Balor" },
  { id: "caldarus", name: "Caldarus" },
  { id: "celine", name: "Celine" },
  { id: "darcy", name: "Darcy" },
  { id: "dell", name: "Dell" },
  { id: "dozy", name: "Dozy" },
  { id: "eiland", name: "Eiland" },
  { id: "elsie", name: "Elsie" },
  { id: "errol", name: "Errol" },
  { id: "hayden", name: "Hayden" },
  { id: "hemlock", name: "Hemlock" },
  { id: "henrietta", name: "Henrietta" },
  { id: "holt", name: "Holt" },
  { id: "josephine", name: "Josephine" },
  { id: "juniper", name: "Juniper" },
  { id: "landen", name: "Landen" },
  { id: "louis", name: "Louis" },
  { id: "luc", name: "Luc" },
  { id: "maple", name: "Maple" },
  { id: "march", name: "March" },
  { id: "merri", name: "Merri" },
  { id: "nora", name: "Nora" },
  { id: "olric", name: "Olric" },
  { id: "reina", name: "Reina" },
  { id: "ryis", name: "Ryis" },
  { id: "seridia", name: "Seridia" },
  { id: "stillwell", name: "Stillwell" },
  { id: "taliferro", name: "Taliferro" },
  { id: "terithia", name: "Terithia" },
  { id: "valen", name: "Valen" },
  { id: "vera", name: "Vera" },
  { id: "wheedle", name: "Wheedle" },
  { id: "zorel", name: "Zorel" },
];

// ---------------------------------------------------------------------------
// Custom Bag Presets & Quick Presets Toolbar
// ---------------------------------------------------------------------------

const CUSTOM_PRESETS_STORAGE_KEY = "fom_custom_presets_v1";
let editingPresetId = null;

function loadCustomPresets() {
  try {
    const raw = localStorage.getItem(CUSTOM_PRESETS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter(p => p && typeof p === "object" && p.id && p.name && Array.isArray(p.villagers));
    }
  } catch (e) {
    console.warn("Could not load custom presets from localStorage:", e);
  }
  return [];
}

function saveCustomPresets(presets) {
  try {
    localStorage.setItem(CUSTOM_PRESETS_STORAGE_KEY, JSON.stringify(presets));
  } catch (e) {
    console.warn("Could not save custom presets to localStorage:", e);
  }
}

function getCustomPresetById(id) {
  if (!id) return null;
  const presets = loadCustomPresets();
  return presets.find(p => p.id === id) || null;
}

function renderBagPresetToolbar() {
  const container = document.getElementById("bagPresetPills");
  if (!container) return;

  const currentMode = currentSettings?.mode || "auto";
  const activeCustomId = currentSettings?.active_preset_id;
  const customPresets = loadCustomPresets();

  const standardPills = [
    { mode: "auto", label: "Auto", title: "Auto (Follow save calendar day)" },
    { mode: "weekday", label: "Townsfolk", title: "Weekday (26 Townsfolk only)" },
    { mode: "saturday", label: "Saturday", title: "Saturday Market (All 34 Villagers + Vendor Boost)" },
    { mode: "market-only", label: "Vendors", title: "Market Vendors Only (8 Villagers)" },
    { mode: "marriage", label: "Marriage", title: "Marriage Candidates (12 Romance Options)" },
    { mode: "all", label: "All", title: "All Villagers (Ignore calendar)" },
  ];

  let pillsHtml = standardPills.map(p => {
    const isActive = (currentMode === p.mode && !activeCustomId);
    return `
      <button type="button" class="bag-preset-pill ${isActive ? 'active' : ''}" data-mode="${p.mode}" title="${p.title}">
        ${p.label}
      </button>
    `;
  }).join("");

  // Custom preset pills
  pillsHtml += customPresets.map(p => {
    const isActive = (currentMode === "custom" && activeCustomId === p.id);
    return `
      <button type="button" class="bag-preset-pill ${isActive ? 'active' : ''}" data-custom-id="${p.id}" title="${escapeHtml(p.name)} (${p.villagers.length} villagers)">
        <span>${escapeHtml(p.name)}</span>
        <span class="pill-edit-btn" data-edit-id="${p.id}" title="Edit preset">✎</span>
      </button>
    `;
  }).join("");

  // + New Preset button
  pillsHtml += `
    <button type="button" class="bag-preset-pill btn-new-preset" id="bagPresetNewBtn" title="Create a new custom bag preset">
      + New Preset
    </button>
  `;

  container.innerHTML = pillsHtml;
}

function initBagPresetToolbarEvents() {
  const bar = document.getElementById("bagPresetBar");
  if (!bar || bar._hasPresetEvents) return;
  bar._hasPresetEvents = true;

  bar.addEventListener("click", async (e) => {
    const editBtn = e.target.closest(".pill-edit-btn");
    if (editBtn) {
      e.stopPropagation();
      const editId = editBtn.dataset.editId;
      openPresetModal(editId);
      return;
    }

    const newBtn = e.target.closest("#bagPresetNewBtn");
    if (newBtn) {
      openPresetModal();
      return;
    }

    const pill = e.target.closest(".bag-preset-pill");
    if (!pill) return;

    if (pill.dataset.customId) {
      const customId = pill.dataset.customId;
      const preset = getCustomPresetById(customId);
      if (!preset) return;

      currentSettings.mode = "custom";
      currentSettings.active_preset_id = customId;
      currentSettings.custom_preset_npcs = preset.villagers.join(",");
      localStorage.setItem("fom_companion_active_preset_id", customId);

      await submitSettingUpdate({
        mode: "custom",
        custom_preset_npcs: preset.villagers.join(","),
      });

      renderBagPresetToolbar();
      if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
      showToast(`Preset "${preset.name}" applied`, 1000);
      return;
    }

    if (pill.dataset.mode) {
      const mode = pill.dataset.mode;
      currentSettings.mode = mode;
      currentSettings.active_preset_id = null;
      currentSettings.custom_preset_npcs = "";
      localStorage.removeItem("fom_companion_active_preset_id");

      await submitSettingUpdate({
        mode: mode,
        custom_preset_npcs: "",
      });

      renderBagPresetToolbar();
      if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
      showToast(`Mode "${mode}" applied`, 1000);
      return;
    }
  });
}

function openPresetModal(presetId = null) {
  editingPresetId = presetId;
  const modal = document.getElementById("customPresetModal");
  if (!modal) return;

  const titleEl = document.getElementById("presetModalTitle");
  const nameInput = document.getElementById("presetNameInput");
  const deleteBtn = document.getElementById("presetDeleteBtn");
  const grid = document.getElementById("presetVillagerGrid");

  let initialVillagers = new Set();
  let initialName = "";

  if (presetId) {
    const preset = getCustomPresetById(presetId);
    if (preset) {
      initialName = preset.name || "";
      initialVillagers = new Set((preset.villagers || []).map(v => String(v).toLowerCase()));
      if (titleEl) titleEl.textContent = `Edit Preset: ${preset.name}`;
      if (deleteBtn) deleteBtn.style.display = "inline-block";
    }
  } else {
    if (titleEl) titleEl.textContent = "Create Custom Bag Preset";
    if (deleteBtn) deleteBtn.style.display = "none";
  }

  if (nameInput) nameInput.value = initialName;

  if (grid) {
    grid.innerHTML = DEFAULT_34_NPCS.map(npc => {
      const isChecked = initialVillagers.has(npc.id.toLowerCase());
      const checkedClass = isChecked ? "is-checked" : "";
      return `
        <label class="preset-villager-card ${checkedClass}" for="preset_npc_${npc.id}">
          <input type="checkbox" class="preset-villager-cb" id="preset_npc_${npc.id}" value="${npc.id}" ${isChecked ? 'checked' : ''} />
          <img class="preset-villager-portrait" src="/assets/sprites/npcs/${npc.id}" onerror="this.onerror=null; this.src='/assets/sprites/npcs/fallback'" alt="${npc.name}" loading="lazy" />
          <span class="preset-villager-name" title="${npc.name}">${npc.name}</span>
        </label>
      `;
    }).join("");
  }

  updatePresetModalCounter();
  modal.style.display = "flex";
  if (nameInput) setTimeout(() => nameInput.focus(), 60);
}

function closePresetModal() {
  const modal = document.getElementById("customPresetModal");
  if (modal) modal.style.display = "none";
  editingPresetId = null;
}

function updatePresetModalCounter() {
  const grid = document.getElementById("presetVillagerGrid");
  const counter = document.getElementById("presetCounterBadge");
  if (!grid || !counter) return;
  const checked = grid.querySelectorAll(".preset-villager-cb:checked").length;
  const total = grid.querySelectorAll(".preset-villager-cb").length;
  counter.textContent = `${checked} / ${total} Villagers`;
}

async function handleSavePreset() {
  const nameInput = document.getElementById("presetNameInput");
  const grid = document.getElementById("presetVillagerGrid");
  const name = (nameInput ? nameInput.value : "").trim();
  if (!name) {
    alert("Please enter a name for the preset.");
    if (nameInput) nameInput.focus();
    return;
  }

  const selected = [];
  if (grid) {
    grid.querySelectorAll(".preset-villager-cb:checked").forEach(cb => {
      selected.push(cb.value);
    });
  }

  if (selected.length === 0) {
    alert("Please select at least one villager for this preset.");
    return;
  }

  let presets = loadCustomPresets();
  let presetId = editingPresetId;

  if (presetId) {
    const idx = presets.findIndex(p => p.id === presetId);
    if (idx !== -1) {
      presets[idx].name = name;
      presets[idx].villagers = selected;
    } else {
      presetId = `preset_${Date.now()}`;
      presets.push({ id: presetId, name, villagers: selected, createdAt: Date.now() });
    }
  } else {
    presetId = `preset_${Date.now()}`;
    presets.push({ id: presetId, name, villagers: selected, createdAt: Date.now() });
  }

  saveCustomPresets(presets);

  currentSettings.mode = "custom";
  currentSettings.active_preset_id = presetId;
  currentSettings.custom_preset_npcs = selected.join(",");
  localStorage.setItem("fom_companion_active_preset_id", presetId);

  await submitSettingUpdate({
    mode: "custom",
    custom_preset_npcs: selected.join(","),
  });

  closePresetModal();
  if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
  renderBagPresetToolbar();
  showToast(`Preset "${name}" saved!`, 1500);
}

async function deleteCustomPresetById(presetId) {
  if (!presetId) return false;
  const preset = getCustomPresetById(presetId);
  const name = preset ? preset.name : "this preset";
  if (!confirm(`Are you sure you want to delete preset "${name}"?`)) return false;

  let presets = loadCustomPresets();
  presets = presets.filter(p => p.id !== presetId);
  saveCustomPresets(presets);

  if (currentSettings.active_preset_id === presetId) {
    currentSettings.mode = "auto";
    currentSettings.active_preset_id = null;
    currentSettings.custom_preset_npcs = "";
    localStorage.removeItem("fom_companion_active_preset_id");
    await submitSettingUpdate({
      mode: "auto",
      custom_preset_npcs: "",
    });
  }

  if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
  renderBagPresetToolbar();
  showToast(`Preset "${name}" deleted`, 1500);
  return true;
}

async function handleDeletePreset() {
  if (!editingPresetId) return;
  const deleted = await deleteCustomPresetById(editingPresetId);
  if (deleted) {
    closePresetModal();
  }
}

function initPresetModalEvents() {
  const modal = document.getElementById("customPresetModal");
  if (!modal || modal._hasEvents) return;
  modal._hasEvents = true;

  const closeBtn = document.getElementById("presetModalClose");
  const cancelBtn = document.getElementById("presetCancelBtn");
  const saveBtn = document.getElementById("presetSaveBtn");
  const deleteBtn = document.getElementById("presetDeleteBtn");
  const selectAllBtn = document.getElementById("presetSelectAllBtn");
  const clearBtn = document.getElementById("presetClearBtn");
  const grid = document.getElementById("presetVillagerGrid");

  closeBtn?.addEventListener("click", closePresetModal);
  cancelBtn?.addEventListener("click", closePresetModal);
  saveBtn?.addEventListener("click", handleSavePreset);
  deleteBtn?.addEventListener("click", handleDeletePreset);

  modal.addEventListener("click", (e) => {
    if (e.target === modal) closePresetModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.style.display !== "none") {
      closePresetModal();
    }
  });

  selectAllBtn?.addEventListener("click", () => {
    if (!grid) return;
    grid.querySelectorAll(".preset-villager-cb").forEach(cb => {
      cb.checked = true;
      cb.closest(".preset-villager-card")?.classList.add("is-checked");
    });
    updatePresetModalCounter();
  });

  clearBtn?.addEventListener("click", () => {
    if (!grid) return;
    grid.querySelectorAll(".preset-villager-cb").forEach(cb => {
      cb.checked = false;
      cb.closest(".preset-villager-card")?.classList.remove("is-checked");
    });
    updatePresetModalCounter();
  });

  grid?.addEventListener("change", (e) => {
    if (e.target && e.target.classList.contains("preset-villager-cb")) {
      const card = e.target.closest(".preset-villager-card");
      if (card) {
        if (e.target.checked) card.classList.add("is-checked");
        else card.classList.remove("is-checked");
      }
      updatePresetModalCounter();
    }
  });
}

async function handleModeSelectChange(el) {
  const val = el.value;
  if (val === "__create_custom__") {
    // Revert dropdown display to previous active
    const prevVal = (currentSettings?.mode === "custom" && currentSettings?.active_preset_id)
      ? `custom:${currentSettings.active_preset_id}`
      : (currentSettings?.mode || "auto");
    el.value = prevVal;
    openPresetModal();
    return;
  }

  if (val.startsWith("custom:")) {
    const presetId = val.slice("custom:".length);
    const preset = getCustomPresetById(presetId);
    if (!preset) return;

    currentSettings.mode = "custom";
    currentSettings.active_preset_id = preset.id;
    currentSettings.custom_preset_npcs = preset.villagers.join(",");
    localStorage.setItem("fom_companion_active_preset_id", preset.id);

    await submitSettingUpdate({
      mode: "custom",
      custom_preset_npcs: preset.villagers.join(","),
    });

    renderBagPresetToolbar();
    showToast(`Preset "${preset.name}" applied`, 1000);
    return;
  }

  // Standard mode
  currentSettings.mode = val;
  currentSettings.active_preset_id = null;
  currentSettings.custom_preset_npcs = "";
  localStorage.removeItem("fom_companion_active_preset_id");

  await submitSettingUpdate({
    mode: val,
    custom_preset_npcs: "",
  });

  renderBagPresetToolbar();
  showToast(`Mode updated`, 1000);
}

function adjustHelpTooltipPosition(wrap) {
  if (!wrap) return;
  const tooltip = wrap.querySelector(".param-help-tooltip");
  if (!tooltip) return;

  // Measure wrapping button position relative to window and parent card/sidebar
  const wrapRect = wrap.getBoundingClientRect();
  const card = wrap.closest(".sidebar-card, .sidebar") || document.body;
  const cardRect = card.getBoundingClientRect();
  const maxRight = Math.min(window.innerWidth - 12, cardRect.right - 8);

  // If tooltip starting at wrapRect.left would exceed maxRight boundary, align to right
  if (wrapRect.left + 210 > maxRight) {
    tooltip.classList.add("align-right");
    wrap.classList.add("tooltip-align-right");
  } else {
    tooltip.classList.remove("align-right");
    wrap.classList.remove("tooltip-align-right");
  }
}

function updateAllHelpTooltipPositions() {
  document.querySelectorAll(".param-help-wrap").forEach(adjustHelpTooltipPosition);
}

function renderHelpIcon(helpText, label = "") {
  if (!helpText) return "";
  return `
    <span class="param-help-wrap">
      <button type="button" class="param-help-btn" aria-label="Explanation for ${label || 'parameter'}" tabindex="0"><img class="inline-icon" src="/static/icons/ui/icon_info.svg" alt="Info"></button>
      <span class="param-help-tooltip" role="tooltip">${helpText}</span>
    </span>
  `;
}

function renderField(field, currentVal, config = {}) {
  const id = `setting_${field.key}`;
  const helpHtml = renderHelpIcon(field.help, field.label);

  if (field.type === "focus_npc_picker" || field.key === "focus_npcs") {
    const isModeEnabled = Boolean((config && config.focus_mode_enabled !== undefined) ? config.focus_mode_enabled : currentSettings?.focus_mode_enabled);
    const selectedNpcs = new Set(
      (currentVal || "")
        .split(",")
        .map(s => s.trim().toLowerCase())
        .filter(Boolean)
    );

    let npcList = field.options;
    if (!npcList && currentPlan?.npc_progress) {
      npcList = Object.values(currentPlan.npc_progress).map(n => ({
        id: String(n.npc_id || '').toLowerCase(),
        name: n.name || n.npc_id,
      }));
    }
    if (!npcList || npcList.length === 0) {
      npcList = DEFAULT_34_NPCS;
    }

    const cardsHtml = npcList.map(npc => {
      const isChecked = selectedNpcs.has(npc.id.toLowerCase());
      const activeClass = isChecked ? 'is-checked active' : '';
      return `
        <label class="focus-npc-card ${activeClass}" for="focus_npc_${npc.id}">
          <input type="checkbox" class="focus-npc-cb" id="focus_npc_${npc.id}" value="${npc.id}" ${isChecked ? 'checked' : ''} />
          <img class="focus-npc-portrait" src="/assets/sprites/npcs/${npc.id}" alt="${npc.name}" loading="lazy" />
          <span class="focus-npc-name" title="${npc.name}">${npc.name}</span>
        </label>
      `;
    }).join("");

    return `
      <div class="field-group focus-npc-picker-group">
        <label>${field.label}${helpHtml}</label>
        <div id="focusNpcContainer" class="focus-npc-container" style="${isModeEnabled ? '' : 'display: none;'}">
          <div class="focus-npc-toolbar">
            <div class="focus-npc-actions">
              <button type="button" class="focus-npc-btn" id="focusNpcSelectAll">Select All</button>
              <button type="button" class="focus-npc-btn" id="focusNpcDeselectAll">Deselect All</button>
            </div>
            <span class="focus-npc-counter" id="focusNpcCounterBadge">${selectedNpcs.size} / ${npcList.length}</span>
          </div>
          <div class="focus-npc-grid" id="focusNpcGrid">
            ${cardsHtml}
          </div>
        </div>
      </div>
    `;
  }

  if (field.type === "exclude_npc_picker" || field.key === "exclude_npcs") {
    const selectedNpcs = new Set(
      (currentVal || "")
        .split(",")
        .map(s => s.trim().toLowerCase())
        .filter(Boolean)
    );

    let npcList = field.options;
    if (!npcList && currentPlan?.npc_progress) {
      npcList = Object.values(currentPlan.npc_progress).map(n => ({
        id: String(n.npc_id || '').toLowerCase(),
        name: n.name || n.npc_id,
      }));
    }
    if (!npcList || npcList.length === 0) {
      npcList = DEFAULT_34_NPCS;
    }

    const cardsHtml = npcList.map(npc => {
      const isChecked = selectedNpcs.has(npc.id.toLowerCase());
      const activeClass = isChecked ? 'is-checked active' : '';
      return `
        <label class="focus-npc-card ${activeClass}" for="exclude_npc_${npc.id}">
          <input type="checkbox" class="exclude-npc-cb" id="exclude_npc_${npc.id}" value="${npc.id}" ${isChecked ? 'checked' : ''} />
          <img class="focus-npc-portrait" src="/assets/sprites/npcs/${npc.id}" alt="${npc.name}" loading="lazy" />
          <span class="focus-npc-name" title="${npc.name}">${npc.name}</span>
        </label>
      `;
    }).join("");

    return `
      <div class="field-group exclude-npc-picker-group">
        <label>${field.label}${helpHtml}</label>
        <div id="excludeNpcContainer" class="focus-npc-container">
          <div class="focus-npc-toolbar">
            <div class="focus-npc-actions">
              <button type="button" class="focus-npc-btn" id="excludeNpcSelectAll">Exclude All</button>
              <button type="button" class="focus-npc-btn" id="excludeNpcDeselectAll">Clear</button>
            </div>
            <span class="focus-npc-counter" id="excludeNpcCounterBadge">${selectedNpcs.size} / ${npcList.length} Excluded</span>
          </div>
          <div class="focus-npc-grid" id="excludeNpcGrid">
            ${cardsHtml}
          </div>
        </div>
      </div>
    `;
  }

  if (field.type === "checkbox") {
    const checked = currentVal ? "checked" : "";
    return `
      <div class="checkbox-group">
        <input type="checkbox" id="${id}" ${checked} />
        <label for="${id}">${field.label}</label>
        ${helpHtml}
      </div>
    `;
  }

  if (field.type === "select") {
    let optionsHtml = "";
    if (field.key === "mode") {
      const customPresets = loadCustomPresets();
      const isCustomActive = (currentSettings?.mode === "custom" && currentSettings?.active_preset_id);
      const activeCustomId = (currentSettings?.mode === "custom") ? currentSettings?.active_preset_id : null;
      const activeCustomPreset = activeCustomId ? getCustomPresetById(activeCustomId) : null;

      optionsHtml = (field.options || []).map(opt => {
        const sel = (!isCustomActive && opt.value === currentVal) ? "selected" : "";
        return `<option value="${opt.value}" ${sel}>${opt.label}</option>`;
      }).join("");

      if (customPresets.length > 0) {
        optionsHtml += `<optgroup label="Custom Presets">`;
        optionsHtml += customPresets.map(p => {
          const sel = (isCustomActive && currentSettings.active_preset_id === p.id) ? "selected" : "";
          return `<option value="custom:${p.id}" ${sel}>Preset: ${escapeHtml(p.name)} (${p.villagers.length} villagers)</option>`;
        }).join("");
        optionsHtml += `</optgroup>`;
      }

      optionsHtml += `<option value="__create_custom__">➕ Create Custom Preset...</option>`;

      let activePresetHtml = "";
      if (isCustomActive && activeCustomPreset) {
        activePresetHtml = `
          <div class="sidebar-active-preset-bar">
            <span class="sidebar-active-preset-info" title="${escapeHtml(activeCustomPreset.villagers.join(', '))}">
              Active: <strong>${escapeHtml(activeCustomPreset.name)}</strong> (${activeCustomPreset.villagers.length})
            </span>
            <div class="sidebar-preset-row-actions">
              <button type="button" class="sidebar-btn-edit-preset" data-id="${activeCustomPreset.id}" title="Edit preset">✏️ Edit</button>
              <button type="button" class="sidebar-btn-del-preset" data-id="${activeCustomPreset.id}" title="Delete preset">🗑️</button>
            </div>
          </div>
        `;
      }

      return `
        <div class="field-group preset-field-group">
          <label for="${id}">${field.label}${helpHtml}</label>
          <select id="${id}">${optionsHtml}</select>
          ${activePresetHtml}
        </div>
      `;
    } else {
      optionsHtml = (field.options || []).map(opt => {
        const sel = opt.value === currentVal ? "selected" : "";
        return `<option value="${opt.value}" ${sel}>${opt.label}</option>`;
      }).join("");
    }

    return `
      <div class="field-group">
        <label for="${id}">${field.label}${helpHtml}</label>
        <select id="${id}">${optionsHtml}</select>
      </div>
    `;
  }

  if (field.key === "date_override" || field.type === "date_override") {
    const isOverridden = Boolean(currentPlan?.in_game_date?.is_overridden);
    const dateInfo = currentPlan?.in_game_date || {};
    const saveDate = dateInfo.save_date;
    const targetDateStr = `${dateInfo.season || "Spring"} Day ${dateInfo.day || 1}, Year ${dateInfo.year || 1}`;
    const overrideVal = (currentVal !== null && currentVal !== undefined) ? currentVal : "";

    return `
      <div class="field-group">
        <label>${field.label}${helpHtml}</label>
        <div class="date-override-card">
          <div class="date-override-status-row">
            <div class="date-override-badge-active">
              <img class="inline-icon" src="/static/icons/ui/icon_calendar.png" alt="Calendar">
              <span>${targetDateStr}</span>
            </div>
            <span class="date-override-state-pill ${isOverridden ? 'pill-overridden' : 'pill-live'}">
              ${isOverridden ? 'Overridden' : 'Save Date'}
            </span>
          </div>

          ${isOverridden && saveDate ? `
            <div class="date-override-note">
              Using override instead of game save (Save: <strong>${saveDate.season} Day ${saveDate.day}, Year ${saveDate.year}</strong>)
            </div>
          ` : ''}

          <div class="date-override-actions">
            <button type="button" class="btn-cal-action btn-cal-primary" id="sidebarOpenCalBtn" title="Open interactive 28-day FoM calendar">
              <img class="inline-icon" src="/static/icons/ui/icon_calendar.png" alt="Calendar"> Open Calendar
            </button>
            ${isOverridden ? `
              <button type="button" class="btn-cal-action btn-cal-reset" id="sidebarResetDateBtn" title="Reset date override and follow game save">
                <img class="inline-icon" src="/static/icons/ui/icon_refresh.svg" alt="Reset"> Reset
              </button>
            ` : ''}
          </div>

          <div class="date-manual-input-row">
            <input type="text" id="${id}" class="date-manual-input" value="${overrideVal}" placeholder="Or type e.g. 'saturday', 'winter 10'..." title="Type custom date or festival" />
          </div>
        </div>
      </div>
    `;
  }

  if (field.type === "range") {
    const val = currentVal ?? field.min;
    return `
      <div class="field-group">
        <label for="${id}">${field.label}${helpHtml}</label>
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
      <label for="${id}">${field.label}${helpHtml}</label>
      <input type="${inputType}" id="${id}" ${valAttr} ${placeholderAttr} ${minMaxAttr} />
    </div>
  `;
}

async function submitSettingUpdate(keyOrUpdates, value) {
  try {
    let payload = {};
    if (typeof keyOrUpdates === "object" && keyOrUpdates !== null) {
      payload = keyOrUpdates;
    } else {
      payload = { [keyOrUpdates]: value };
    }
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const resData = await res.json();
    if (resData.config) {
      const activePresetId = currentSettings?.active_preset_id;
      currentSettings = resData.config;
      if (activePresetId !== undefined) {
        currentSettings.active_preset_id = activePresetId;
      }
    }
    if (resData.plan) {
      renderPlan(resData.plan);
    }
    const keys = Object.keys(payload).join(", ");
    showToast(`Setting "${keys}" updated`);
  } catch (err) {
    console.error("Failed to update setting:", err);
    showToast(`Error updating settings: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// 4b. FoM 28-Day Seasonal Calendar Modal & Date Override
// ---------------------------------------------------------------------------

let calModalState = {
  year: 1,
  season: "spring",
  selectedDay: 1,
  selectedSeason: "spring",
  selectedYear: 1,
  pendingReset: false,
  isDirty: false,
};

const FOM_FESTIVALS = {
  spring: { 17: "Spring Festival" },
  summer: { 28: "Shooting Star Festival" },
  fall: { 10: "Harvest Festival" },
  winter: { 10: "Animal Festival" },
};

function openCalendarModal() {
  const modal = document.getElementById("calendarModal");
  if (!modal) return;

  const inGame = currentPlan?.in_game_date || {};
  calModalState.year = inGame.year || 1;
  let s = (inGame.season || "spring").toLowerCase();
  if (s === "autumn") s = "fall";
  calModalState.season = s;
  calModalState.selectedDay = inGame.day || 1;
  calModalState.selectedSeason = s;
  calModalState.selectedYear = inGame.year || 1;
  calModalState.pendingReset = false;
  calModalState.isDirty = false;

  updateCalendarToolbar();
  renderCalendarDaysGrid();
  updateCalendarStatusBar();

  modal.classList.remove("closing");
  modal.style.display = "flex";
}

function closeCalendarModal() {
  const modal = document.getElementById("calendarModal");
  if (!modal) return;
  modal.classList.add("closing");
  setTimeout(() => {
    modal.style.display = "none";
    modal.classList.remove("closing");
  }, 200);
}

function updateCalendarToolbar() {
  const yearDisplay = document.getElementById("calYearDisplay");
  if (yearDisplay) {
    yearDisplay.textContent = `Year ${calModalState.year}`;
  }

  document.querySelectorAll(".cal-season-tab").forEach(tab => {
    const s = tab.getAttribute("data-season");
    if (s === calModalState.season) {
      tab.classList.add("active");
    } else {
      tab.classList.remove("active");
    }
  });
}

function updateCalendarStatusBar() {
  const textEl = document.getElementById("calStatusDateText");
  const badgeEl = document.getElementById("calStatusBadge");
  const noteEl = document.getElementById("calSaveDateNote");
  if (!textEl) return;

  const inGame = currentPlan?.in_game_date || {};
  const isOverridden = Boolean(inGame.is_overridden);
  const saveDate = inGame.save_date;

  const selSeason = calModalState.selectedSeason || calModalState.season;
  const selDay = calModalState.selectedDay || 1;
  const selYear = calModalState.selectedYear || calModalState.year;

  const capSeason = selSeason.charAt(0).toUpperCase() + selSeason.slice(1);
  const isSat = (selDay % 7 === 6);
  const fest = FOM_FESTIVALS[selSeason]?.[selDay];

  let desc = `${capSeason} Day ${selDay}, Year ${selYear}`;
  if (isSat) desc += " • (Saturday Market)";
  if (fest) desc += ` • (${fest})`;
  textEl.textContent = desc;

  if (badgeEl) {
    if (calModalState.pendingReset) {
      badgeEl.textContent = "Revert to Save Date";
      badgeEl.className = "cal-status-badge badge-save";
    } else if (calModalState.isDirty) {
      badgeEl.textContent = "Selected (Click Done to apply)";
      badgeEl.className = "cal-status-badge badge-override";
    } else if (isOverridden) {
      badgeEl.textContent = "Date Overridden";
      badgeEl.className = "cal-status-badge badge-override";
    } else {
      badgeEl.textContent = "Following Save Date";
      badgeEl.className = "cal-status-badge badge-save";
    }
  }

  if (noteEl) {
    if (saveDate) {
      noteEl.textContent = `Save: ${saveDate.season} Day ${saveDate.day}, Year ${saveDate.year}`;
    } else {
      noteEl.textContent = "";
    }
  }
}

function renderCalendarDaysGrid() {
  const grid = document.getElementById("calendarDaysGrid");
  if (!grid) return;

  const inGame = currentPlan?.in_game_date || {};
  const saveDate = inGame.save_date;

  const festivals = FOM_FESTIVALS[calModalState.season] || {};

  let html = "";
  for (let day = 1; day <= 28; day++) {
    const isSat = (day % 7 === 6);
    const festName = festivals[day];

    const isSaveDate = Boolean(
      saveDate &&
      saveDate.season.toLowerCase() === calModalState.season &&
      saveDate.day === day &&
      saveDate.year === calModalState.year
    );

    const isCurrentModalSelection = Boolean(
      calModalState.selectedDay === day &&
      calModalState.selectedSeason === calModalState.season &&
      calModalState.selectedYear === calModalState.year
    );

    let cellClasses = ["cal-day-cell"];
    if (isSat) cellClasses.push("is-sat");
    if (isSaveDate) cellClasses.push("is-save-date");
    if (isCurrentModalSelection) cellClasses.push("is-selected");

    html += `
      <div class="${cellClasses.join(' ')}" data-day="${day}" title="Day ${day}${isSat ? ' (Saturday Market)' : ''}${festName ? ' - ' + festName : ''}">
        <div class="cal-cell-top">
          <span class="cal-cell-number">${day}</span>
          <div class="cal-cell-badges">
            ${isSat ? '<span class="cal-cell-sat-tag"><img class="inline-icon" src="/static/icons/ui/icon_saturday.png" alt="Sat"> Sat</span>' : ''}
            ${isSaveDate ? '<span class="cal-cell-save-tag"><img class="inline-icon" src="/static/icons/ui/icon_save.png" alt="Save"> Save</span>' : ''}
          </div>
        </div>
        <div class="cal-cell-content">
          ${festName ? `<span class="cal-cell-fest-tag" title="${festName}"><img class="inline-icon" src="/static/icons/ui/icon_festival.png" alt="Festival"> ${festName}</span>` : ''}
        </div>
      </div>
    `;
  }

  grid.innerHTML = html;

  // Add click listeners to day cells: select day locally without updating backend yet
  grid.querySelectorAll(".cal-day-cell").forEach(cell => {
    cell.addEventListener("click", () => {
      const day = parseInt(cell.getAttribute("data-day"), 10);
      selectCalendarDay(day);
    });
  });
}

function selectCalendarDay(day) {
  calModalState.selectedDay = day;
  calModalState.selectedSeason = calModalState.season;
  calModalState.selectedYear = calModalState.year;
  calModalState.pendingReset = false;
  calModalState.isDirty = true;

  renderCalendarDaysGrid();
  updateCalendarStatusBar();
}

async function applyCalendarModalDone() {
  const pendingReset = calModalState.pendingReset;
  const isDirty = calModalState.isDirty;
  const selSeason = calModalState.selectedSeason || calModalState.season;
  const selDay = calModalState.selectedDay || 1;
  const selYear = calModalState.selectedYear || calModalState.year;

  calModalState.pendingReset = false;
  calModalState.isDirty = false;

  closeCalendarModal();

  if (pendingReset) {
    showToast("Reverting to game save date...", 2000);
    await submitSettingUpdate("date_override", "");
    await loadSettings();
  } else if (isDirty) {
    const capSeason = selSeason.charAt(0).toUpperCase() + selSeason.slice(1);
    const formatted = `${capSeason} ${selDay}, Year ${selYear}`;
    showToast(`Applying date override: ${formatted}...`, 2000);
    await submitSettingUpdate("date_override", formatted);
    await loadSettings();
  }
}

function stageResetToSaveDate() {
  const inGame = currentPlan?.in_game_date || {};
  const saveDate = inGame.save_date;
  if (saveDate) {
    calModalState.year = saveDate.year || 1;
    let s = (saveDate.season || "spring").toLowerCase();
    if (s === "autumn") s = "fall";
    calModalState.season = s;
    calModalState.selectedSeason = s;
    calModalState.selectedYear = saveDate.year || 1;
    calModalState.selectedDay = saveDate.day || 1;
  }
  calModalState.pendingReset = true;
  calModalState.isDirty = true;

  updateCalendarToolbar();
  renderCalendarDaysGrid();
  updateCalendarStatusBar();
}

async function resetDateOverride() {
  showToast("Reverting to game save date...", 2000);
  await submitSettingUpdate("date_override", "");
  const inGame = currentPlan?.in_game_date || {};
  const saveDate = inGame.save_date;
  calModalState.year = saveDate?.year || inGame.year || 1;
  let s = (saveDate?.season || inGame.season || "spring").toLowerCase();
  if (s === "autumn") s = "fall";
  calModalState.season = s;
  calModalState.selectedSeason = s;
  calModalState.selectedYear = saveDate?.year || inGame.year || 1;
  calModalState.selectedDay = saveDate?.day || inGame.day || 1;
  calModalState.pendingReset = false;
  calModalState.isDirty = false;

  updateCalendarToolbar();
  renderCalendarDaysGrid();
  updateCalendarStatusBar();
  loadSettings();
}

// ---------------------------------------------------------------------------
// 5. Initialisation
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  setupEventSource();
  fetchPlan();
  loadSettings();
  loadAvailableSaves();
  initBagPresetToolbarEvents();
  initPresetModalEvents();
  renderBagPresetToolbar();
  initFutureWifeBannerEvents();
  renderFutureWifeBanner();

  // Mode Switcher & Almanac Events
  initModeSwitcher();
  initAlmanacEventListeners();

  // Calendar Modal Controls & Header Date Badge Interaction
  const dateBadge = document.getElementById("dateBadge");
  if (dateBadge) {
    dateBadge.addEventListener("click", () => openCalendarModal());
    dateBadge.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openCalendarModal();
      }
    });
  }

  const calCloseBtn = document.getElementById("calCloseBtn");
  if (calCloseBtn) {
    calCloseBtn.addEventListener("click", async () => {
      await applyCalendarModalDone();
    });
  }

  const calendarModalClose = document.getElementById("calendarModalClose");
  if (calendarModalClose) {
    calendarModalClose.addEventListener("click", () => closeCalendarModal());
  }

  const calendarModal = document.getElementById("calendarModal");
  if (calendarModal) {
    calendarModal.addEventListener("click", (e) => {
      if (e.target === calendarModal) {
        closeCalendarModal();
      }
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const calModal = document.getElementById("calendarModal");
      if (calModal && calModal.style.display !== "none") {
        closeCalendarModal();
      }
    }
  });

  const calYearPrev = document.getElementById("calYearPrev");
  if (calYearPrev) {
    calYearPrev.addEventListener("click", () => {
      calModalState.year = Math.max(1, calModalState.year - 1);
      updateCalendarToolbar();
      renderCalendarDaysGrid();
      updateCalendarStatusBar();
    });
  }

  const calYearNext = document.getElementById("calYearNext");
  if (calYearNext) {
    calYearNext.addEventListener("click", () => {
      calModalState.year += 1;
      updateCalendarToolbar();
      renderCalendarDaysGrid();
      updateCalendarStatusBar();
    });
  }

  document.querySelectorAll(".cal-season-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      const season = tab.getAttribute("data-season");
      if (season) {
        calModalState.season = season;
        updateCalendarToolbar();
        renderCalendarDaysGrid();
        updateCalendarStatusBar();
      }
    });
  });

  const calResetSaveBtn = document.getElementById("calResetSaveBtn");
  if (calResetSaveBtn) {
    calResetSaveBtn.addEventListener("click", () => {
      stageResetToSaveDate();
    });
  }

  const saveDropdown = document.getElementById("saveSelectDropdown");
  if (saveDropdown) {
    saveDropdown.addEventListener("change", async () => {
      const val = saveDropdown.value;
      if (val === "__browse__") {
        await loadAvailableSaves();
        const fileInput = document.getElementById("globalSaveFileInput");
        if (fileInput) fileInput.click();
      } else if (val === "__auto__") {
        if (typeof resetReadyToCraftChecks === "function") {
          resetReadyToCraftChecks();
        }
        currentSettings.mode = "auto";
        currentSettings.active_preset_id = null;
        currentSettings.custom_preset_npcs = "";
        currentSettings.focus_mode_enabled = false;
        localStorage.removeItem("fom_companion_active_preset_id");
        await submitSettingUpdate({
          save_file: null,
          mode: "auto",
          custom_preset_npcs: "",
          focus_mode_enabled: false,
        });
        await loadAvailableSaves();
        if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
        renderBagPresetToolbar();
        showToast("Switched to auto-detecting newest game save");
      } else if (val) {
        if (typeof resetReadyToCraftChecks === "function") {
          resetReadyToCraftChecks();
        }
        currentSettings.mode = "auto";
        currentSettings.active_preset_id = null;
        currentSettings.custom_preset_npcs = "";
        currentSettings.focus_mode_enabled = false;
        localStorage.removeItem("fom_companion_active_preset_id");
        await submitSettingUpdate({
          save_file: val,
          mode: "auto",
          custom_preset_npcs: "",
          focus_mode_enabled: false,
        });
        await loadAvailableSaves();
        if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
        renderBagPresetToolbar();
        const name = val.split(/[/\\]/).pop();
        showToast(`Switched active save to "${name}"`);
      }
    });
  }

  const quickResetBtn = document.getElementById("quickResetBtn");
  if (quickResetBtn) {
    quickResetBtn.addEventListener("click", async () => {
      if (typeof resetReadyToCraftChecks === "function") {
        resetReadyToCraftChecks();
      }
      currentSettings.mode = "auto";
      currentSettings.active_preset_id = null;
      currentSettings.custom_preset_npcs = "";
      currentSettings.focus_mode_enabled = false;
      localStorage.removeItem("fom_companion_active_preset_id");
      await submitSettingUpdate({
        save_file: null,
        mode: "auto",
        custom_preset_npcs: "",
        focus_mode_enabled: false,
      });
      await loadAvailableSaves();
      if (currentSchema) renderSettingsAccordion(currentSchema, currentSettings);
      renderBagPresetToolbar();
      showToast("Switched to auto-detecting newest game save");
    });
  }

  const quickImportBtn = document.getElementById("quickImportBtn");
  const globalSaveFileInput = document.getElementById("globalSaveFileInput");
  if (quickImportBtn && globalSaveFileInput) {
    quickImportBtn.addEventListener("click", () => {
      globalSaveFileInput.click();
    });
    globalSaveFileInput.addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (file) {
        await uploadSaveFile(file);
      }
      globalSaveFileInput.value = "";
    });
  }

  const saveStatusBox = document.getElementById("saveStatusBox");
  if (saveStatusBox) {
    saveStatusBox.addEventListener("dragover", (e) => {
      e.preventDefault();
      saveStatusBox.classList.add("drag-over");
    });
    saveStatusBox.addEventListener("dragleave", (e) => {
      e.preventDefault();
      saveStatusBox.classList.remove("drag-over");
    });
    saveStatusBox.addEventListener("drop", async (e) => {
      e.preventDefault();
      saveStatusBox.classList.remove("drag-over");
      const file = e.dataTransfer.files[0];
      if (file) {
        await uploadSaveFile(file);
      }
    });
  }

  const refreshBtn = document.getElementById("refreshBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      refreshBtn.disabled = true;
      try {
        const res = await fetch("/api/plan/refresh", { method: "POST" });
        const data = await res.json();
        if (typeof resetReadyToCraftChecks === "function") {
          resetReadyToCraftChecks();
        }
        renderPlan(data);
        showToast("Plan refreshed manually");
      } catch (err) {
        showToast("Error refreshing plan: " + err.message);
      } finally {
        refreshBtn.disabled = false;
      }
    });
  }

  // Statistics Dashboard Drawer Toggles & Search
  const toggleCompletedBtn = document.getElementById("toggleCompletedBtn");
  if (toggleCompletedBtn) toggleCompletedBtn.addEventListener("click", () => setStatsDrawer("completed"));

  const toggleIncompleteBtn = document.getElementById("toggleIncompleteBtn");
  if (toggleIncompleteBtn) toggleIncompleteBtn.addEventListener("click", () => setStatsDrawer("incomplete"));

  const toggleRecipesBtn = document.getElementById("toggleRecipesBtn");
  if (toggleRecipesBtn) toggleRecipesBtn.addEventListener("click", () => setStatsDrawer("recipes"));

  const closeCompletedDrawerBtn = document.getElementById("closeCompletedDrawerBtn");
  if (closeCompletedDrawerBtn) closeCompletedDrawerBtn.addEventListener("click", () => setStatsDrawer("completed"));

  const closeIncompleteDrawerBtn = document.getElementById("closeIncompleteDrawerBtn");
  if (closeIncompleteDrawerBtn) closeIncompleteDrawerBtn.addEventListener("click", () => setStatsDrawer("incomplete"));

  const closeIncompleteDrawerBottomBtn = document.getElementById("closeIncompleteDrawerBottomBtn");
  if (closeIncompleteDrawerBottomBtn) closeIncompleteDrawerBottomBtn.addEventListener("click", () => setStatsDrawer("incomplete"));

  const closeRecipesDrawerBtn = document.getElementById("closeRecipesDrawerBtn");
  if (closeRecipesDrawerBtn) closeRecipesDrawerBtn.addEventListener("click", () => setStatsDrawer("recipes"));

  const closeRecipesDrawerBottomBtn = document.getElementById("closeRecipesDrawerBottomBtn");
  if (closeRecipesDrawerBottomBtn) closeRecipesDrawerBottomBtn.addEventListener("click", () => setStatsDrawer("recipes"));

  const toggleMoreRecipesBtn = document.getElementById("toggleMoreRecipesBtn");
  if (toggleMoreRecipesBtn) {
    toggleMoreRecipesBtn.addEventListener("click", () => {
      recipesExpanded = !recipesExpanded;
      if (currentPlan) {
        renderRecipesDrawerContent(currentPlan.unobtained_recipes || []);
      }
    });
  }

  const incompleteSearchInput = document.getElementById("incompleteSearchInput");
  if (incompleteSearchInput) {
    incompleteSearchInput.addEventListener("input", (e) => {
      incompleteSearchFilter = e.target.value;
      if (currentPlan) {
        renderIncompleteDrawerContent(currentPlan.incomplete_npcs_details || (currentPlan.stats && currentPlan.stats.incomplete_npcs_details) || []);
      }
    });
  }

  const recipeSearchInput = document.getElementById("recipeSearchInput");
  if (recipeSearchInput) {
    recipeSearchInput.addEventListener("input", (e) => {
      recipeSearchFilter = e.target.value;
      if (currentPlan) {
        renderRecipesDrawerContent(currentPlan.unobtained_recipes || []);
      }
    });
  }

  // Delegated click listener for focus suggestion blocked NPCs expand/collapse
  document.addEventListener("click", (e) => {
    const expandBtn = e.target.closest(".npc-expand-btn");
    if (expandBtn) {
      e.preventDefault();
      toggleBlockedNpcs(expandBtn, true);
      return;
    }
    const collapseBtn = e.target.closest(".npc-collapse-btn");
    if (collapseBtn) {
      e.preventDefault();
      toggleBlockedNpcs(collapseBtn, false);
      return;
    }

    // Backdrop touch / outside click to collapse active stats drawer on mobile
    if (activeStatsDrawer) {
      const activeDrawerEl = document.getElementById(`drawer${activeStatsDrawer.charAt(0).toUpperCase() + activeStatsDrawer.slice(1)}`);
      if (activeDrawerEl && activeDrawerEl.style.display !== "none") {
        if (!activeDrawerEl.contains(e.target) && !e.target.closest(".stat-drawer-toggle-btn") && !e.target.closest(".stat-card")) {
          setStatsDrawer(activeStatsDrawer);
        }
      }
    }
  });

  // Dynamic tooltip alignment on mouseenter and focusin to prevent right border overflow
  document.addEventListener("mouseenter", (e) => {
    const wrap = e.target.closest && e.target.closest(".param-help-wrap");
    if (wrap) adjustHelpTooltipPosition(wrap);
  }, true);

  document.addEventListener("focusin", (e) => {
    const wrap = e.target.closest && e.target.closest(".param-help-wrap");
    if (wrap) adjustHelpTooltipPosition(wrap);
  }, true);

  // Responsive window resize for D3 crafting tree container and tooltip positioning
  window.addEventListener("resize", () => {
    updateAllHelpTooltipPositions();
    const treeModal = document.getElementById("treeModal");
    if (treeModal && treeModal.style.display !== "none" && _treeModalSvg) {
      const body = document.getElementById("treeModalBody");
      if (body) {
        const w = body.clientWidth;
        const h = body.clientHeight;
        if (w > 0 && h > 0) {
          _treeModalSvg.attr("width", w).attr("height", h);
        }
      }
    }
  });
});

// ===========================================================================
// Milestone 4: Almanac Planner Engine & Interactive Controls
// ===========================================================================

// Alias support for element IDs between specifications
const _origGetElementById = document.getElementById.bind(document);
const ID_ALIASES = {
  tabGiftPlanner: "tabBtnGiftPlanner",
  tabAlmanacPlanner: "tabBtnAlmanacPlanner",
  almanacItemDrawer: "almanacCategoryDrawer",
  readyToCraftCountBadge: "readyToCraftBadge",
  almanacBlockersCountBadge: "almanacBlockersBadge",
  almanacSourcesCountBadge: "almanacSourcesBadge",
  almanacCraftQueue: "almanacBatchQueueContainer",
  almanacSourcesPanel: "almanacSourcesContainer",
};
document.getElementById = function(id) {
  let el = _origGetElementById(id);
  if (!el && ID_ALIASES[id]) {
    el = _origGetElementById(ID_ALIASES[id]);
  }
  return el;
};

let activePlannerMode = "gift";
let currentAlmanacCategory = null;
let currentAlmanacStatusFilter = "all";
let currentAlmanacSeasonFilter = "all";
let currentAlmanacSearchQuery = "";
let currentAlmanacBlockerSearchQuery = "";
let almanacBatchViewMode = "chains";
let currentAlmanacTier = "all";
let furnitureActiveSwatches = {};
try {
  const savedSwatches = localStorage.getItem("fom_selected_swatches");
  if (savedSwatches) furnitureActiveSwatches = JSON.parse(savedSwatches);
} catch (e) {
  furnitureActiveSwatches = {};
}

window._almanacTreeData = window._almanacTreeData || {};
window.__giftScrollY = 0;
window.__almanacScrollY = 0;

const ALMANAC_STATIONS = {
  cooking: {
    label: "Cooking",
    icon: "/static/icons/ui/spr_ui_skill_icon_cooking.png",
    class: "station-cooking",
    actionVerb: "Cook"
  },
  milling: {
    label: "Milling",
    icon: "/static/icons/locations/mill.png",
    class: "station-milling",
    actionVerb: "Mill"
  },
  woodcrafting: {
    label: "Woodcrafting",
    icon: "/static/icons/ui/spr_ui_skill_icon_woodcrafting.png",
    class: "station-woodcrafting",
    actionVerb: "Craft"
  },
  blacksmithing: {
    label: "Blacksmithing",
    icon: "/static/icons/ui/spr_ui_skill_icon_blacksmithing.png",
    class: "station-blacksmithing",
    actionVerb: "Forge"
  },
  refining: {
    label: "Stone Refining",
    icon: "/static/icons/ui/spr_ui_skill_icon_mining.png",
    class: "station-refining",
    actionVerb: "Refine"
  },
  dragon_forging: {
    label: "Dragon Forging",
    icon: "/static/icons/ui/spr_ui_journal_almanac_icon_artifacts.png",
    class: "station-dragon_forging",
    actionVerb: "Infuse"
  }
};

function resolveAlmanacCategoryIconUrl(categoryId) {
  return `/static/icons/ui/spr_ui_journal_almanac_icon_${categoryId}.png`;
}

function resolveAlmanacItemSpriteUrl(item) {
  if (!item) return "/static/icons/ui/icon_gift.png";
  if (item.icon_sprite) {
    return `/static/icons/items/${item.icon_sprite}.png`;
  }
  return `/static/icons/items/spr_ui_item_${item.item_id}.png`;
}

function updateSidebarForPlannerMode(mode) {
  const targetMode = mode === "almanac" ? "almanac" : "gift";
  const groups = document.querySelectorAll("#settingsAccordion .settings-group");
  groups.forEach(detailsEl => {
    const groupId = detailsEl.getAttribute("data-settings-group") || "";
    const isAlmanacGroup = groupId === "almanac";
    if (targetMode === "almanac") {
      if (isAlmanacGroup) {
        detailsEl.style.display = "";
        detailsEl.open = true;
      } else {
        detailsEl.style.display = "none";
      }
    } else {
      if (isAlmanacGroup) {
        detailsEl.style.display = "none";
      } else {
        detailsEl.style.display = "";
      }
    }
  });

  const giftMetaRows = document.querySelectorAll('.save-status-row[data-planner-mode="gift"]');
  giftMetaRows.forEach(row => {
    row.style.display = targetMode === "gift" ? "" : "none";
  });
}

function initModeSwitcher() {
  const tabGift = document.getElementById("tabBtnGiftPlanner") || document.getElementById("tabGiftPlanner");
  const tabAlmanac = document.getElementById("tabBtnAlmanacPlanner") || document.getElementById("tabAlmanacPlanner");

  if (tabGift) {
    tabGift.addEventListener("click", () => switchPlannerMode("gift"));
  }
  if (tabAlmanac) {
    tabAlmanac.addEventListener("click", () => switchPlannerMode("almanac"));
  }

  let savedMode = "gift";
  try {
    savedMode = localStorage.getItem("fom_active_planner_mode") || "gift";
  } catch (e) {}

  if (savedMode === "almanac") {
    switchPlannerMode("almanac", false);
  } else {
    updateSidebarForPlannerMode("gift");
  }
}

function switchPlannerMode(mode, saveScroll = true) {
  const targetMode = mode === "almanac" ? "almanac" : "gift";
  if (targetMode === activePlannerMode && saveScroll) {
    updateSidebarForPlannerMode(targetMode);
    return;
  }

  const tabGift = document.getElementById("tabBtnGiftPlanner") || document.getElementById("tabGiftPlanner");
  const tabAlmanac = document.getElementById("tabBtnAlmanacPlanner") || document.getElementById("tabAlmanacPlanner");
  const sectionGift = document.getElementById("giftPlannerSection");
  const sectionAlmanac = document.getElementById("almanacPlannerSection");

  if (activePlannerMode === "gift") {
    window.__giftScrollY = window.scrollY;
  } else {
    window.__almanacScrollY = window.scrollY;
  }

  activePlannerMode = targetMode;
  try {
    localStorage.setItem("fom_active_planner_mode", targetMode);
  } catch (e) {}

  if (tabGift) {
    tabGift.classList.toggle("active", targetMode === "gift");
    tabGift.setAttribute("aria-selected", targetMode === "gift" ? "true" : "false");
  }
  if (tabAlmanac) {
    tabAlmanac.classList.toggle("active", targetMode === "almanac");
    tabAlmanac.setAttribute("aria-selected", targetMode === "almanac" ? "true" : "false");
  }

  if (sectionGift) sectionGift.style.display = targetMode === "gift" ? "block" : "none";
  if (sectionAlmanac) sectionAlmanac.style.display = targetMode === "almanac" ? "block" : "none";

  updateSidebarForPlannerMode(targetMode);

  const restoreY = targetMode === "gift" ? (window.__giftScrollY || 0) : (window.__almanacScrollY || 0);
  window.scrollTo({ top: restoreY, behavior: "instant" });
}

function renderAlmanacPlanner(almanac) {
  if (!almanac) return;
  renderAlmanacDashboard(almanac);
  renderReadyToCraftQueue(almanac.ready_to_craft || [], almanacBatchViewMode);
  renderRawMaterialBlockers(almanac.raw_material_blockers || []);
  renderSourcePriority(almanac.sources_by_tier, currentAlmanacTier);

  // If category drawer is open, keep it open and re-render drawer items
  const backdrop = document.getElementById("almanacDrawerBackdrop");
  if (backdrop && backdrop.classList.contains("active") && currentAlmanacCategory) {
    const catData = almanac.categories?.[currentAlmanacCategory];
    if (catData) {
      const subtitle = document.getElementById("almanacDrawerSubtitle");
      if (subtitle) subtitle.textContent = `${catData.obtained} / ${catData.total} Obtained (${catData.percentage}%)`;
      renderDrawerItems();
    }
  }
}

function renderAlmanacDashboard(almanac) {
  if (!almanac) return;

  const summary = almanac.summary || {};
  const headerPct = document.getElementById("headerAlmanacPct");
  const overallBadge = document.getElementById("almanacOverallBadge");
  const grid = document.getElementById("almanacCategoryGrid");

  const pct = (summary.percentage !== undefined) ? summary.percentage : 0;
  if (headerPct) headerPct.textContent = `${pct}%`;
  if (overallBadge) {
    overallBadge.textContent = `${summary.obtained || 0} / ${summary.total || 0} Collected (${pct}%)`;
  }

  if (!grid) return;
  const categories = almanac.categories || {};
  const catKeys = [
    "artifacts", "blacksmithing", "bugs", "cooked_dishes", "crops",
    "date_inspiration", "fish", "forageables", "furniture",
    "materials", "ranching", "song_crystal"
  ];

  grid.innerHTML = catKeys.map(catKey => {
    const cat = categories[catKey] || { name: catKey, obtained: 0, total: 0, percentage: 0 };
    const iconUrl = resolveAlmanacCategoryIconUrl(catKey);
    const isComplete = cat.total > 0 && cat.obtained >= cat.total;
    const missingCount = Math.max(0, cat.total - cat.obtained);

    return `
      <div class="almanac-category-card" role="button" tabindex="0" onclick="openAlmanacDrawer('${catKey}')" onkeydown="if(event.key==='Enter'||event.key===' ')openAlmanacDrawer('${catKey}')" aria-label="Open ${cat.name} details">
        <div class="almanac-card-header">
          <div class="almanac-card-title-group">
            <img class="almanac-card-icon" src="${iconUrl}" onerror="this.src='/static/icons/ui/icon_gift.png';" alt="${escapeHtml(cat.name)}" />
            <h3 class="almanac-card-name">${escapeHtml(cat.name)}</h3>
          </div>
          ${isComplete ? '<span class="status-pill pill-obtained">COMPLETE</span>' : `<span class="badge-counter">${missingCount} Missing</span>`}
        </div>

        <div class="almanac-card-metrics">
          <span class="almanac-card-count">${cat.obtained} / ${cat.total}</span>
          <span class="almanac-card-pct">${cat.percentage}%</span>
        </div>

        <div class="stat-progress-track">
          <div class="stat-progress-fill" style="width: ${Math.min(100, Math.max(0, cat.percentage))}%; ${isComplete ? 'background: #16a34a;' : ''}"></div>
        </div>

        <div class="almanac-card-subtext">
          <span>${catKey === 'furniture' ? `${cat.groups_obtained || 0}/${cat.groups_total || 0} groups` : `${cat.obtained} acquired`}</span>
          <span class="almanac-card-action">Browse Items →</span>
        </div>
      </div>
    `;
  }).join("");
}

function openAlmanacDrawer(categoryKey) {
  currentAlmanacCategory = categoryKey;
  const backdrop = document.getElementById("almanacDrawerBackdrop");
  const title = document.getElementById("almanacDrawerTitle");
  const subtitle = document.getElementById("almanacDrawerSubtitle");
  const icon = document.getElementById("almanacDrawerIcon");

  const catData = currentPlan?.almanac?.categories?.[categoryKey];
  if (!catData) return;

  if (title) title.textContent = catData.name;
  if (subtitle) subtitle.textContent = `${catData.obtained} / ${catData.total} Obtained (${catData.percentage}%)`;
  if (icon) icon.src = resolveAlmanacCategoryIconUrl(categoryKey);

  currentAlmanacStatusFilter = "all";
  currentAlmanacSeasonFilter = "all";
  currentAlmanacSearchQuery = "";
  const sInput = document.getElementById("almanacSearchInput");
  if (sInput) sInput.value = "";
  const sClear = document.getElementById("almanacSearchClearBtn");
  if (sClear) sClear.style.display = "none";

  const readyToCraftSet = new Set((currentPlan?.almanac?.ready_to_craft || []).map(r => r.item_id));
  const countAllEl = document.getElementById("countStatusAll");
  const countObtEl = document.getElementById("countStatusObtained");
  const countMisEl = document.getElementById("countStatusMissing");
  const countCrfEl = document.getElementById("countStatusCraftable");

  if (categoryKey === "furniture" && catData.groups) {
    if (countAllEl) countAllEl.textContent = catData.groups.length;
    if (countObtEl) countObtEl.textContent = catData.groups.filter(g => g.is_obtained).length;
    if (countMisEl) countMisEl.textContent = catData.groups.filter(g => !g.is_obtained).length;
    if (countCrfEl) countCrfEl.textContent = catData.groups.filter(g => (g.swatches || []).some(s => readyToCraftSet.has(s.item_id))).length;
  } else {
    const items = catData.items || [];
    if (countAllEl) countAllEl.textContent = items.length;
    if (countObtEl) countObtEl.textContent = items.filter(it => it.is_obtained).length;
    if (countMisEl) countMisEl.textContent = items.filter(it => !it.is_obtained).length;
    if (countCrfEl) countCrfEl.textContent = items.filter(it => readyToCraftSet.has(it.item_id)).length;
  }

  updateFilterPillStates();
  renderDrawerItems();

  if (backdrop) {
    backdrop.style.display = "flex";
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(() => {
        if (backdrop.classList && typeof backdrop.classList.add === "function") {
          backdrop.classList.add("active");
        }
      });
    } else if (backdrop.classList && typeof backdrop.classList.add === "function") {
      backdrop.classList.add("active");
    }
  }
  if (document.body && document.body.style) {
    document.body.style.overflow = "hidden";
  }
}

function closeAlmanacDrawer() {
  const backdrop = document.getElementById("almanacDrawerBackdrop");
  if (!backdrop) return;
  if (backdrop.classList && typeof backdrop.classList.remove === "function") {
    backdrop.classList.remove("active");
  }
  setTimeout(() => {
    backdrop.style.display = "none";
    if (document.body && document.body.style) {
      document.body.style.overflow = "";
    }
  }, 240);
}

function updateFilterPillStates() {
  document.querySelectorAll("#almanacStatusFilters .pill-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.filter === currentAlmanacStatusFilter);
  });
  document.querySelectorAll("#almanacSeasonFilters .pill-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.season === currentAlmanacSeasonFilter);
  });
}

function renderDrawerItems() {
  const container = document.getElementById("almanacItemsGrid");
  const showingCount = document.getElementById("almanacShowingCount");
  if (!container || !currentAlmanacCategory || !currentPlan?.almanac) return;

  const catData = currentPlan.almanac.categories[currentAlmanacCategory];
  if (!catData) return;

  const readyToCraftSet = new Set((currentPlan.almanac.ready_to_craft || []).map(r => r.item_id));
  const bagPlanSet = new Set((currentPlan.bag_plan || []).map(b => String(b.item_id).toLowerCase()));

  if (currentAlmanacCategory === "furniture" && catData.groups) {
    renderFurnitureDrawerGroups(catData.groups, container, showingCount, readyToCraftSet, bagPlanSet);
    return;
  }

  const items = catData.items || [];
  const filtered = items.filter(it => {
    if (currentAlmanacStatusFilter === "obtained" && !it.is_obtained) return false;
    if (currentAlmanacStatusFilter === "missing" && it.is_obtained) return false;
    if (currentAlmanacStatusFilter === "craftable" && !readyToCraftSet.has(it.item_id)) return false;

    if (currentAlmanacSeasonFilter !== "all") {
      const itSeasons = (it.seasons || []).map(s => String(s).toLowerCase());
      if (itSeasons.length > 0 && !itSeasons.includes(currentAlmanacSeasonFilter)) return false;
    }

    if (currentAlmanacSearchQuery) {
      const name = (it.name || "").toLowerCase();
      const sources = (it.sources || []).map(s => (s.location || "")).join(" ").toLowerCase();
      const station = (it.recipe?.station || "").toLowerCase();
      if (!name.includes(currentAlmanacSearchQuery) && !sources.includes(currentAlmanacSearchQuery) && !station.includes(currentAlmanacSearchQuery)) {
        return false;
      }
    }
    return true;
  });

  if (showingCount) showingCount.textContent = `Showing ${filtered.length} of ${items.length} items`;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state-notice">No items found matching the selected filters.</div>`;
    return;
  }

  container.innerHTML = filtered.map(it => {
    const isCraftable = readyToCraftSet.has(it.item_id);
    const inTodayBag = bagPlanSet.has(String(it.item_id).toLowerCase());
    const spriteUrl = resolveAlmanacItemSpriteUrl(it);
    const seasonsStr = (it.seasons && it.seasons.length > 0)
      ? it.seasons.map(s => String(s).toUpperCase()).join(", ")
      : "All Seasons";

    return `
      <div class="almanac-item-card ${it.is_obtained ? 'is-obtained' : ''}">
        <div class="almanac-item-thumb-box">
          <img class="almanac-item-thumb" src="${spriteUrl}" onerror="this.src='/static/icons/ui/icon_gift.png';" alt="${escapeHtml(it.name)}" />
        </div>
        <div class="almanac-item-content">
          <div class="almanac-item-header">
            <span class="almanac-item-name">${escapeHtml(it.name)}</span>
            ${it.is_obtained ? '<span class="status-pill pill-obtained">Obtained</span>' : '<span class="status-pill pill-missing">Missing</span>'}
          </div>

          <div style="font-size: 0.8rem; color: var(--ink-muted);">
            🪙 ${it.value?.bin ? it.value.bin + 't' : 'Non-sellable'} • ${seasonsStr}
          </div>

          <div class="almanac-item-tags">
            ${inTodayBag ? '<span class="badge-synergy-gift">🎁 Today\'s Gift</span>' : ''}
            ${(it.gift_synergy || []).map(g => `<span class="badge-synergy-gift">❤️ ${escapeHtml(g)}</span>`).join('')}
            ${(it.quest_synergy || []).map(q => `<span class="badge-synergy-quest">📜 ${escapeHtml(q)}</span>`).join('')}
            ${isCraftable ? '<span class="badge-craftable-now">⚒️ Craftable Now</span>' : ''}
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function renderFurnitureDrawerGroups(groups, container, showingCount, readyToCraftSet, bagPlanSet) {
  const filtered = groups.filter(g => {
    if (currentAlmanacStatusFilter === "obtained" && !g.is_obtained) return false;
    if (currentAlmanacStatusFilter === "missing" && g.is_obtained) return false;
    if (currentAlmanacStatusFilter === "craftable") {
      const hasCraftableSwatch = (g.swatches || []).some(s => readyToCraftSet.has(s.item_id));
      if (!hasCraftableSwatch) return false;
    }
    if (currentAlmanacSearchQuery) {
      const matchName = (g.name || "").toLowerCase().includes(currentAlmanacSearchQuery);
      const matchSwatch = (g.swatches || []).some(s => (s.name || s.swatch_name || "").toLowerCase().includes(currentAlmanacSearchQuery));
      if (!matchName && !matchSwatch) return false;
    }
    return true;
  });

  if (showingCount) showingCount.textContent = `Showing ${filtered.length} of ${groups.length} furniture recipes`;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state-notice">No furniture recipes matching the selected filters.</div>`;
    return;
  }

  container.innerHTML = filtered.map(g => {
    const swatches = g.swatches || [];
    let selectedItemId = furnitureActiveSwatches[g.group_key];
    if (!selectedItemId || !swatches.some(s => s.item_id === selectedItemId)) {
      const unobtained = swatches.find(s => !s.is_obtained);
      selectedItemId = unobtained ? unobtained.item_id : (swatches[0]?.item_id || "");
    }
    const activeSwatch = swatches.find(s => s.item_id === selectedItemId) || swatches[0] || {};
    const spriteUrl = resolveAlmanacItemSpriteUrl(activeSwatch);

    return `
      <div class="swatch-group-card" id="furn_group_${escapeHtml(g.group_key)}">
        <div style="display: flex; gap: 12px; align-items: center;">
          <div class="almanac-item-thumb-box">
            <img class="almanac-item-thumb" id="thumb_${escapeHtml(g.group_key)}" src="${spriteUrl}" onerror="this.src='/static/icons/ui/icon_gift.png';" alt="${escapeHtml(g.name)}" />
          </div>
          <div style="flex: 1;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span class="almanac-item-name">${escapeHtml(g.name)}</span>
              <span class="badge-counter">${g.swatches_obtained || 0} / ${g.swatches_total || swatches.length} Swatches</span>
            </div>
            <div class="swatch-pills-row" style="margin-top: 8px;">
              ${swatches.map(s => `
                <button type="button" class="swatch-pill ${s.is_obtained ? 'is-obtained' : ''} ${s.item_id === activeSwatch.item_id ? 'active' : ''}" onclick="selectFurnitureSwatch('${escapeHtml(g.group_key)}', '${escapeHtml(s.item_id)}')">
                  ${escapeHtml(s.swatch_name || 'Standard')}
                </button>
              `).join('')}
            </div>
          </div>
        </div>
      </div>
    `;
  }).join("");
}

function selectFurnitureSwatch(groupKey, itemId) {
  furnitureActiveSwatches[groupKey] = itemId;
  try {
    localStorage.setItem("fom_selected_swatches", JSON.stringify(furnitureActiveSwatches));
  } catch (e) {}

  const catData = currentPlan?.almanac?.categories?.furniture;
  if (!catData) return;
  const group = (catData.groups || []).find(g => g.group_key === groupKey);
  if (!group) return;
  const swatch = (group.swatches || []).find(s => s.item_id === itemId);
  if (!swatch) return;

  const thumb = document.getElementById(`thumb_${groupKey}`);
  if (thumb) thumb.src = resolveAlmanacItemSpriteUrl(swatch);

  const container = document.getElementById(`furn_group_${groupKey}`);
  if (container) {
    container.querySelectorAll(".swatch-pill").forEach(p => {
      const match = p.getAttribute("onclick")?.includes(itemId);
      p.classList.toggle("active", Boolean(match));
    });
  }
}

const readyToCraftState = {
  viewMode: "chains",
  stationFilter: "all",
  visibleLimit: 5,
  showCompleted: false,
  checkedStepKeys: new Set(),
  saveIdentity: null,
};

const almanacBlockersState = {
  categoryFilter: "all",
  visibleLimit: 5,
  showCompleted: false,
  checkedItemIds: new Set(),
};

const almanacSourcesState = {
  visibleLimit: 5,
  showCompleted: false,
  checkedSourceKeys: new Set(),
};

function resetReadyToCraftChecks() {
  readyToCraftState.checkedStepKeys.clear();
  readyToCraftState.showCompleted = false;
  readyToCraftState.visibleLimit = 5;
  readyToCraftState.stationFilter = "all";

  almanacBlockersState.checkedItemIds.clear();
  almanacBlockersState.showCompleted = false;
  almanacBlockersState.visibleLimit = 5;
  almanacBlockersState.categoryFilter = "all";
  currentAlmanacBlockerSearchQuery = "";
  const blockerSearchInput = document.getElementById("almanacBlockerSearch");
  if (blockerSearchInput) blockerSearchInput.value = "";

  almanacSourcesState.checkedSourceKeys.clear();
  almanacSourcesState.showCompleted = false;
  almanacSourcesState.visibleLimit = 5;
  currentAlmanacTier = "all";
  const tierTabs = document.querySelectorAll("#almanacTierTabs .tier-tab-btn");
  tierTabs.forEach(b => b.classList.toggle("active", (b.dataset.tier || "all") === "all"));
}

function syncReadyToCraftSaveIdentity(data) {
  if (!data) {
    resetReadyToCraftChecks();
    readyToCraftState.saveIdentity = null;
    return;
  }
  const sd = data.in_game_date?.save_date || {};
  const fingerprint = `${data.save_info?.filename || ""}::${sd.year ?? ""}::${sd.season ?? ""}::${sd.day ?? ""}`;
  if (readyToCraftState.saveIdentity !== null && readyToCraftState.saveIdentity !== fingerprint) {
    resetReadyToCraftChecks();
  }
  readyToCraftState.saveIdentity = fingerprint;
}

function isCraftStepChecked(step) {
  return Boolean(step && step._stepKey && readyToCraftState.checkedStepKeys.has(step._stepKey));
}

function isCraftBatchCompleted(batch) {
  return Boolean(batch && Array.isArray(batch.steps) && batch.steps.length > 0 && batch.steps.every(isCraftStepChecked));
}

function setReadyToCraftStationFilter(station) {
  readyToCraftState.stationFilter = station || "all";
  readyToCraftState.visibleLimit = 5;
  if (currentPlan?.almanac?.ready_to_craft) {
    renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, almanacBatchViewMode);
  }
}

function toggleCraftBatchCheck(batchKey) {
  const queueSteps = currentPlan?.almanac?.ready_to_craft || [];
  const batches = groupBatchQueue(queueSteps);
  const targetBatch = batches.find(b => b.batchKey === batchKey);
  if (!targetBatch) return;

  const allChecked = isCraftBatchCompleted(targetBatch);
  targetBatch.steps.forEach(s => {
    if (!s._stepKey) return;
    if (allChecked) {
      readyToCraftState.checkedStepKeys.delete(s._stepKey);
    } else {
      readyToCraftState.checkedStepKeys.add(s._stepKey);
    }
  });
  renderReadyToCraftQueue(queueSteps, almanacBatchViewMode);
}

function toggleCraftStepCheck(stepKey) {
  if (!stepKey) return;
  if (readyToCraftState.checkedStepKeys.has(stepKey)) {
    readyToCraftState.checkedStepKeys.delete(stepKey);
  } else {
    readyToCraftState.checkedStepKeys.add(stepKey);
  }
  if (currentPlan?.almanac?.ready_to_craft) {
    renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, almanacBatchViewMode);
  }
}

function toggleShowCompletedCrafts() {
  readyToCraftState.showCompleted = !readyToCraftState.showCompleted;
  if (currentPlan?.almanac?.ready_to_craft) {
    renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, almanacBatchViewMode);
  }
}

function showNext5ReadyToCraft() {
  readyToCraftState.visibleLimit += 5;
  if (currentPlan?.almanac?.ready_to_craft) {
    renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, almanacBatchViewMode);
  }
}

function collapseReadyToCraft() {
  readyToCraftState.visibleLimit = 5;
  if (currentPlan?.almanac?.ready_to_craft) {
    renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, almanacBatchViewMode);
  }
}

function groupBatchQueue(queueSteps) {
  if (!queueSteps || !Array.isArray(queueSteps) || queueSteps.length === 0) return [];
  const batches = [];
  let currentSteps = [];
  const batchCountsByTarget = {};

  const finalizeBatch = (stepsArr) => {
    const targetStep = stepsArr[stepsArr.length - 1];
    const baseTargetId = String(targetStep.item_id || targetStep.item_name || "batch");
    batchCountsByTarget[baseTargetId] = (batchCountsByTarget[baseTargetId] || 0) + 1;
    const batchKey = batchCountsByTarget[baseTargetId] === 1
      ? baseTargetId
      : `${baseTargetId}#${batchCountsByTarget[baseTargetId]}`;

    stepsArr.forEach((s, idx) => {
      s._batchKey = batchKey;
      s._stepKey = `${batchKey}::${s.item_id || idx}::${idx}`;
    });

    const totalUnlocks = stepsArr.filter(s => s.unlocks_almanac).length;
    const stations = [...new Set(stepsArr.map(s => s.station || "cooking"))];
    const giftSynergies = [...new Set(stepsArr.flatMap(s => s.gift_synergy || []))];
    const questSynergies = [...new Set(stepsArr.flatMap(s => s.quest_synergy || []))];

    batches.push({
      batchKey,
      target: targetStep,
      steps: [...stepsArr],
      totalUnlocks,
      stations,
      giftSynergies,
      questSynergies
    });
  };

  for (const step of queueSteps) {
    currentSteps.push(step);
    if (!step.is_intermediate) {
      finalizeBatch(currentSteps);
      currentSteps = [];
    }
  }

  if (currentSteps.length > 0) {
    finalizeBatch(currentSteps);
  }

  return batches;
}

function renderReadyToCraftStationFilters(queueSteps, batches, viewMode) {
  const filterBar = document.getElementById("readyToCraftStationFilters");
  if (!filterBar) return;

  if (!queueSteps || queueSteps.length === 0) {
    filterBar.innerHTML = "";
    filterBar.style.display = "none";
    return;
  }

  const presentStationSet = new Set(queueSteps.map(s => s.station || "cooking"));
  const availableStations = [
    ...Object.keys(ALMANAC_STATIONS).filter(st => presentStationSet.has(st)),
    ...[...presentStationSet].filter(st => !ALMANAC_STATIONS[st])
  ];

  if (readyToCraftState.stationFilter !== "all" && !presentStationSet.has(readyToCraftState.stationFilter)) {
    readyToCraftState.stationFilter = "all";
  }

  const activeBatchesAll = batches.filter(b => !isCraftBatchCompleted(b));
  const activeStepsAll = queueSteps.filter(s => !isCraftStepChecked(s));
  const allCount = viewMode === "steps" ? activeStepsAll.length : activeBatchesAll.length;

  const pillsHtml = [
    `<button type="button" class="craft-station-pill ${readyToCraftState.stationFilter === "all" ? "active" : ""}" data-station="all" onclick="setReadyToCraftStationFilter('all')">
      <span>All</span>
      <span class="craft-station-count">${allCount}</span>
    </button>`
  ];

  availableStations.forEach(st => {
    const meta = ALMANAC_STATIONS[st] || { label: st, icon: "/static/icons/ui/icon_cooking.png", class: "station-cooking" };
    const count = viewMode === "steps"
      ? activeStepsAll.filter(s => (s.station || "cooking") === st).length
      : activeBatchesAll.filter(b => b.steps.some(s => !isCraftStepChecked(s) && (s.station || "cooking") === st)).length;
    const isActive = readyToCraftState.stationFilter === st;

    pillsHtml.push(`
      <button type="button" class="craft-station-pill ${isActive ? "active" : ""}" data-station="${escapeHtml(st)}" onclick="setReadyToCraftStationFilter('${escapeHtml(st)}')">
        <img class="mini-station-icon" src="${meta.icon}" alt="">
        <span>${escapeHtml(meta.label)}</span>
        <span class="craft-station-count">${count}</span>
      </button>
    `);
  });

  filterBar.style.display = "flex";
  filterBar.innerHTML = pillsHtml.join("");
}

function renderCraftStepRowHtml(step, stepLabel, extraClass = "") {
  const stMeta = ALMANAC_STATIONS[step.station] || ALMANAC_STATIONS.cooking;
  const itemSprite = resolveAlmanacItemSpriteUrl(step);
  const isStepDone = isCraftStepChecked(step);

  const ingsHtml = (step.ingredients || []).map(ing => `
    <span class="ing-chip">
      <img class="mini-sprite" src="${resolveAlmanacItemSpriteUrl(ing)}" alt="" onerror="this.style.display='none'">
      ${ing.count}× ${escapeHtml(ing.display_name || ing.item_id)}
    </span>
  `).join(" + ");

  const unlockBadge = step.unlocks_almanac
    ? `<span class="step-unlock-pill">📖 Unlocks Slot</span>`
    : `<span class="step-intermediate-pill">⚡ Intermediate</span>`;

  const consumedNote = (step.is_intermediate && step.consumed_by)
    ? `<span class="step-consumed-note">↳ Consumed to craft ${escapeHtml(step.consumed_by)}</span>`
    : ``;

  return `
    <div class="batch-step-row ${isStepDone ? "is-checked" : ""} ${extraClass}">
      <label class="craft-check-label step-check-label" title="${isStepDone ? "Uncheck step" : "Mark step as crafted"}">
        <input type="checkbox" class="craft-checkbox" ${isStepDone ? "checked" : ""} onchange="toggleCraftStepCheck('${escapeHtml(step._stepKey || "")}')">
      </label>
      <span class="step-num-pill">${escapeHtml(stepLabel)}</span>
      <span class="station-badge ${stMeta.class}">
        <img class="mini-station-icon" src="${stMeta.icon}" alt=""> ${stMeta.label}
      </span>
      <div class="step-action-desc">
        ${ingsHtml} <span class="flow-arrow">➔</span>
        <span class="prod-chip">
          <img class="mini-sprite" src="${itemSprite}" alt="" onerror="this.src='/static/icons/ui/icon_gift.png'">
          ${step.quantity || 1}× ${escapeHtml(step.item_name)}
        </span>
      </div>
      ${unlockBadge}
      ${consumedNote}
    </div>
  `;
}

function renderCraftBatchCardHtml(batch, bIdx) {
  const target = batch.target;
  const targetSprite = resolveAlmanacItemSpriteUrl(target);
  const isBatchDone = isCraftBatchCompleted(batch);

  const stationBadgesHtml = batch.stations.map(st => {
    const meta = ALMANAC_STATIONS[st] || ALMANAC_STATIONS.cooking;
    return `<span class="station-badge ${meta.class}"><img class="station-icon" src="${meta.icon}" alt=""> ${meta.label}</span>`;
  }).join(" ");

  const unlockBadge = batch.totalUnlocks > 0
    ? `<span class="almanac-unlock-badge"><img class="inline-icon" src="/static/icons/ui/spr_ui_journal_tab_almanac_enabled.png" alt=""> Unlocks ${batch.totalUnlocks} Slot${batch.totalUnlocks > 1 ? 's' : ''}</span>`
    : ``;

  const giftTagsHtml = batch.giftSynergies.map(tag => `<span class="d3-node-npc-chip">❤️ ${escapeHtml(tag)}</span>`).join(" ");
  const questTagsHtml = batch.questSynergies.map(tag => `<span class="d3-quest-badge" style="background:#f3e8ff; border:1px solid #d8b4fe; color:#6b21a8;">📜 ${escapeHtml(tag)}</span>`).join(" ");

  const stepsTimelineHtml = batch.steps.map((st, idx) =>
    renderCraftStepRowHtml(st, `Step ${idx + 1}`)
  ).join("");

  return `
    <div class="almanac-batch-card ${isBatchDone ? "is-checked" : ""}" data-batch-index="${bIdx}" data-batch-key="${escapeHtml(batch.batchKey)}">
      <div class="batch-card-header">
        <div class="batch-target-info">
          <label class="craft-check-label batch-check-label" title="${isBatchDone ? "Uncheck entire batch" : "Mark entire batch as crafted"}">
            <input type="checkbox" class="craft-checkbox" ${isBatchDone ? "checked" : ""} onchange="toggleCraftBatchCheck('${escapeHtml(batch.batchKey)}')">
          </label>
          <img class="batch-product-sprite" src="${targetSprite}" alt="${escapeHtml(target.item_name)}" onerror="this.src='/static/icons/ui/icon_gift.png'">
          <span class="batch-target-name">${escapeHtml(target.item_name)}</span>
        </div>
        <div class="batch-header-badges">
          ${stationBadgesHtml}
          ${unlockBadge}
          ${giftTagsHtml}
          ${questTagsHtml}
        </div>
      </div>
      <div class="batch-steps-timeline">
        ${stepsTimelineHtml}
      </div>
    </div>
  `;
}

function renderReadyToCraftQueue(queueSteps, viewMode = "chains") {
  readyToCraftState.viewMode = viewMode;
  const container = document.getElementById("almanacBatchQueueContainer");
  const countBadge = document.getElementById("readyToCraftBadge") || document.getElementById("readyToCraftCountBadge");
  const filterBar = document.getElementById("readyToCraftStationFilters");
  const paginationRow = document.getElementById("readyToCraftPaginationRow");
  const btnShowNext5 = document.getElementById("btnShowNext5Crafts");
  const btnCollapse = document.getElementById("btnCollapseCrafts");
  const btnToggleCompleted = document.getElementById("btnToggleCompletedCrafts");
  const btnResetChecks = document.getElementById("btnResetCraftChecks");
  if (!container) return;

  if (!queueSteps || queueSteps.length === 0) {
    if (countBadge) countBadge.textContent = "0 Batches";
    if (filterBar) {
      filterBar.innerHTML = "";
      filterBar.style.display = "none";
    }
    if (paginationRow) paginationRow.style.display = "none";
    if (btnToggleCompleted) btnToggleCompleted.style.display = "none";
    if (btnResetChecks) btnResetChecks.style.display = "none";
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 28px 16px; color: var(--ink-muted); font-style: italic;">
        No items currently ready to craft. Check Raw Material Blockers below to see what ingredients to gather!
      </div>
    `;
    return;
  }

  const batches = groupBatchQueue(queueSteps);
  renderReadyToCraftStationFilters(queueSteps, batches, viewMode);

  const activeBatchesAll = batches.filter(b => !isCraftBatchCompleted(b));
  const completedBatchesAll = batches.filter(b => isCraftBatchCompleted(b));
  const activeStepsAll = queueSteps.filter(s => !isCraftStepChecked(s));
  const completedStepsAll = queueSteps.filter(s => isCraftStepChecked(s));

  const remainingUnlocks = queueSteps.filter(s => s.unlocks_almanac && !isCraftStepChecked(s)).length;
  if (countBadge) {
    if (completedBatchesAll.length > 0) {
      countBadge.textContent = `${activeBatchesAll.length} / ${batches.length} Batches (${remainingUnlocks} Unlocks)`;
    } else {
      countBadge.textContent = `${batches.length} Batches (${remainingUnlocks} Unlocks)`;
    }
  }

  const totalCheckedSteps = readyToCraftState.checkedStepKeys.size;
  const completedCount = viewMode === "steps" ? completedStepsAll.length : completedBatchesAll.length;
  if (totalCheckedSteps === 0) {
    readyToCraftState.showCompleted = false;
  }

  if (btnResetChecks) {
    if (totalCheckedSteps > 0) {
      btnResetChecks.style.display = "inline-flex";
      btnResetChecks.textContent = `↺ Reset (${totalCheckedSteps})`;
    } else {
      btnResetChecks.style.display = "none";
    }
  }

  if (btnToggleCompleted) {
    if (completedCount > 0 || (readyToCraftState.showCompleted && totalCheckedSteps > 0)) {
      btnToggleCompleted.style.display = "inline-flex";
      btnToggleCompleted.classList.toggle("active", readyToCraftState.showCompleted);
      btnToggleCompleted.textContent = `${readyToCraftState.showCompleted ? "Hide" : "Show"} Completed (${completedCount})`;
    } else {
      btnToggleCompleted.style.display = "none";
    }
  }

  const stFilter = readyToCraftState.stationFilter || "all";

  if (viewMode === "steps") {
    const filteredActiveSteps = activeStepsAll.filter(s => stFilter === "all" || (s.station || "cooking") === stFilter);
    const filteredCompletedSteps = completedStepsAll.filter(s => stFilter === "all" || (s.station || "cooking") === stFilter);
    const visibleActiveSteps = filteredActiveSteps.slice(0, readyToCraftState.visibleLimit);
    const remainingActiveCount = Math.max(0, filteredActiveSteps.length - visibleActiveSteps.length);

    if (paginationRow) {
      if (filteredActiveSteps.length > 5) {
        paginationRow.style.display = "flex";
        if (btnShowNext5) {
          if (remainingActiveCount > 0) {
            btnShowNext5.style.display = "inline-flex";
            btnShowNext5.innerHTML = `<span>Show Next 5 (${remainingActiveCount} remaining) ▼</span>`;
          } else {
            btnShowNext5.style.display = "none";
          }
        }
        if (btnCollapse) {
          btnCollapse.style.display = readyToCraftState.visibleLimit > 5 ? "inline-flex" : "none";
        }
      } else {
        paginationRow.style.display = "none";
      }
    }

    let html = "";
    if (visibleActiveSteps.length === 0) {
      html += `
        <div class="almanac-craft-all-done-banner">
          <span>✨ All crafting steps in this station filter are checked off!</span>
          ${filteredCompletedSteps.length > 0 && !readyToCraftState.showCompleted
            ? `<button type="button" class="action-btn" onclick="toggleShowCompletedCrafts()">Show Completed (${filteredCompletedSteps.length})</button>`
            : ``}
        </div>
      `;
    } else {
      html += visibleActiveSteps.map(step => renderCraftStepRowHtml(step, `Step ${step.step_number}`)).join("");
    }

    if (readyToCraftState.showCompleted && filteredCompletedSteps.length > 0) {
      html += `
        <div class="almanac-completed-crafts-group">
          <div class="completed-crafts-divider">
            <span>✓ Completed Steps (${filteredCompletedSteps.length})</span>
          </div>
          <div class="completed-crafts-list">
            ${filteredCompletedSteps.map(step => renderCraftStepRowHtml(step, `Step ${step.step_number}`)).join("")}
          </div>
        </div>
      `;
    }

    container.innerHTML = html;
    return;
  }

  const filteredActiveBatches = activeBatchesAll.filter(b =>
    stFilter === "all" || b.steps.some(s => !isCraftStepChecked(s) && (s.station || "cooking") === stFilter)
  );
  const filteredCompletedBatches = completedBatchesAll.filter(b =>
    stFilter === "all" || b.steps.some(s => (s.station || "cooking") === stFilter)
  );
  const visibleActiveBatches = filteredActiveBatches.slice(0, readyToCraftState.visibleLimit);
  const remainingActiveCount = Math.max(0, filteredActiveBatches.length - visibleActiveBatches.length);

  if (paginationRow) {
    if (filteredActiveBatches.length > 5) {
      paginationRow.style.display = "flex";
      if (btnShowNext5) {
        if (remainingActiveCount > 0) {
          btnShowNext5.style.display = "inline-flex";
          btnShowNext5.innerHTML = `<span>Show Next 5 (${remainingActiveCount} remaining) ▼</span>`;
        } else {
          btnShowNext5.style.display = "none";
        }
      }
      if (btnCollapse) {
        btnCollapse.style.display = readyToCraftState.visibleLimit > 5 ? "inline-flex" : "none";
      }
    } else {
      paginationRow.style.display = "none";
    }
  }

  let html = "";
  if (visibleActiveBatches.length === 0) {
    html += `
      <div class="almanac-craft-all-done-banner">
        <span>✨ All crafting batches in this station filter are checked off!</span>
        ${filteredCompletedBatches.length > 0 && !readyToCraftState.showCompleted
          ? `<button type="button" class="action-btn" onclick="toggleShowCompletedCrafts()">Show Completed (${filteredCompletedBatches.length})</button>`
          : ``}
      </div>
    `;
  } else {
    html += visibleActiveBatches.map((batch, bIdx) => renderCraftBatchCardHtml(batch, bIdx)).join("");
  }

  if (readyToCraftState.showCompleted && filteredCompletedBatches.length > 0) {
    html += `
      <div class="almanac-completed-crafts-group">
        <div class="completed-crafts-divider">
          <span>✓ Completed Batches (${filteredCompletedBatches.length})</span>
        </div>
        <div class="completed-crafts-list">
          ${filteredCompletedBatches.map((batch, bIdx) => renderCraftBatchCardHtml(batch, bIdx)).join("")}
        </div>
      </div>
    `;
  }

  container.innerHTML = html;
}

function copyCraftingListToClipboard() {
  const queueSteps = currentPlan?.almanac?.ready_to_craft || [];
  if (queueSteps.length === 0) {
    showToast("No ready-to-craft items to copy.");
    return;
  }
  const batches = groupBatchQueue(queueSteps);
  const stFilter = readyToCraftState.stationFilter || "all";
  const activeBatches = batches.filter(b =>
    !isCraftBatchCompleted(b) &&
    (stFilter === "all" || b.steps.some(s => !isCraftStepChecked(s) && (s.station || "cooking") === stFilter))
  );
  if (activeBatches.length === 0) {
    showToast("All items in this view are already checked off!");
    return;
  }
  const lines = ["=== Fields of Mistria: Ready to Craft Checklist ==="];
  activeBatches.forEach((b, idx) => {
    lines.push(`\nBatch ${idx + 1}: ${b.target.item_name} (${b.stations.join(", ")})`);
    b.steps.filter(s => !isCraftStepChecked(s)).forEach(s => {
      const ings = (s.ingredients || []).map(i => `${i.count}x ${i.display_name || i.item_id}`).join(", ");
      lines.push(`  [ ] Step ${s.step_number}: ${s.station} -> ${s.quantity || 1}x ${s.item_name} (using ${ings})`);
    });
  });
  const text = lines.join("\n");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      showToast("Crafting checklist copied to clipboard!");
    }).catch(() => {
      showToast("Could not copy checklist.");
    });
  } else {
    showToast("Clipboard not supported.");
  }
}

const ALMANAC_BLOCKER_CATEGORY_META = {
  crops: { label: "Crops", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_crops.png" },
  forageables: { label: "Forageables", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_forageables.png" },
  materials: { label: "Materials", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_materials.png" },
  ranching: { label: "Ranching", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_ranching.png" },
  fish: { label: "Fish", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_fish.png" },
  bugs: { label: "Bugs", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_bugs.png" },
  artifacts: { label: "Artifacts", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_artifacts.png" },
  cooked_dishes: { label: "Cooked Dishes", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_cooked_dishes.png" },
  blacksmithing: { label: "Blacksmithing", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_blacksmithing.png" },
  furniture: { label: "Furniture", icon: "/static/icons/ui/spr_ui_journal_almanac_icon_furniture.png" },
};

function normalizeBlockerCategoryKey(rawCat) {
  const slug = String(rawCat || "Materials")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (slug === "forage") return "forageables";
  return slug || "materials";
}

function getBlockerItemKey(b) {
  return String(b?.item_id || b?.item_name || "");
}

function isAlmanacBlockerChecked(b) {
  const k = getBlockerItemKey(b);
  return Boolean(k && almanacBlockersState.checkedItemIds.has(k));
}

function matchesBlockerSearch(b, query) {
  if (!query) return true;
  const hay = [
    b.item_name || "",
    b.item_id || "",
    b.category || "",
    ...(b.unblocked_almanac_items || []).map(u => `${u.name || ""} ${u.category || ""}`)
  ].join(" ").toLowerCase();
  return hay.includes(query);
}

function setAlmanacBlockerCategoryFilter(catKey) {
  almanacBlockersState.categoryFilter = catKey || "all";
  almanacBlockersState.visibleLimit = 5;
  if (currentPlan?.almanac?.raw_material_blockers) {
    renderRawMaterialBlockers(currentPlan.almanac.raw_material_blockers);
  }
}

function toggleAlmanacBlockerCheck(itemKey) {
  if (!itemKey) return;
  if (almanacBlockersState.checkedItemIds.has(itemKey)) {
    almanacBlockersState.checkedItemIds.delete(itemKey);
  } else {
    almanacBlockersState.checkedItemIds.add(itemKey);
  }
  if (currentPlan?.almanac?.raw_material_blockers) {
    renderRawMaterialBlockers(currentPlan.almanac.raw_material_blockers);
  }
}

function toggleShowCompletedBlockers() {
  almanacBlockersState.showCompleted = !almanacBlockersState.showCompleted;
  if (currentPlan?.almanac?.raw_material_blockers) {
    renderRawMaterialBlockers(currentPlan.almanac.raw_material_blockers);
  }
}

function showNext5AlmanacBlockers() {
  almanacBlockersState.visibleLimit += 5;
  if (currentPlan?.almanac?.raw_material_blockers) {
    renderRawMaterialBlockers(currentPlan.almanac.raw_material_blockers);
  }
}

function collapseAlmanacBlockers() {
  almanacBlockersState.visibleLimit = 5;
  if (currentPlan?.almanac?.raw_material_blockers) {
    renderRawMaterialBlockers(currentPlan.almanac.raw_material_blockers);
  }
}

function renderBlockerCardHtml(b, idx) {
  const sprite = resolveAlmanacItemSpriteUrl(b);
  const bKey = getBlockerItemKey(b);
  const isChecked = isAlmanacBlockerChecked(b);
  const treeKey = `almanac_blocker_${b.item_id}_${idx}`;
  if (b.tree) {
    window._almanacTreeData[treeKey] = b.tree;
  }

  const unblocked = b.unblocked_almanac_items || [];
  const previewChips = unblocked.slice(0, 6).map(u => `
    <span class="unblocked-item-chip" title="${escapeHtml(u.name)} (${escapeHtml(u.category)})">
      <img class="mini-sprite" src="${resolveAlmanacItemSpriteUrl(u)}" alt="" onerror="this.style.display='none'">
      ${escapeHtml(u.name)}
    </span>
  `).join("");

  const moreChip = unblocked.length > 6
    ? `<span class="unblocked-more-chip">+${unblocked.length - 6} more</span>`
    : ``;

  const treeBtn = b.tree && b.tree.children && b.tree.children.length > 0
    ? `
      <button type="button" class="almanac-tree-btn" onclick="openCraftingTreeModal(window._almanacTreeData['${treeKey}'], ${b.combined_deficit})">
        <img class="inline-icon" src="/static/icons/ui/icon_tree.png" alt="Tree"> View Crafting Tree (${unblocked.length})
      </button>
    `
    : ``;

  const giftNote = b.gift_deficit > 0 ? `<span class="metric-pill">🎁 Gift Deficit: <strong>${b.gift_deficit}</strong></span>` : ``;
  const questNote = b.quest_demand > 0 ? `<span class="metric-pill">📜 Quest Need: <strong>${b.quest_demand}</strong></span>` : ``;

  return `
    <div class="almanac-blocker-card ${isChecked ? "is-checked" : ""}" data-item-id="${escapeHtml(b.item_id)}">
      <div class="blocker-top-row">
        <div class="blocker-item-lead">
          <label class="craft-check-label blocker-check-label" title="${isChecked ? "Uncheck material" : "Mark material as gathered"}">
            <input type="checkbox" class="craft-checkbox" ${isChecked ? "checked" : ""} onchange="toggleAlmanacBlockerCheck('${escapeHtml(bKey)}')">
          </label>
          <img class="blocker-sprite" src="${sprite}" alt="${escapeHtml(b.item_name)}" onerror="this.src='/static/icons/ui/icon_gift.png'">
          <div class="blocker-name-cat">
            <span class="blocker-item-name">${escapeHtml(b.item_name)}</span>
            <span class="blocker-category-pill">${escapeHtml(b.category || "Materials")}</span>
          </div>
        </div>
        <div class="blocker-deficit-badge">
          <span class="deficit-badge-label">Deficit</span>
          <span class="deficit-badge-value">-${(b.combined_deficit || 0).toLocaleString()}</span>
        </div>
      </div>

      <div class="blocker-metrics-bar">
        <span class="metric-pill">Inventory: <strong>${(b.inventory || 0).toLocaleString()}</strong></span>
        <span class="metric-pill">Almanac Need: <strong>${(b.almanac_deficit || 0).toLocaleString()}</strong></span>
        ${giftNote}
        ${questNote}
      </div>

      <div class="blocker-unblocked-section">
        <div class="unblocked-header">
          <span>Unblocks ${unblocked.length} Almanac Item${unblocked.length === 1 ? '' : 's'}</span>
        </div>
        <div class="unblocked-chips-wrap">
          ${previewChips}
          ${moreChip}
        </div>
      </div>

      <div class="blocker-action-row">
        ${treeBtn}
      </div>
    </div>
  `;
}

function renderRawMaterialBlockers(blockers) {
  const container = document.getElementById("almanacBlockersContainer");
  const countBadge = document.getElementById("almanacBlockersBadge") || document.getElementById("almanacBlockersCountBadge");
  const filterBar = document.getElementById("almanacBlockerCategoryFilters");
  const paginationRow = document.getElementById("almanacBlockersPaginationRow");
  const btnShowNext5 = document.getElementById("btnShowNext5Blockers");
  const btnCollapse = document.getElementById("btnCollapseBlockers");
  const btnToggleCompleted = document.getElementById("btnToggleCompletedBlockers");
  const btnResetChecks = document.getElementById("btnResetBlockerChecks");
  if (!container) return;

  if (!blockers || blockers.length === 0) {
    if (countBadge) countBadge.textContent = "0 Blockers";
    if (filterBar) {
      filterBar.innerHTML = "";
      filterBar.style.display = "none";
    }
    if (paginationRow) paginationRow.style.display = "none";
    if (btnToggleCompleted) btnToggleCompleted.style.display = "none";
    if (btnResetChecks) btnResetChecks.style.display = "none";
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 28px 16px; color: var(--ink-muted); font-style: italic;">
        No raw material blockers found! You have all base materials needed for unobtained craftable items.
      </div>
    `;
    return;
  }

  window._almanacTreeData = window._almanacTreeData || {};

  const presentCatMap = new Map();
  blockers.forEach(b => {
    const key = normalizeBlockerCategoryKey(b.category);
    if (!presentCatMap.has(key)) {
      const meta = ALMANAC_BLOCKER_CATEGORY_META[key] || {
        label: b.category || "Materials",
        icon: "/static/icons/ui/icon_gift.png"
      };
      presentCatMap.set(key, meta);
    }
  });

  if (almanacBlockersState.categoryFilter !== "all" && !presentCatMap.has(almanacBlockersState.categoryFilter)) {
    almanacBlockersState.categoryFilter = "all";
  }

  const activeBlockersAll = blockers.filter(b => !isAlmanacBlockerChecked(b));
  const completedBlockersAll = blockers.filter(b => isAlmanacBlockerChecked(b));

  if (countBadge) {
    if (completedBlockersAll.length > 0) {
      countBadge.textContent = `${activeBlockersAll.length} / ${blockers.length} Missing Materials`;
    } else {
      countBadge.textContent = `${blockers.length} Missing Materials`;
    }
  }

  const totalChecked = completedBlockersAll.length;
  if (totalChecked === 0) {
    almanacBlockersState.showCompleted = false;
  }

  if (btnResetChecks) {
    if (totalChecked > 0) {
      btnResetChecks.style.display = "inline-flex";
      btnResetChecks.textContent = `↺ Reset (${totalChecked})`;
    } else {
      btnResetChecks.style.display = "none";
    }
  }

  if (btnToggleCompleted) {
    if (totalChecked > 0) {
      btnToggleCompleted.style.display = "inline-flex";
      btnToggleCompleted.classList.toggle("active", almanacBlockersState.showCompleted);
      btnToggleCompleted.textContent = `${almanacBlockersState.showCompleted ? "Hide" : "Show"} Completed (${totalChecked})`;
    } else {
      btnToggleCompleted.style.display = "none";
    }
  }

  const searchMatchesActive = activeBlockersAll.filter(b => matchesBlockerSearch(b, currentAlmanacBlockerSearchQuery));

  if (filterBar) {
    const canonicalOrder = Object.keys(ALMANAC_BLOCKER_CATEGORY_META).filter(k => presentCatMap.has(k));
    const extraKeys = [...presentCatMap.keys()].filter(k => !ALMANAC_BLOCKER_CATEGORY_META[k]);
    const orderedKeys = [...canonicalOrder, ...extraKeys];

    const pills = [
      `<button type="button" class="craft-station-pill ${almanacBlockersState.categoryFilter === "all" ? "active" : ""}" data-category="all" onclick="setAlmanacBlockerCategoryFilter('all')">
        <span>All</span>
        <span class="craft-station-count">${searchMatchesActive.length}</span>
      </button>`
    ];

    orderedKeys.forEach(catKey => {
      const meta = presentCatMap.get(catKey);
      const count = searchMatchesActive.filter(b => normalizeBlockerCategoryKey(b.category) === catKey).length;
      const isActive = almanacBlockersState.categoryFilter === catKey;
      pills.push(`
        <button type="button" class="craft-station-pill ${isActive ? "active" : ""}" data-category="${escapeHtml(catKey)}" onclick="setAlmanacBlockerCategoryFilter('${escapeHtml(catKey)}')">
          <img class="mini-station-icon" src="${meta.icon}" alt="" onerror="this.style.display='none'">
          <span>${escapeHtml(meta.label)}</span>
          <span class="craft-station-count">${count}</span>
        </button>
      `);
    });

    filterBar.style.display = "flex";
    filterBar.innerHTML = pills.join("");
  }

  const catFilter = almanacBlockersState.categoryFilter || "all";
  const filteredActive = searchMatchesActive.filter(b =>
    catFilter === "all" || normalizeBlockerCategoryKey(b.category) === catFilter
  );
  const filteredCompleted = completedBlockersAll.filter(b =>
    matchesBlockerSearch(b, currentAlmanacBlockerSearchQuery) &&
    (catFilter === "all" || normalizeBlockerCategoryKey(b.category) === catFilter)
  );

  const visibleActive = filteredActive.slice(0, almanacBlockersState.visibleLimit);
  const remainingCount = Math.max(0, filteredActive.length - visibleActive.length);

  if (paginationRow) {
    if (filteredActive.length > 5) {
      paginationRow.style.display = "flex";
      if (btnShowNext5) {
        if (remainingCount > 0) {
          btnShowNext5.style.display = "inline-flex";
          btnShowNext5.innerHTML = `<span>Show Next 5 (${remainingCount} remaining) ▼</span>`;
        } else {
          btnShowNext5.style.display = "none";
        }
      }
      if (btnCollapse) {
        btnCollapse.style.display = almanacBlockersState.visibleLimit > 5 ? "inline-flex" : "none";
      }
    } else {
      paginationRow.style.display = "none";
    }
  }

  let html = "";
  if (visibleActive.length === 0) {
    html += `
      <div class="almanac-craft-all-done-banner">
        <span>${filteredCompleted.length > 0 ? "✨ All raw material blockers in this view are checked off!" : "No raw material blockers match the current filter."}</span>
        ${filteredCompleted.length > 0 && !almanacBlockersState.showCompleted
          ? `<button type="button" class="action-btn" onclick="toggleShowCompletedBlockers()">Show Completed (${filteredCompleted.length})</button>`
          : ``}
      </div>
    `;
  } else {
    html += visibleActive.map((b, idx) => renderBlockerCardHtml(b, idx)).join("");
  }

  if (almanacBlockersState.showCompleted && filteredCompleted.length > 0) {
    html += `
      <div class="almanac-completed-crafts-group">
        <div class="completed-crafts-divider">
          <span>✓ Completed Materials (${filteredCompleted.length})</span>
        </div>
        <div class="almanac-blockers-grid">
          ${filteredCompleted.map((b, idx) => renderBlockerCardHtml(b, idx + 1000)).join("")}
        </div>
      </div>
    `;
  }

  container.innerHTML = html;
}

function getAlmanacSourceKey(src) {
  return `${src?.tier || "quick"}::${src?.source || ""}`;
}

function isAlmanacSourceChecked(src) {
  return almanacSourcesState.checkedSourceKeys.has(getAlmanacSourceKey(src));
}

function toggleAlmanacSourceCheck(srcKey) {
  if (!srcKey) return;
  if (almanacSourcesState.checkedSourceKeys.has(srcKey)) {
    almanacSourcesState.checkedSourceKeys.delete(srcKey);
  } else {
    almanacSourcesState.checkedSourceKeys.add(srcKey);
  }
  if (currentPlan?.almanac?.sources_by_tier) {
    renderSourcePriority(currentPlan.almanac.sources_by_tier, currentAlmanacTier);
  }
}

function toggleShowCompletedSources() {
  almanacSourcesState.showCompleted = !almanacSourcesState.showCompleted;
  if (currentPlan?.almanac?.sources_by_tier) {
    renderSourcePriority(currentPlan.almanac.sources_by_tier, currentAlmanacTier);
  }
}

function showNext5AlmanacSources() {
  almanacSourcesState.visibleLimit += 5;
  if (currentPlan?.almanac?.sources_by_tier) {
    renderSourcePriority(currentPlan.almanac.sources_by_tier, currentAlmanacTier);
  }
}

function collapseAlmanacSources() {
  almanacSourcesState.visibleLimit = 5;
  if (currentPlan?.almanac?.sources_by_tier) {
    renderSourcePriority(currentPlan.almanac.sources_by_tier, currentAlmanacTier);
  }
}

function renderSourceCardHtml(src) {
  const tierIcon = `/static/icons/ui/tier_${src.tier}.png`;
  const tierLabel = src.tier.charAt(0).toUpperCase() + src.tier.slice(1);
  const srcKey = getAlmanacSourceKey(src);
  const isChecked = isAlmanacSourceChecked(src);

  const directChips = (src.direct_collectibles || []).slice(0, 10).map(d => `
    <span class="unblocked-item-chip">
      <img class="mini-sprite" src="${resolveAlmanacItemSpriteUrl(d)}" alt="" onerror="this.style.display='none'">
      ${escapeHtml(d.name)}
    </span>
  `).join("");

  const rawChips = (src.raw_materials || []).slice(0, 8).map(r => `
    <span class="unblocked-item-chip" style="border-color:#fca5a5; background:#fff5f5;">
      <img class="mini-sprite" src="${resolveAlmanacItemSpriteUrl(r)}" alt="" onerror="this.style.display='none'">
      ${escapeHtml(r.name)} <strong style="color:#dc2626;">(-${(r.deficit || 0).toLocaleString()})</strong>
    </span>
  `).join("");

  const unblockedChips = (src.unblocked_craftables || []).slice(0, 8).map(u => `
    <span class="unblocked-item-chip" style="border-color:#fde68a; background:#fefce8;">
      <img class="mini-sprite" src="${resolveAlmanacItemSpriteUrl(u)}" alt="" onerror="this.style.display='none'">
      ${escapeHtml(u.name)}
    </span>
  `).join("");

  return `
    <div class="almanac-source-card ${isChecked ? "is-checked" : ""}" data-tier="${escapeHtml(src.tier)}" data-source-key="${escapeHtml(srcKey)}">
      <div class="source-card-header">
        <div class="source-name-wrap">
          <label class="craft-check-label source-check-label" title="${isChecked ? "Uncheck source" : "Mark source as visited/completed"}">
            <input type="checkbox" class="craft-checkbox" ${isChecked ? "checked" : ""} onchange="toggleAlmanacSourceCheck('${escapeHtml(srcKey)}')">
          </label>
          <span class="station-badge station-${src.tier}">
            <img class="station-icon" src="${tierIcon}" alt="${tierLabel}"> ${tierLabel}
          </span>
          <span class="source-name">${escapeHtml(src.source)}</span>
        </div>
        <span class="source-impact-badge" title="Total unobtained items you can get or unblock here">
          ★ Impact: +${src.total_impact || 0}
        </span>
      </div>

      <div class="source-metrics-summary">
        <span class="source-metric-pill">Direct Finds: <strong>${(src.direct_collectibles || []).length}</strong></span>
        <span class="source-metric-pill">Raw Materials: <strong>${(src.raw_materials || []).length}</strong></span>
        <span class="source-metric-pill">Unblocked Recipes: <strong>${(src.unblocked_craftables || []).length}</strong></span>
      </div>

      <div class="source-items-accordion">
        ${src.direct_collectibles && src.direct_collectibles.length > 0 ? `
          <span class="source-sub-label">Direct Gatherables:</span>
          <div class="source-chips-cloud">${directChips}</div>
        ` : ''}

        ${src.raw_materials && src.raw_materials.length > 0 ? `
          <span class="source-sub-label" style="margin-top:4px;">Shortage Materials Found Here:</span>
          <div class="source-chips-cloud">${rawChips}</div>
        ` : ''}

        ${src.unblocked_craftables && src.unblocked_craftables.length > 0 ? `
          <span class="source-sub-label" style="margin-top:4px;">Unblocks Almanac Recipes:</span>
          <div class="source-chips-cloud">${unblockedChips}</div>
        ` : ''}
      </div>
    </div>
  `;
}

function renderSourcePriority(sourcesByTier, activeTier = "all") {
  const container = document.getElementById("almanacSourcesContainer");
  const countBadge = document.getElementById("almanacSourcesBadge") || document.getElementById("almanacSourcesCountBadge");
  const paginationRow = document.getElementById("almanacSourcesPaginationRow");
  const btnShowNext5 = document.getElementById("btnShowNext5Sources");
  const btnCollapse = document.getElementById("btnCollapseSources");
  const btnToggleCompleted = document.getElementById("btnToggleCompletedSources");
  const btnResetChecks = document.getElementById("btnResetSourceChecks");
  if (!container) return;

  if (!sourcesByTier) {
    if (countBadge) countBadge.textContent = "0 Sources";
    if (paginationRow) paginationRow.style.display = "none";
    if (btnToggleCompleted) btnToggleCompleted.style.display = "none";
    if (btnResetChecks) btnResetChecks.style.display = "none";
    container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 24px;">No sources available.</div>`;
    return;
  }

  const allSources = [
    ...(sourcesByTier.quick || []),
    ...(sourcesByTier.grind || []),
    ...(sourcesByTier.farm || [])
  ];

  // Update tier tab counts dynamically
  const tierTabs = document.querySelectorAll("#almanacTierTabs .tier-tab-btn");
  tierTabs.forEach(btn => {
    const t = btn.dataset.tier || "all";
    const pool = t === "all" ? allSources : (sourcesByTier[t] || []);
    const activeCount = pool.filter(s => !isAlmanacSourceChecked(s)).length;
    if (t === "all") {
      btn.textContent = `All Sources (${activeCount})`;
    } else {
      const label = t.charAt(0).toUpperCase() + t.slice(1);
      btn.innerHTML = `<img class="inline-icon" src="/static/icons/ui/tier_${t}.png" alt="${label}"> ${label} (${activeCount})`;
    }
  });

  const list = activeTier === "all" ? allSources : (sourcesByTier[activeTier] || []);
  const activeList = list.filter(s => !isAlmanacSourceChecked(s));
  const completedList = list.filter(s => isAlmanacSourceChecked(s));
  const totalCheckedAll = allSources.filter(s => isAlmanacSourceChecked(s)).length;

  if (totalCheckedAll === 0) {
    almanacSourcesState.showCompleted = false;
  }

  if (countBadge) {
    if (completedList.length > 0) {
      countBadge.textContent = `${activeList.length} / ${list.length} Source${list.length === 1 ? '' : 's'}`;
    } else {
      countBadge.textContent = `${list.length} Source${list.length === 1 ? '' : 's'}`;
    }
  }

  if (btnResetChecks) {
    if (totalCheckedAll > 0) {
      btnResetChecks.style.display = "inline-flex";
      btnResetChecks.textContent = `↺ Reset (${totalCheckedAll})`;
    } else {
      btnResetChecks.style.display = "none";
    }
  }

  if (btnToggleCompleted) {
    if (completedList.length > 0 || (almanacSourcesState.showCompleted && totalCheckedAll > 0)) {
      btnToggleCompleted.style.display = "inline-flex";
      btnToggleCompleted.classList.toggle("active", almanacSourcesState.showCompleted);
      btnToggleCompleted.textContent = `${almanacSourcesState.showCompleted ? "Hide" : "Show"} Completed (${completedList.length})`;
    } else {
      btnToggleCompleted.style.display = "none";
    }
  }

  if (list.length === 0) {
    if (paginationRow) paginationRow.style.display = "none";
    container.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 28px 16px; color: var(--ink-muted); font-style: italic;">
        No acquisition sources match this filter for the selected season.
      </div>
    `;
    return;
  }

  const visibleActive = activeList.slice(0, almanacSourcesState.visibleLimit);
  const remainingCount = Math.max(0, activeList.length - visibleActive.length);

  if (paginationRow) {
    if (activeList.length > 5) {
      paginationRow.style.display = "flex";
      if (btnShowNext5) {
        if (remainingCount > 0) {
          btnShowNext5.style.display = "inline-flex";
          btnShowNext5.innerHTML = `<span>Show Next 5 (${remainingCount} remaining) ▼</span>`;
        } else {
          btnShowNext5.style.display = "none";
        }
      }
      if (btnCollapse) {
        btnCollapse.style.display = almanacSourcesState.visibleLimit > 5 ? "inline-flex" : "none";
      }
    } else {
      paginationRow.style.display = "none";
    }
  }

  let html = "";
  if (visibleActive.length === 0) {
    html += `
      <div class="almanac-craft-all-done-banner">
        <span>✨ All acquisition sources in this tier are checked off!</span>
        ${completedList.length > 0 && !almanacSourcesState.showCompleted
          ? `<button type="button" class="action-btn" onclick="toggleShowCompletedSources()">Show Completed (${completedList.length})</button>`
          : ``}
      </div>
    `;
  } else {
    html += visibleActive.map(src => renderSourceCardHtml(src)).join("");
  }

  if (almanacSourcesState.showCompleted && completedList.length > 0) {
    html += `
      <div class="almanac-completed-crafts-group">
        <div class="completed-crafts-divider">
          <span>✓ Completed Sources (${completedList.length})</span>
        </div>
        <div class="almanac-sources-grid">
          ${completedList.map(src => renderSourceCardHtml(src)).join("")}
        </div>
      </div>
    `;
  }

  container.innerHTML = html;
}

let _almanacEventsInitialized = false;
function initAlmanacEventListeners() {
  if (_almanacEventsInitialized) return;
  _almanacEventsInitialized = true;

  const closeBtn = document.getElementById("closeAlmanacDrawerBtn");
  const closeBottomBtn = document.getElementById("closeAlmanacDrawerBottomBtn");
  const backdrop = document.getElementById("almanacDrawerBackdrop");
  const searchInput = document.getElementById("almanacSearchInput");
  const searchClearBtn = document.getElementById("almanacSearchClearBtn");

  if (closeBtn) closeBtn.onclick = closeAlmanacDrawer;
  if (closeBottomBtn) closeBottomBtn.onclick = closeAlmanacDrawer;
  if (backdrop) {
    backdrop.onclick = (e) => {
      if (e.target === backdrop) closeAlmanacDrawer();
    };
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && backdrop) {
      const isOpen = (backdrop.style && backdrop.style.display !== "none") &&
                     (backdrop.classList && typeof backdrop.classList.contains === "function" ? backdrop.classList.contains("active") : true);
      if (isOpen) {
        closeAlmanacDrawer();
      }
    }
  });

  const statusPills = document.querySelectorAll("#almanacStatusFilters .pill-btn");
  statusPills.forEach(btn => {
    btn.onclick = () => {
      currentAlmanacStatusFilter = btn.dataset.filter || "all";
      updateFilterPillStates();
      renderDrawerItems();
    };
  });

  const seasonPills = document.querySelectorAll("#almanacSeasonFilters .pill-btn");
  seasonPills.forEach(btn => {
    btn.onclick = () => {
      currentAlmanacSeasonFilter = btn.dataset.season || "all";
      updateFilterPillStates();
      renderDrawerItems();
    };
  });

  if (searchInput) {
    searchInput.oninput = () => {
      currentAlmanacSearchQuery = searchInput.value.trim().toLowerCase();
      if (searchClearBtn) {
        searchClearBtn.style.display = currentAlmanacSearchQuery ? "inline-flex" : "none";
      }
      renderDrawerItems();
    };
  }
  if (searchClearBtn) {
    searchClearBtn.onclick = () => {
      if (searchInput) searchInput.value = "";
      currentAlmanacSearchQuery = "";
      searchClearBtn.style.display = "none";
      renderDrawerItems();
    };
  }

  const btnChains = document.getElementById("btnBatchViewChains");
  const btnSteps = document.getElementById("btnBatchViewSteps");
  if (btnChains) {
    btnChains.onclick = () => {
      almanacBatchViewMode = "chains";
      btnChains.classList.add("active");
      if (btnSteps) btnSteps.classList.remove("active");
      if (currentPlan?.almanac?.ready_to_craft) {
        renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, "chains");
      }
    };
  }
  if (btnSteps) {
    btnSteps.onclick = () => {
      almanacBatchViewMode = "steps";
      btnSteps.classList.add("active");
      if (btnChains) btnChains.classList.remove("active");
      if (currentPlan?.almanac?.ready_to_craft) {
        renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, "steps");
      }
    };
  }

  const btnToggleCompleted = document.getElementById("btnToggleCompletedCrafts");
  if (btnToggleCompleted) {
    btnToggleCompleted.onclick = toggleShowCompletedCrafts;
  }

  const btnResetChecks = document.getElementById("btnResetCraftChecks");
  if (btnResetChecks) {
    btnResetChecks.onclick = () => {
      readyToCraftState.checkedStepKeys.clear();
      readyToCraftState.showCompleted = false;
      if (currentPlan?.almanac?.ready_to_craft) {
        renderReadyToCraftQueue(currentPlan.almanac.ready_to_craft, almanacBatchViewMode);
      }
      showToast("Reset all temporary crafting checks.");
    };
  }

  const btnShowNext5 = document.getElementById("btnShowNext5Crafts");
  if (btnShowNext5) {
    btnShowNext5.onclick = showNext5ReadyToCraft;
  }

  const btnCollapse = document.getElementById("btnCollapseCrafts");
  if (btnCollapse) {
    btnCollapse.onclick = collapseReadyToCraft;
  }

  const copyBtn = document.getElementById("btnCopyCraftList");
  if (copyBtn) {
    copyBtn.onclick = copyCraftingListToClipboard;
  }

  const blockerSearch = document.getElementById("almanacBlockerSearch");
  if (blockerSearch) {
    blockerSearch.oninput = () => {
      currentAlmanacBlockerSearchQuery = blockerSearch.value.trim().toLowerCase();
      almanacBlockersState.visibleLimit = 5;
      if (currentPlan?.almanac?.raw_material_blockers) {
        renderRawMaterialBlockers(currentPlan.almanac.raw_material_blockers);
      }
    };
  }

  const btnToggleCompletedBlockers = document.getElementById("btnToggleCompletedBlockers");
  if (btnToggleCompletedBlockers) {
    btnToggleCompletedBlockers.onclick = toggleShowCompletedBlockers;
  }

  const btnResetBlockerChecks = document.getElementById("btnResetBlockerChecks");
  if (btnResetBlockerChecks) {
    btnResetBlockerChecks.onclick = () => {
      almanacBlockersState.checkedItemIds.clear();
      almanacBlockersState.showCompleted = false;
      if (currentPlan?.almanac?.raw_material_blockers) {
        renderRawMaterialBlockers(currentPlan.almanac.raw_material_blockers);
      }
      showToast("Reset all temporary material blocker checks.");
    };
  }

  const btnShowNext5Blockers = document.getElementById("btnShowNext5Blockers");
  if (btnShowNext5Blockers) {
    btnShowNext5Blockers.onclick = showNext5AlmanacBlockers;
  }

  const btnCollapseBlockers = document.getElementById("btnCollapseBlockers");
  if (btnCollapseBlockers) {
    btnCollapseBlockers.onclick = collapseAlmanacBlockers;
  }

  const btnToggleCompletedSources = document.getElementById("btnToggleCompletedSources");
  if (btnToggleCompletedSources) {
    btnToggleCompletedSources.onclick = toggleShowCompletedSources;
  }

  const btnResetSourceChecks = document.getElementById("btnResetSourceChecks");
  if (btnResetSourceChecks) {
    btnResetSourceChecks.onclick = () => {
      almanacSourcesState.checkedSourceKeys.clear();
      almanacSourcesState.showCompleted = false;
      if (currentPlan?.almanac?.sources_by_tier) {
        renderSourcePriority(currentPlan.almanac.sources_by_tier, currentAlmanacTier);
      }
      showToast("Reset all temporary source checks.");
    };
  }

  const btnShowNext5Sources = document.getElementById("btnShowNext5Sources");
  if (btnShowNext5Sources) {
    btnShowNext5Sources.onclick = showNext5AlmanacSources;
  }

  const btnCollapseSources = document.getElementById("btnCollapseSources");
  if (btnCollapseSources) {
    btnCollapseSources.onclick = collapseAlmanacSources;
  }

  const tierTabs = document.querySelectorAll("#almanacTierTabs .tier-tab-btn");
  tierTabs.forEach(btn => {
    btn.onclick = () => {
      tierTabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentAlmanacTier = btn.dataset.tier || "all";
      almanacSourcesState.visibleLimit = 5;
      if (currentPlan?.almanac?.sources_by_tier) {
        renderSourcePriority(currentPlan.almanac.sources_by_tier, currentAlmanacTier);
      }
    };
  });
}

// Global window bindings for inline HTML onclick handlers
window.switchPlannerMode = switchPlannerMode;
window.setPlannerMode = switchPlannerMode;
window.updateSidebarForPlannerMode = updateSidebarForPlannerMode;
window.openAlmanacDrawer = openAlmanacDrawer;
window.closeAlmanacDrawer = closeAlmanacDrawer;
window.selectFurnitureSwatch = selectFurnitureSwatch;
window.renderAlmanacPlanner = renderAlmanacPlanner;
window.resetReadyToCraftChecks = resetReadyToCraftChecks;
window.setReadyToCraftStationFilter = setReadyToCraftStationFilter;
window.toggleCraftBatchCheck = toggleCraftBatchCheck;
window.toggleCraftStepCheck = toggleCraftStepCheck;
window.toggleShowCompletedCrafts = toggleShowCompletedCrafts;
window.showNext5ReadyToCraft = showNext5ReadyToCraft;
window.collapseReadyToCraft = collapseReadyToCraft;
window.setAlmanacBlockerCategoryFilter = setAlmanacBlockerCategoryFilter;
window.toggleAlmanacBlockerCheck = toggleAlmanacBlockerCheck;
window.toggleShowCompletedBlockers = toggleShowCompletedBlockers;
window.showNext5AlmanacBlockers = showNext5AlmanacBlockers;
window.collapseAlmanacBlockers = collapseAlmanacBlockers;
window.toggleAlmanacSourceCheck = toggleAlmanacSourceCheck;
window.toggleShowCompletedSources = toggleShowCompletedSources;
window.showNext5AlmanacSources = showNext5AlmanacSources;
window.collapseAlmanacSources = collapseAlmanacSources;



