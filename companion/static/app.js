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
    playerFarmBadge.textContent = `🌾 ${pName} @ ${fName}`;
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
  if (completedSub) completedSub.textContent = (completedCount === totalNpcs && totalNpcs > 0) ? "🎉 All NPCs 100% completed!" : "100% gift journal complete";
  if (drawerCompletedCount) drawerCompletedCount.textContent = completedCount;

  // 3. Incomplete NPCs
  if (incompleteVal) incompleteVal.textContent = `${incompleteCount} / ${totalNpcs}`;
  if (incompleteSub) incompleteSub.textContent = incompleteCount === 0 ? "All NPC gifts discovered!" : `${incompleteCount} NPCs pending loved/liked gifts`;
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
    container.innerHTML = `<div class="empty-state-notice">No NPCs have 100% completed gift journals yet. Keep gifting!</div>`;
    return;
  }

  container.innerHTML = list.map(npc => `
    <div class="completed-npc-chip">
      <img class="completed-npc-avatar" src="${npc.portrait_url}" alt="${npc.name}" onerror="this.src='/assets/sprites/npcs/fallback'" />
      <div class="completed-npc-info">
        <span class="completed-npc-name" title="${npc.name}">${npc.name}</span>
        <span class="completed-npc-badge">✓ 100% Complete</span>
      </div>
    </div>
  `).join("");
}

function renderIncompleteDrawerContent(list) {
  const container = document.getElementById("incompleteGrid");
  if (!container) return;

  if (!list || list.length === 0) {
    container.innerHTML = `<div class="empty-state-notice">🎉 All NPCs have their gift journals 100% completed!</div>`;
    return;
  }

  const query = (incompleteSearchFilter || "").trim().toLowerCase();
  const filtered = query
    ? list.filter(npc => (npc.name && npc.name.toLowerCase().includes(query)) || (npc.npc_id && npc.npc_id.toLowerCase().includes(query)))
    : list;

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state-notice">No incomplete NPCs found matching "${incompleteSearchFilter}".</div>`;
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
            <span class="gift-type-label loved">💖 Remaining Loved (${(npc.remaining_loved || []).length})</span>
            <div class="gift-chips-container">
              ${lovedChips || '<span style="font-size: 0.72rem; color: var(--text-light); font-style: italic;">All loved gifts discovered!</span>'}
            </div>
          </div>
          <div class="gift-type-row" style="margin-top: 4px;">
            <span class="gift-type-label liked">💜 Remaining Liked (${(npc.remaining_liked || []).length})</span>
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
    container.innerHTML = `<div class="empty-state-notice">🎉 All cooking recipes have been obtained!</div>`;
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
          ${r.impact > 0 ? `<span class="recipe-impact-badge" title="Unlocks gift preferences for ${r.impact} NPC(s)">🎁 Unlocks ${r.impact} NPC${r.impact === 1 ? '' : 's'}</span>` : ''}
        </div>
        <div class="recipe-source-row">
          <span>📍</span>
          <span class="recipe-source-badge" title="How to obtain: ${r.unlock_source}">${r.unlock_source || 'Unknown'}</span>
        </div>
      </div>
    </div>
  `).join("");
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

function renderBlockedNpcs(blockedNpcs) {
  if (!blockedNpcs || !Array.isArray(blockedNpcs)) {
    return 'Various NPCs';
  }

  const validNpcs = blockedNpcs
    .map(name => (typeof name === 'string' ? name : (name ? String(name) : '')).trim())
    .filter(name => name.length > 0);

  if (validNpcs.length === 0) {
    return 'Various NPCs';
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
      <button type="button" class="npc-toggle-btn npc-expand-btn" onclick="toggleBlockedNpcs(this, true)" title="Show ${extraCount} more NPCs">and +${extraCount} more</button>
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
  shop: "🛒",
  inn: "🍽️",
  market_stall: "🛒",
  chicken_statue: "🐔",
  mimic: "⛏️",
  mill: "⚙️",
  fishing: "🎣",
  wishing_well: "💫",
  festival: "🎪",
  date: "💕",
  quest: "📋",
  museum: "🏛️",
  living_off_the_land: "🌱",
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
    if (data.is_group) return 56;

    let h = 44; // base header
    if (isRoot && deficit) h += 24; // deficit badge

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
      const isGroup = !!data.is_group;
      const isGift = !isGroup && data.gift_npcs && data.gift_npcs.length > 0;
      const hasChildren = (d.children && d.children.length > 0) || (d._children && d._children.length > 0);
      const isIntermediate = !isRoot && !isGroup && hasChildren;

      let cardClass = 'd3-tree-node';
      if (isRoot) cardClass += ' is-root';
      else if (isGroup) cardClass += ' is-group';
      else if (isIntermediate) cardClass += ' is-intermediate';
      else if (isGift) cardClass += ' is-gift';

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

      // Header row: sprite + title
      let headerHtml = `<div class="d3-node-header">`;
      if (isGroup) {
        headerHtml += `<span style="font-size:1.1rem; line-height:1;">🍽️</span>`;
      } else {
        headerHtml += `<img class="d3-node-sprite" src="${data.sprite_url || '/assets/sprites/items/' + data.item_id}" alt="${data.item_name}" onerror="this.style.display='none'" />`;
      }
      headerHtml += `<span class="d3-node-name" title="${data.item_name}">${data.item_name}</span>`;
      headerHtml += `</div>`;
      let bodyHtml = headerHtml;

      // Deficit badge on root
      if (isRoot && deficit) {
        bodyHtml += `<span class="d3-node-deficit">Need: ${deficit}</span>`;
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
          const emoji = ALT_SOURCE_EMOJI[s.type] || '📍';

          bodyHtml += `<span class="d3-node-alt-badge" title="${fullTitle}">
            <img class="source-icon" src="${iconUrl}" onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='inline';" alt="${s.type}" />
            <span class="source-emoji-fallback" style="display:none;">${emoji} </span>
            <span class="badge-text">${label}${cost}</span>
          </span>`;
        });
        bodyHtml += `</div>`;
      }

      // NPC recipient chips
      if (data.gift_npcs && data.gift_npcs.length > 0) {
        bodyHtml += `<div class="d3-node-npcs">`;
        data.gift_npcs.forEach(npc => {
          bodyHtml += `<span class="d3-node-npc-chip">→ ${npc}</span>`;
        });
        bodyHtml += `</div>`;
      }

      // Collapse / Expand toggle button pill
      if (hasChildren && !isRoot) {
        const childCount = (d.children ? d.children.length : (d._children ? d._children.length : 0));
        const isCollapsed = !!d._children;
        const toggleIcon = isCollapsed ? '▶' : '▼';
        const toggleText = isCollapsed ? `${toggleIcon} ${childCount} products` : `${toggleIcon} Collapse`;
        bodyHtml += `<div class="d3-node-toggle ${isCollapsed ? 'is-collapsed' : ''}">${toggleText}</div>`;
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
        const toggleText = isCollapsed ? `${toggleIcon} ${childCount} products` : `${toggleIcon} Collapse`;

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

    // If node has intermediate items (with children) AND direct leaves (children: [])
    const intermediates = node.children.filter(c => (c.children && c.children.length > 0) || (c._children && c._children.length > 0));
    const leaves = node.children.filter(c => (!c.children || c.children.length === 0) && (!c._children || c._children.length === 0));

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
      node.children = [...intermediates, groupNode];
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

      // Auto-expand any collapsed ancestors of matching nodes
      function expandMatches(n) {
        const name = (n.data.item_name || '').toLowerCase();
        const npcs = (n.data.gift_npcs || []).join(' ').toLowerCase();
        const alts = (n.data.alt_sources || []).map(s => s.vendor || s.location || s.type).join(' ').toLowerCase();
        const isSelfMatch = name.includes(term) || npcs.includes(term) || alts.includes(term);

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
        const name = (d.data.item_name || '').toLowerCase();
        const npcs = (d.data.gift_npcs || []).join(' ').toLowerCase();
        const alts = (d.data.alt_sources || []).map(s => s.vendor || s.location || s.type).join(' ').toLowerCase();
        const isMatch = name.includes(term) || npcs.includes(term) || alts.includes(term);

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
          <span class="source-item-pairs" title="${item.blocked_pairs} blocked NPC-gift combinations">(${item.blocked_pairs} pairs)</span>
        </div>
      `).join("");

      const npcsHtml = renderBlockedNpcs(s.benefited_npcs || []);

      return `
        <div class="source-card">
          <div class="source-card-header">
            <div class="source-card-title">
              <span class="source-icon">📍</span>
              <strong>${s.source_name}</strong>
            </div>
            <div class="source-card-badges">
              <span class="tier-badge-pill tier-pill-${tierKey}">${tierKey.toUpperCase()}</span>
              <span class="source-score-badge" title="Total blocked NPC gifts unlocked">Score: ${s.total_score || 0}</span>
            </div>
          </div>

          <div class="source-items-section">
            <div class="source-label">Blocker Items (${(s.items || []).length}):</div>
            <div class="source-items-chips">${itemsHtml}</div>
          </div>

          <div class="source-benefited-section">
            <div class="source-label">Benefited NPCs:</div>
            <div class="source-npcs-chips">${npcsHtml}</div>
          </div>
        </div>
      `;
    }).join("");

    return `
      <details class="source-tier-accordion tier-${tierKey}" open>
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
        <span class="source-summary-icon">📍</span>
        <h3>Acquisition Source Priority</h3>
      </div>
      <span class="source-summary-subtitle">Ranked by blocked NPC gift impact</span>
    </div>
    <div class="source-tiers-wrapper">
      ${renderTier("quick", "Quick Acquisition", "⚡", "— Instant / Purchasable (Shops, Mill, Forge, Cook)", quickSources)}
      ${renderTier("grind", "Grind Acquisition", "⛏️", "— Repeatable / Exploration (Mines, Fishing, Foraging)", grindSources)}
      ${renderTier("farm", "Farm & Ranch", "🌱", "— Seasonal / Planning (Crops, Animals, Feed)", farmSources)}
    </div>
  `;
}
window.renderSourceSummary = renderSourceSummary;

function renderFocusSuggestions(focusItems, focusTrees = [], sourcePriority = null) {
  const grid = document.getElementById("focusGrid");
  const badge = document.getElementById("focusCountBadge");

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

    let treeHtml = "";
    if (tree) {
      const treeKey = `tree_${fId}_${idx}`;
      window._craftingTreeData[treeKey] = tree;
      treeHtml = `
        <div class="tree-section">
          <button type="button" class="tree-toggle" onclick="openCraftingTreeModal(window._craftingTreeData['${treeKey}'], ${f.deficit || 0})">🌳 View crafting tree</button>
        </div>
      `;
    }

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
    const fieldsHtml = (group.fields || []).map(f => renderField(f, config[f.key], config)).join("");

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

  // Select All & Deselect All Buttons
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

  let optionsHtml = `<option value="__auto__" ${isAuto ? "selected" : ""}>★ Auto-Detect (Latest save)</option>`;

  if (data.saves && data.saves.length > 0) {
    optionsHtml += `<optgroup label="Discovered Game Saves (${data.saves.length})">`;
    data.saves.forEach(s => {
      const isSelected = (!isAuto && currentPath === s.path) ? "selected" : "";
      const label = s.modified ? `${s.filename} (${s.modified})` : s.filename;
      optionsHtml += `<option value="${s.path}" ${isSelected}>${label}</option>`;
    });
    optionsHtml += `</optgroup>`;
  }

  optionsHtml += `<option value="__browse__">📁 Browse & Import .sav File...</option>`;
  select.innerHTML = optionsHtml;
}

async function uploadSaveFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".sav")) {
    showToast("⚠️ Invalid file! Please select a Fields of Mistria .sav file.");
    return;
  }

  showToast(`⏳ Importing "${file.name}"...`, 4000);

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
    }
    if (resData.plan) {
      renderPlan(resData.plan);
    }
    await loadAvailableSaves();
    showToast(`🎮 Save "${resData.filename || file.name}" imported successfully!`);
  } catch (err) {
    console.error("Save upload error:", err);
    showToast(`❌ Import error: ${err.message}`);
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

function renderField(field, currentVal, config = {}) {
  const id = `setting_${field.key}`;

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

  if (field.key === "date_override" || field.type === "date_override") {
    const isOverridden = Boolean(currentPlan?.in_game_date?.is_overridden);
    const dateInfo = currentPlan?.in_game_date || {};
    const saveDate = dateInfo.save_date;
    const targetDateStr = `${dateInfo.season || "Spring"} Day ${dateInfo.day || 1}, Year ${dateInfo.year || 1}`;
    const overrideVal = (currentVal !== null && currentVal !== undefined) ? currentVal : "";

    return `
      <div class="field-group">
        <label>${field.label}</label>
        <div class="date-override-card">
          <div class="date-override-status-row">
            <div class="date-override-badge-active">
              <span>📅</span>
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
              📅 Open Calendar
            </button>
            ${isOverridden ? `
              <button type="button" class="btn-cal-action btn-cal-reset" id="sidebarResetDateBtn" title="Reset date override and follow game save">
                ↺ Reset
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
    if (resData.config) {
      currentSettings = resData.config;
    }
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
  if (isSat) desc += " ★ (Saturday Market)";
  if (fest) desc += ` 🎉 (${fest})`;
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
            ${isSat ? '<span class="cal-cell-sat-tag">★ Sat</span>' : ''}
            ${isSaveDate ? '<span class="cal-cell-save-tag">🎮 Save</span>' : ''}
          </div>
        </div>
        <div class="cal-cell-content">
          ${festName ? `<span class="cal-cell-fest-tag" title="${festName}">🎉 ${festName}</span>` : ''}
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
    showToast("↺ Reverting to game save date...", 2000);
    await submitSettingUpdate("date_override", "");
    await loadSettings();
  } else if (isDirty) {
    const capSeason = selSeason.charAt(0).toUpperCase() + selSeason.slice(1);
    const formatted = `${capSeason} ${selDay}, Year ${selYear}`;
    showToast(`📅 Applying date override: ${formatted}...`, 2000);
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
  showToast("↺ Reverting to game save date...", 2000);
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
        await submitSettingUpdate("save_file", null);
        await loadAvailableSaves();
        showToast("Switched to auto-detecting newest game save");
      } else if (val) {
        await submitSettingUpdate("save_file", val);
        await loadAvailableSaves();
        const name = val.split(/[/\\]/).pop();
        showToast(`Switched active save to "${name}"`);
      }
    });
  }

  const quickResetBtn = document.getElementById("quickResetBtn");
  if (quickResetBtn) {
    quickResetBtn.addEventListener("click", async () => {
      await submitSettingUpdate("save_file", null);
      await loadAvailableSaves();
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
  });
});

