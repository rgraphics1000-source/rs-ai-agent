/* =========================================================
   RS AI - Full Platform Interactive Logic (JavaScript)
   ========================================================= */

let currentWorkspaceId = parseInt(localStorage.getItem("current_workspace_id") || "1");
let allWorkspaces = [];

document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    loadWorkspacesList();
    loadOverview();
    loadOrders();
    loadProducts();
    loadTrainingRules();
    loadSavedMediaList();
    loadFaqs();
    loadCommentLogs();
    loadAllSettings();
    loadOmnichatConversations();
    loadGoogleFormsTab();
    initSmartphoneSimulator();
    initModals();
    initPWA();
});

function initPWA() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js')
            .then(() => console.log("[PWA] Service worker registered"))
            .catch(err => console.log("[PWA] SW register error:", err));
    }
}

// ==========================================
// WORKSPACE / BUSINESS MULTI-TENANCY LOGIC
// ==========================================
async function loadWorkspacesList() {
    try {
        const res = await fetch("/api/workspaces");
        const data = await res.json();
        if (data.success && data.workspaces) {
            allWorkspaces = data.workspaces;
            const valid = allWorkspaces.some(w => w.id === currentWorkspaceId);
            if (!valid) {
                currentWorkspaceId = allWorkspaces[0] ? allWorkspaces[0].id : 1;
                localStorage.setItem("current_workspace_id", currentWorkspaceId);
                refreshAllWorkspaceData();
            }
            renderWorkspaceDropdown();
        }
    } catch (e) {
        console.error("Load workspaces error:", e);
    }
}

function renderWorkspaceDropdown() {
    const selects = [
        document.getElementById("global-workspace-select"),
        document.getElementById("mobile-workspace-select")
    ];
    selects.forEach(sel => {
        if (!sel) return;
        sel.innerHTML = "";
        allWorkspaces.forEach(ws => {
            const opt = document.createElement("option");
            opt.value = ws.id;
            opt.textContent = `${ws.id === 1 ? '🏢 ' : '🏪 '}${ws.name}`;
            if (ws.id === currentWorkspaceId) opt.selected = true;
            sel.appendChild(opt);
        });
    });
}

function refreshAllWorkspaceData() {
    loadOverview();
    loadOrders();
    loadProducts();
    loadTrainingRules();
    loadSavedMediaList();
    loadFaqs();
    loadCommentLogs();
    loadAllSettings();
    loadOmnichatConversations();
    loadConnectedPages();
    loadGoogleFormsTab();
}

function onWorkspaceChanged(wsId) {
    currentWorkspaceId = parseInt(wsId) || 1;
    localStorage.setItem("current_workspace_id", currentWorkspaceId);
    showToast(`Switched to Business Workspace #${currentWorkspaceId}`, "success");
    refreshAllWorkspaceData();
}

function openCreateWorkspaceModal() {
    openModal("modal-create-workspace");
}

async function handleCreateWorkspace(e) {
    e.preventDefault();
    const name = document.getElementById("new-ws-name").value.trim();
    const shop_name = document.getElementById("new-ws-shop-name").value.trim();
    const phone = document.getElementById("new-ws-phone").value.trim();
    const address = document.getElementById("new-ws-address").value.trim();
    const delDhaka = parseFloat(document.getElementById("new-ws-del-dhaka").value) || 70;
    const delOut = parseFloat(document.getElementById("new-ws-del-out").value) || 130;

    if (!name) {
        showToast("Please enter workspace name", "warning");
        return;
    }

    try {
        const res = await fetch("/api/workspaces", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: name,
                shop_name: shop_name || name,
                shop_phone: phone,
                shop_address: address,
                delivery_inside_dhaka: delDhaka,
                delivery_outside_dhaka: delOut,
                ai_enabled: 1
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Workspace '${name}' created successfully!`, "success");
            closeModal("modal-create-workspace");
            document.getElementById("form-create-workspace").reset();
            await loadWorkspacesList();
            onWorkspaceChanged(data.id);
        } else {
            showToast(data.error || "Failed to create workspace", "danger");
        }
    } catch (err) {
        showToast("Network error creating workspace", "danger");
    }
}

// ==========================================
// 1. NAVIGATION & TAB SWITCHING (DESKTOP & MOBILE)
// ==========================================
function toggleMobileSidebar() {
    const sidebar = document.getElementById("app-sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (!sidebar) return;

    sidebar.classList.toggle("mobile-open");
    if (backdrop) backdrop.classList.toggle("active");
}

function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const mobileNavLinks = document.querySelectorAll(".mobile-nav-link[data-tab]");
    const tabPanes = document.querySelectorAll(".tab-pane");
    const pageTitle = document.getElementById("page-title");
    const pageSubtitle = document.getElementById("page-subtitle");

    const titles = {
        "test-arena": { title: "⚡ AI Setup & Live Simulator", sub: "Configure your sales assistant and test customer conversations live" },
        "dashboard": { title: "📊 Dashboard Overview", sub: "Monitor total conversations, orders, conversion rate and sales" },
        "orders": { title: "📦 Orders Management", sub: "Track, manage and update customer orders across channels" },
        "products": { title: "🏷️ Products & Inventory", sub: "Manage product catalog, prices, stocks and variations" },
        "content": { title: "📚 Train Content & FAQs", sub: "Train your AI with custom Q&A pairs, knowledge base and auto-replies" },
        "omnichat": { title: "💬 Omnichat Inbox", sub: "Multi-channel unified customer conversation inbox" },
        "analytics": { title: "📈 Analytics & Performance", sub: "Key performance metrics, response times and sales trends" },
        "adsflow": { title: "📢 AdsFlow Campaigns", sub: "Automatic lead qualification from Facebook click-to-Messenger ads" },
        "google-forms": { title: "📑 Google Forms & ID Card Automation", sub: "মাস্টার ফর্ম ক্লোন করে যেকোনো প্রতিষ্ঠানের জন্য অটোমেটিক আইডি কার্ড ফর্ম তৈরি ও রেসপন্স সংগ্রহ" },
        "integrations": { title: "🔗 Channels & Integrations", sub: "Connect Facebook Page Messenger, Comments, and WhatsApp Cloud API" },
        "settings": { title: "⚙️ Store & AI Settings", sub: "Configure business details, delivery fees, and AI engine" },
        "support": { title: "📞 Help & Support", sub: "Platform documentation, contact info and FAQs" }
    };

    function switchTab(target) {
        if (!target) return;

        localStorage.setItem("rs_active_tab", target);
        try {
            const url = new URL(window.location.href);
            url.searchParams.set("tab", target);
            window.history.replaceState({}, "", url.toString());
        } catch (e) {}

        navItems.forEach(n => {
            if (n.getAttribute("data-tab") === target) n.classList.add("active");
            else n.classList.remove("active");
        });

        mobileNavLinks.forEach(m => {
            if (m.getAttribute("data-tab") === target) m.classList.add("active");
            else m.classList.remove("active");
        });

        tabPanes.forEach(p => p.classList.remove("active"));
        const activePane = document.getElementById(`tab-${target}`);
        if (activePane) activePane.classList.add("active");

        if (titles[target] && pageTitle && pageSubtitle) {
            pageTitle.innerText = titles[target].title;
            pageSubtitle.innerText = titles[target].sub;
        }

        if (target === "google-forms") {
            loadGoogleFormsTab();
        }

        // Close mobile drawer if open
        const sidebar = document.getElementById("app-sidebar");
        const backdrop = document.getElementById("sidebar-backdrop");
        if (sidebar && sidebar.classList.contains("mobile-open")) {
            sidebar.classList.remove("mobile-open");
            if (backdrop) backdrop.classList.remove("active");
        }
    }

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const target = item.getAttribute("data-tab");
            switchTab(target);
        });
    });

    mobileNavLinks.forEach(item => {
        item.addEventListener("click", () => {
            const target = item.getAttribute("data-tab");
            switchTab(target);
        });
    });

    // Auto-restore active tab on page reload / load
    try {
        const urlParams = new URLSearchParams(window.location.search);
        const tabParam = urlParams.get("tab");
        const hashParam = window.location.hash ? window.location.hash.replace("#", "") : null;
        const savedTab = localStorage.getItem("rs_active_tab");
        const initialTab = tabParam || hashParam || savedTab || "dashboard";
        switchTab(initialTab);
    } catch (e) {
        console.error("Tab restoration error:", e);
    }
}

function refreshCurrentTab(target) {
    if (!target) {
        const activeNav = document.querySelector(".nav-item.active");
        target = activeNav ? activeNav.getAttribute("data-tab") : "dashboard";
    }

    if (target === "dashboard") loadOverview();
    if (target === "orders") loadOrders();
    if (target === "products") loadProducts();
    if (target === "content") { loadTrainingRules(); loadSavedMediaList(); loadFaqs(); loadCommentLogs(); }
    if (target === "omnichat") { loadOmnichatConversations(); loadConnectedPages(); }
    if (target === "integrations") { loadConnectedPages(); loadSettings(); }
    if (target === "google-forms") loadGoogleFormsTab();
    if (target === "settings" || target === "test-arena") { loadSettings(); loadConnectedPages(); }
}

// ==========================================
// 2. OVERVIEW & DASHBOARD METRICS
// ==========================================
async function loadOverview() {
    try {
        const res = await fetch(`/api/overview?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();

        // Dashboard Stats
        const salesEl = document.getElementById("dash-stat-sales");
        const ordersEl = document.getElementById("dash-stat-orders");
        const convsEl = document.getElementById("dash-stat-convs");
        const rateEl = document.getElementById("dash-stat-conv-rate");

        if (salesEl) salesEl.innerText = `৳${data.total_revenue.toLocaleString()}`;
        if (ordersEl) ordersEl.innerText = data.total_orders;
        if (convsEl) convsEl.innerText = Math.max(1, data.total_orders + 1);
        if (rateEl) {
            const rate = data.total_orders > 0 ? "100%" : "0%";
            rateEl.innerText = rate;
        }

        // Recent Orders
        const tbody = document.getElementById("dash-recent-orders-tbody");
        if (tbody) {
            tbody.innerHTML = "";
            if (!data.recent_orders || data.recent_orders.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 25px;">No orders recorded yet. Orders placed via AI will appear here automatically.</td></tr>`;
                return;
            }

            data.recent_orders.forEach(o => {
                const tr = document.createElement("tr");
                tr.innerHTML = `
                    <td><strong>${o.order_code}</strong></td>
                    <td>${o.customer_name}</td>
                    <td>${o.customer_phone}</td>
                    <td><strong>৳${o.total_amount}</strong></td>
                    <td><span class="badge badge-${o.status.toLowerCase()}">${o.status}</span></td>
                    <td>${o.created_at ? o.created_at.split(" ")[0] : ""}</td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        console.error("Overview error:", e);
    }
}

// ==========================================
// 3. ORDER MANAGEMENT
// ==========================================
let currentOrderStatusFilter = "All";

async function loadOrders(searchQuery = "") {
    const tbody = document.getElementById("orders-tbody");
    if (!tbody) return;

    tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; padding: 20px;">Loading orders...</td></tr>`;

    try {
        let url = `/api/orders?status=${currentOrderStatusFilter}&workspace_id=${currentWorkspaceId}`;
        if (searchQuery) url += `&search=${encodeURIComponent(searchQuery)}`;

        const res = await fetch(url);
        const data = await res.json();


        tbody.innerHTML = "";
        if (!data.orders || data.orders.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-dim); padding: 35px;">No orders found.</td></tr>`;
            return;
        }

        data.orders.forEach(o => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${o.order_code}</strong><br><small style="color:var(--text-dim); text-transform: capitalize;">${o.channel}</small></td>
                <td><strong>${o.customer_name}</strong><br><small style="color:var(--text-muted);">${o.customer_phone}</small></td>
                <td style="max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${o.customer_address}">
                    ${o.customer_address}
                </td>
                <td style="max-width: 220px;">${o.items_summary}</td>
                <td><strong>৳${o.total_amount}</strong><br><small style="color:var(--text-dim);">(Del: ৳${o.delivery_charge})</small></td>
                <td>
                    <select class="form-select form-select-sm" style="padding: 4px 8px; font-size: 12px; width: 110px;" onchange="changeOrderStatus(${o.id}, this.value)">
                        <option value="Pending" ${o.status === 'Pending' ? 'selected' : ''}>Pending</option>
                        <option value="Confirmed" ${o.status === 'Confirmed' ? 'selected' : ''}>Confirmed</option>
                        <option value="Processing" ${o.status === 'Processing' ? 'selected' : ''}>Processing</option>
                        <option value="Shipped" ${o.status === 'Shipped' ? 'selected' : ''}>Shipped</option>
                        <option value="Delivered" ${o.status === 'Delivered' ? 'selected' : ''}>Delivered</option>
                        <option value="Cancelled" ${o.status === 'Cancelled' ? 'selected' : ''}>Cancelled</option>
                    </select>
                </td>
                <td>${o.created_at ? o.created_at.split(" ")[0] : ""}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn btn-secondary" style="padding: 4px 8px;" onclick='viewOrderDetails(${JSON.stringify(o)})' title="View Invoice">
                            <i class="fas fa-eye"></i>
                        </button>
                        <button class="btn btn-danger" style="padding: 4px 8px;" onclick="deleteOrder(${o.id})" title="Delete">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Load orders error:", e);
    }
}

function filterOrdersByStatus(status, btnElement) {
    currentOrderStatusFilter = status;
    document.querySelectorAll(".order-filter-btn").forEach(b => b.classList.remove("active", "btn-primary"));
    document.querySelectorAll(".order-filter-btn").forEach(b => b.classList.add("btn-secondary"));
    
    if (btnElement) {
        btnElement.classList.remove("btn-secondary");
        btnElement.classList.add("active", "btn-primary");
    }
    loadOrders();
}

async function changeOrderStatus(orderId, newStatus) {
    try {
        const res = await fetch(`/api/orders/${orderId}/status`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: newStatus })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Order status updated to: ${newStatus}`, "success");
            loadOverview();
        }
    } catch (e) {
        showToast("Failed to update status", "danger");
    }
}

async function deleteOrder(orderId) {
    if (!confirm("Are you sure you want to delete this order?")) return;
    try {
        const res = await fetch(`/api/orders/${orderId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("Order deleted successfully", "success");
            loadOrders();
            loadOverview();
        }
    } catch (e) {
        showToast("Could not delete order", "danger");
    }
}

function viewOrderDetails(o) {
    const modal = document.getElementById("modal-order-details");
    const content = document.getElementById("order-details-content");
    if (!modal || !content) return;

    content.innerHTML = `
        <div style="background: rgba(255,255,255,0.03); padding: 16px; border-radius: 8px; margin-bottom: 16px;">
            <div style="display:flex; justify-content:space-between; margin-bottom: 10px;">
                <h4>Order: <span style="color:var(--primary-light);">${o.order_code}</span></h4>
                <span class="badge badge-${o.status.toLowerCase()}">${o.status}</span>
            </div>
            <p><strong>Customer:</strong> ${o.customer_name}</p>
            <p><strong>Phone:</strong> <a href="tel:${o.customer_phone}" style="color:var(--primary-light); text-decoration:none;">${o.customer_phone}</a></p>
            <p><strong>Delivery Address:</strong> ${o.customer_address}</p>
            <p><strong>Channel:</strong> ${o.channel}</p>
            <p><strong>Date & Time:</strong> ${o.created_at}</p>
        </div>

        <h5 style="margin-bottom: 8px;">Line Items Summary:</h5>
        <div style="background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; margin-bottom: 16px;">
            ${o.items_summary}
        </div>

        <div style="background: var(--primary-soft); border: 1px solid var(--border-glow); padding: 14px; border-radius: 8px;">
            <div style="display:flex; justify-content:space-between; margin-bottom: 4px;">
                <span>Subtotal:</span> <strong>৳${o.subtotal}</strong>
            </div>
            <div style="display:flex; justify-content:space-between; margin-bottom: 4px;">
                <span>Delivery Fee:</span> <strong>৳${o.delivery_charge}</strong>
            </div>
            <hr style="border-color: rgba(255,255,255,0.1); margin: 8px 0;">
            <div style="display:flex; justify-content:space-between; font-size: 16px;">
                <span>Total Bill:</span> <strong style="color:#34d399;">৳${o.total_amount}</strong>
            </div>
        </div>

        <div style="margin-top: 20px; display:flex; justify-content: flex-end; gap: 10px;">
            <button class="btn btn-secondary" onclick="window.print()"><i class="fas fa-print"></i> Print Invoice</button>
            <button class="btn btn-primary" onclick="closeModal('modal-order-details')">Done</button>
        </div>
    `;
    openModal("modal-order-details");
}

async function handleManualOrder(e) {
    e.preventDefault();
    const form = document.getElementById("form-manual-order");
    const formData = new FormData(form);

    try {
        const res = await fetch("/api/orders", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("Order created successfully!", "success");
            form.reset();
            closeModal("modal-add-order");
            loadOrders();
            loadOverview();
        }
    } catch (e) {
        showToast("Failed to create order", "danger");
    }
}

// ==========================================
// 4. PRODUCT CATALOG (MULTI-IMAGE SUPPORT)
// ==========================================
let addProductSelectedFiles = [];
let editProductExistingImages = [];
let editProductNewFiles = [];

function previewAddProductImages(e) {
    const files = Array.from(e.target.files);
    addProductSelectedFiles = addProductSelectedFiles.concat(files);
    renderAddProductPreviews();
}

function renderAddProductPreviews() {
    const wrapper = document.getElementById("add-prod-preview-wrapper");
    const container = document.getElementById("add-prod-images-preview");
    if (!container || !wrapper) return;

    if (addProductSelectedFiles.length === 0) {
        wrapper.style.display = "none";
        container.innerHTML = "";
        return;
    }

    wrapper.style.display = "block";
    container.innerHTML = "";

    addProductSelectedFiles.forEach((file, idx) => {
        const item = document.createElement("div");
        item.style.position = "relative";
        item.style.width = "70px";
        item.style.height = "70px";
        item.style.borderRadius = "6px";
        item.style.overflow = "hidden";
        item.style.border = idx === 0 ? "2px solid #ea580c" : "1px solid var(--border-glass)";

        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "cover";

        const badge = document.createElement("span");
        if (idx === 0) {
            badge.innerText = "Cover";
            badge.style.position = "absolute";
            badge.style.bottom = "0";
            badge.style.left = "0";
            badge.style.right = "0";
            badge.style.background = "rgba(234, 88, 12, 0.85)";
            badge.style.fontSize = "9px";
            badge.style.textAlign = "center";
            badge.style.color = "#fff";
            badge.style.fontWeight = "bold";
        }

        const delBtn = document.createElement("button");
        delBtn.innerHTML = "&times;";
        delBtn.type = "button";
        delBtn.style.position = "absolute";
        delBtn.style.top = "2px";
        delBtn.style.right = "2px";
        delBtn.style.background = "rgba(239, 68, 68, 0.9)";
        delBtn.style.color = "#fff";
        delBtn.style.border = "none";
        delBtn.style.borderRadius = "50%";
        delBtn.style.width = "18px";
        delBtn.style.height = "18px";
        delBtn.style.cursor = "pointer";
        delBtn.style.fontSize = "12px";
        delBtn.style.lineHeight = "1";
        delBtn.onclick = () => {
            addProductSelectedFiles.splice(idx, 1);
            renderAddProductPreviews();
        };

        item.appendChild(img);
        if (idx === 0) item.appendChild(badge);
        item.appendChild(delBtn);
        container.appendChild(item);
    });
}

function previewEditProductImages(e) {
    const files = Array.from(e.target.files);
    editProductNewFiles = editProductNewFiles.concat(files);
    renderEditProductPreviews();
}

function renderEditProductPreviews() {
    const container = document.getElementById("edit-prod-images-preview");
    if (!container) return;
    container.innerHTML = "";

    // Render existing images with individual variation title & price
    editProductExistingImages.forEach((item, idx) => {
        const url = typeof item === 'object' ? item.url : item;
        const title = (typeof item === 'object' ? item.title : '') || `ছবি #${idx + 1}`;
        const price = (typeof item === 'object' ? item.price : '') || '';

        const card = document.createElement("div");
        card.style.cssText = "display: flex; gap: 10px; align-items: center; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 8px; margin-bottom: 8px; width: 100%;";

        const img = document.createElement("img");
        img.src = url;
        img.style.cssText = "width: 55px; height: 55px; object-fit: cover; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15);";

        const fields = document.createElement("div");
        fields.style.cssText = "flex: 1; display: grid; grid-template-columns: 1.5fr 1fr; gap: 8px;";

        const titleInput = document.createElement("input");
        titleInput.type = "text";
        titleInput.className = "form-control";
        titleInput.style.fontSize = "12px";
        titleInput.placeholder = "ভ্যারিয়েশন / প্যাকেজের নাম";
        titleInput.value = title;
        titleInput.oninput = (e) => {
            if (typeof editProductExistingImages[idx] !== 'object') {
                editProductExistingImages[idx] = { url: url, title: e.target.value, price: price };
            } else {
                editProductExistingImages[idx].title = e.target.value;
            }
        };

        const priceInput = document.createElement("input");
        priceInput.type = "number";
        priceInput.className = "form-control";
        priceInput.style.fontSize = "12px";
        priceInput.placeholder = "আলাদা দাম (৳)";
        priceInput.value = price;
        priceInput.oninput = (e) => {
            const val = parseFloat(e.target.value) || 0;
            if (typeof editProductExistingImages[idx] !== 'object') {
                editProductExistingImages[idx] = { url: url, title: title, price: val };
            } else {
                editProductExistingImages[idx].price = val;
            }
        };

        fields.appendChild(titleInput);
        fields.appendChild(priceInput);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "btn btn-danger";
        delBtn.style.cssText = "padding: 6px 10px; font-size: 11px; align-self: center;";
        delBtn.innerHTML = '<i class="fas fa-trash"></i>';
        delBtn.onclick = () => {
            editProductExistingImages.splice(idx, 1);
            renderEditProductPreviews();
        };

        card.appendChild(img);
        card.appendChild(fields);
        card.appendChild(delBtn);
        container.appendChild(card);
    });

    // Render newly selected files
    editProductNewFiles.forEach((file, idx) => {
        const item = document.createElement("div");
        item.style.cssText = "position: relative; width: 60px; height: 60px; border-radius: 6px; overflow: hidden; border: 1px dashed #34d399;";

        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.style.cssText = "width: 100%; height: 100%; object-fit: cover;";

        const delBtn = document.createElement("button");
        delBtn.innerHTML = "&times;";
        delBtn.type = "button";
        delBtn.style.cssText = "position: absolute; top: 2px; right: 2px; background: rgba(239, 68, 68, 0.9); color: #fff; border: none; border-radius: 50%; width: 18px; height: 18px; cursor: pointer; font-size: 12px; line-height: 1;";
        delBtn.onclick = () => {
            editProductNewFiles.splice(idx, 1);
            renderEditProductPreviews();
        };

        item.appendChild(img);
        item.appendChild(delBtn);
        container.appendChild(item);
    });
}

let cachedProductsList = [];

async function loadProducts() {
    const grid = document.getElementById("products-grid");
    if (!grid) return;

    try {
        const res = await fetch(`/api/products?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        let products = data.products || [];

        if (currentWorkspaceId === 1) {
            if (products.length > 0) {
                localStorage.setItem("rs_cached_products", JSON.stringify(products));
            } else {
                // Check if we have backup in localStorage to auto-restore for Workspace 1
                const savedLocal = localStorage.getItem("rs_cached_products");
                if (savedLocal) {
                    try {
                        const parsed = JSON.parse(savedLocal);
                        if (Array.isArray(parsed) && parsed.length > 0) {
                            await fetch("/api/products/batch-restore", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ products: parsed })
                            });
                            const refreshRes = await fetch(`/api/products?workspace_id=${currentWorkspaceId}`);
                            const refreshData = await refreshRes.json();
                            products = refreshData.products || parsed;
                        }
                    } catch (e) {
                        console.error("Auto-restore products error:", e);
                    }
                }
            }
        }

        cachedProductsList = products;
        grid.innerHTML = "";
        if (products.length === 0) {
            grid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-dim); padding: 40px;">No products added yet in this workspace. Click '+ Add New Product' above.</div>`;
            return;
        }

        products.forEach(p => {
            const card = document.createElement("div");
            card.className = "product-card";
            const gallery = (p.gallery_images && p.gallery_images.length > 0) ? p.gallery_images : (p.image_url ? [p.image_url] : ["/static/uploads/sample_panjabi.jpg"]);
            const rawCover = gallery[0];
            const coverImg = (typeof rawCover === 'object' && rawCover !== null) ? (rawCover.url || rawCover.link || '/static/uploads/sample_panjabi.jpg') : (rawCover || '/static/uploads/sample_panjabi.jpg');
            const priceHtml = p.discount_price 
                ? `<span>৳${p.discount_price}</span> <span class="product-old-price">৳${p.price}</span>` 
                : `<span>৳${p.price}</span>`;

            const photoBadge = gallery.length > 1 
                ? `<span style="position:absolute; top: 10px; right: 10px; background: rgba(10,13,20,0.85); color: #fff; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; cursor: pointer; border: 1px solid rgba(255,255,255,0.2);" onclick="openProductGallery(${p.id})"><i class="fas fa-images"></i> ${gallery.length} Photos</span>` 
                : '';

            card.innerHTML = `
                <div style="position: relative; cursor: pointer;" onclick="openProductGallery(${p.id})">
                    <img src="${coverImg}" alt="${p.name}" class="product-thumb" onerror="this.src='/static/uploads/sample_panjabi.jpg'">
                    ${photoBadge}
                </div>
                <div class="product-body">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span class="product-code">${p.code}</span>
                        <span class="badge ${p.stock > 0 ? 'badge-delivered' : 'badge-cancelled'}">${p.stock > 0 ? `Stock: ${p.stock}` : 'Out of stock'}</span>
                    </div>
                    <h4 class="product-name" style="cursor: pointer;" onclick="openProductGallery(${p.id})">${p.name}</h4>
                    <div class="product-price">${priceHtml}</div>
                    <p style="font-size: 12px; color: var(--text-muted); margin-top: 6px; flex: 1;">${p.description || ''}</p>
                    
                    ${gallery.length > 1 ? `
                    <div style="display:flex; gap: 4px; margin: 8px 0; overflow-x: auto;">
                        ${gallery.slice(0, 4).map(u => {
                            const uSrc = (typeof u === 'object' && u !== null) ? (u.url || u.link || '') : u;
                            return `<img src="${uSrc}" style="width: 32px; height: 32px; object-fit: cover; border-radius: 4px; border: 1px solid var(--border-glass);" onclick="openProductGallery(${p.id})">`;
                        }).join('')}
                        ${gallery.length > 4 ? `<span style="font-size: 10px; align-self: center; color: var(--text-muted);">+${gallery.length - 4}</span>` : ''}
                    </div>` : ''}

                    <div class="product-footer" style="display: flex; align-items: center; justify-content: space-between; gap: 4px; padding-top: 8px; margin-top: auto; border-top: 1px solid var(--border-color);">
                        <span style="font-size: 11px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 65px;" title="${p.category || ''}">${p.category || 'General'}</span>
                        <div style="display: flex; gap: 4px; flex-shrink: 0;">
                            <button class="btn btn-edit-prod" style="padding: 5px 9px; font-size: 11.5px; font-weight: 600; display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; border-radius: 6px; background: rgba(59, 130, 246, 0.2); color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.4); cursor: pointer;" onclick="openEditProductModal(${p.id})">
                                <i class="fas fa-pen-to-square"></i> <span>এডিট</span>
                            </button>
                            <button class="btn btn-del-prod" style="padding: 5px 8px; font-size: 11.5px; border-radius: 6px; background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.4); cursor: pointer; flex-shrink: 0;" onclick="deleteProduct(${p.id})" title="ডিলিট">
                                <i class="fas fa-trash-can"></i>
                            </button>
                        </div>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        });
    } catch (e) {
        console.error("Load products error:", e);
    }
}

async function handleAddProduct(e) {
    e.preventDefault();
    const form = document.getElementById("form-add-product");
    const formData = new FormData(form);

    // Remove single file image if present, and append all addProductSelectedFiles
    formData.delete("image");
    formData.delete("images");
    addProductSelectedFiles.forEach(file => {
        formData.append("images", file);
    });
    formData.append("workspace_id", currentWorkspaceId);

    try {
        const res = await fetch("/api/products", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("Product added with all photos!", "success");
            form.reset();
            addProductSelectedFiles = [];
            renderAddProductPreviews();
            closeModal("modal-add-product");
            loadProducts();
            loadOverview();
        }
    } catch (e) {

        showToast("Could not add product", "danger");
    }
}

function openEditProductModal(productId) {
    const p = cachedProductsList.find(item => item.id === productId);
    if (!p) return;

    document.getElementById("edit-prod-id").value = p.id;
    document.getElementById("edit-prod-name").value = p.name || "";
    document.getElementById("edit-prod-code").value = p.code || "";
    document.getElementById("edit-prod-category").value = p.category || "General";
    document.getElementById("edit-prod-price").value = p.price || "";
    document.getElementById("edit-prod-discount-price").value = p.discount_price || "";
    document.getElementById("edit-prod-stock").value = p.stock || "10";
    document.getElementById("edit-prod-description").value = p.description || "";

    const rawGallery = (p.gallery_images && p.gallery_images.length > 0) ? p.gallery_images : (p.image_url ? [p.image_url] : []);
    editProductExistingImages = rawGallery.map((item, idx) => {
        if (typeof item === 'object' && item !== null) {
            return {
                url: item.url || '',
                title: item.title || `ভ্যারিয়েশন #${idx + 1}`,
                price: item.price || p.discount_price || p.price
            };
        }
        return {
            url: item,
            title: `ছবি #${idx + 1}`,
            price: p.discount_price || p.price
        };
    });

    editProductNewFiles = [];
    renderEditProductPreviews();

    openModal("modal-edit-product");
}

async function handleEditProduct(e) {
    e.preventDefault();
    const productId = document.getElementById("edit-prod-id").value;
    const formData = new FormData();
    formData.append("name", document.getElementById("edit-prod-name").value);
    formData.append("code", document.getElementById("edit-prod-code").value);
    formData.append("category", document.getElementById("edit-prod-category").value);
    formData.append("price", document.getElementById("edit-prod-price").value);
    formData.append("discount_price", document.getElementById("edit-prod-discount-price").value);
    formData.append("stock", document.getElementById("edit-prod-stock").value);
    formData.append("description", document.getElementById("edit-prod-description").value);
    formData.append("existing_images", JSON.stringify(editProductExistingImages));

    editProductNewFiles.forEach(file => {
        formData.append("images", file);
    });

    try {
        const res = await fetch(`/api/products/${productId}/edit`, {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("Product updated successfully!", "success");
            closeModal("modal-edit-product");
            loadProducts();
        }
    } catch (e) {
        showToast("Update failed", "danger");
    }
}

function openProductGallery(productId) {
    const p = cachedProductsList.find(item => item.id === productId);
    if (!p) return;

    const rawGallery = (p.gallery_images && p.gallery_images.length > 0) ? p.gallery_images : (p.image_url ? [p.image_url] : ["/static/uploads/id_card/IMG-20241009-WA0005.jpg"]);
    
    // Normalize gallery items into objects
    const gallery = rawGallery.map((item, idx) => {
        if (typeof item === 'object' && item !== null) {
            return {
                url: item.url || '',
                title: item.title || `ভ্যারিয়েশন #${idx + 1}`,
                price: item.price || p.discount_price || p.price
            };
        }
        return {
            url: item,
            title: `ছবি #${idx + 1}`,
            price: p.discount_price || p.price
        };
    });

    const title = document.getElementById("gallery-modal-title");
    const body = document.getElementById("gallery-modal-body");
    if (!title || !body) return;

    title.innerHTML = `<i class="fas fa-images" style="color:var(--primary-light);"></i> ${p.name} (${gallery.length} Photos & Prices)`;

    const firstItem = gallery[0];

    body.innerHTML = `
        <div style="margin-bottom: 12px; position: relative;">
            <img id="gallery-main-view" src="${firstItem.url}" style="width: 100%; max-height: 360px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.5);">
            <div id="gallery-main-caption" style="position: absolute; bottom: 8px; left: 8px; right: 8px; background: rgba(10,13,20,0.85); backdrop-filter: blur(8px); padding: 8px 12px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1); display: flex; justify-content: space-between; align-items: center;">
                <span id="gallery-current-title" style="color: #fff; font-weight: 600; font-size: 13px;">${firstItem.title}</span>
                <span id="gallery-current-price" style="color: #34d399; font-weight: 700; font-size: 14px;">৳${firstItem.price}</span>
            </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 8px; max-height: 180px; overflow-y: auto; padding: 6px; background: rgba(0,0,0,0.2); border-radius: 8px;">
            ${gallery.map((g, idx) => `
                <div style="position: relative; cursor: pointer; border-radius: 6px; overflow: hidden; border: ${idx === 0 ? '2px solid #ea580c' : '1px solid var(--border-glass)'}; background: rgba(255,255,255,0.03);" onclick="document.getElementById('gallery-main-view').src='${g.url}'; document.getElementById('gallery-current-title').innerText='${g.title}'; document.getElementById('gallery-current-price').innerText='৳${g.price}'; this.parentElement.querySelectorAll('div').forEach(i => i.style.border='1px solid var(--border-glass)'); this.style.border='2px solid #ea580c';">
                    <img src="${g.url}" style="width: 100%; height: 70px; object-fit: cover;">
                    <div style="padding: 4px; font-size: 10px; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #cbd5e1;">${g.title}</div>
                    <div style="font-size: 11px; font-weight: 700; color: #34d399; text-align: center; padding-bottom: 2px;">৳${g.price}</div>
                </div>
            `).join('')}
        </div>
        <div style="margin-top: 12px; text-align: left; background: rgba(255,255,255,0.03); padding: 10px 12px; border-radius: 8px;">
            <p style="font-size: 12px; color: var(--text-muted); margin: 0;">${p.description || ''}</p>
        </div>
    `;

    openModal("modal-view-gallery");
}

async function deleteProduct(productId) {
    if (!confirm("Are you sure you want to delete this product?")) return;
    try {
        const res = await fetch(`/api/products/${productId}/delete`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("Product deleted successfully!", "success");
            loadProducts();
            loadOverview();
        }
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ==========================================
// 5. TRAIN CONTENT & FAQS
// ==========================================
function switchContentSubtab(tab, btn) {
    document.querySelectorAll(".content-subtab-btn").forEach(b => {
        b.classList.remove("btn-primary");
        b.classList.add("btn-secondary");
    });
    if (btn) {
        btn.classList.remove("btn-secondary");
        btn.classList.add("btn-primary");
    }

    document.getElementById("content-subtab-faqs").style.display = tab === "faqs" ? "block" : "none";
    document.getElementById("content-subtab-comments").style.display = tab === "comments" ? "block" : "none";
}

async function loadFaqs() {
    const container = document.getElementById("faqs-list-container");
    if (!container) return;

    try {
        const res = await fetch(`/api/faqs?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();

        container.innerHTML = "";
        if (!data.faqs || data.faqs.length === 0) {
            container.innerHTML = `<div style="text-align: center; color: var(--text-dim); padding: 25px;">No custom Q&A pairs added yet in this workspace.</div>`;
            return;
        }

        data.faqs.forEach(f => {
            const div = document.createElement("div");
            div.style.cssText = "background: rgba(255,255,255,0.025); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: flex-start;";
            div.innerHTML = `
                <div>
                    <strong style="color:#fff; font-size: 13.5px;"><i class="fas fa-question-circle" style="color:var(--primary-light);"></i> Q: ${f.question}</strong>
                    <p style="font-size: 13px; color: var(--text-muted); margin-top: 6px; line-height: 1.5;"><strong>A:</strong> ${f.answer}</p>
                </div>
                <button class="btn btn-danger" style="padding: 4px 8px; font-size: 11px;" onclick="deleteFaq(${f.id})">
                    <i class="fas fa-trash"></i>
                </button>
            `;
            container.appendChild(div);
        });
    } catch (e) {
        console.error("Load FAQs error:", e);
    }
}

async function handleAddFaq(e) {
    e.preventDefault();
    const q = document.getElementById("faq-question").value.trim();
    const a = document.getElementById("faq-answer").value.trim();

    if (!q || !a) return;

    try {
        const res = await fetch("/api/faqs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question: q, answer: a, workspace_id: currentWorkspaceId })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Q&A Pair added to AI training!", "success");
            document.getElementById("faq-question").value = "";
            document.getElementById("faq-answer").value = "";
            loadFaqs();
        }
    } catch (e) {
        showToast("Could not add FAQ", "danger");
    }
}

async function deleteFaq(faqId) {
    try {
        const res = await fetch(`/api/faqs/${faqId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("FAQ removed", "success");
            loadFaqs();
        }
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ==========================================
// 6. COMMENT AUTOMATION LOGS
// ==========================================
async function loadCommentLogs() {
    const tbody = document.getElementById("comments-tbody");
    if (!tbody) return;

    try {
        const res = await fetch(`/api/comments/logs?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();

        tbody.innerHTML = "";
        if (!data.logs || data.logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-dim); padding: 25px;">No comments received yet. Incoming post comments will be logged here.</td></tr>`;
            return;
        }

        data.logs.forEach(l => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${l.user_name || 'Customer'}</strong></td>
                <td>"${l.comment_text}"</td>
                <td><small style="color: #34d399;">${l.public_reply || '—'}</small></td>
                <td><small style="color: #60a5fa;">${l.private_reply ? l.private_reply.substring(0, 50) + '...' : '—'}</small></td>
                <td>${l.replied_at || ''}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Load comment logs error:", e);
    }
}

async function subscribeFacebookWebhooksManually() {
    showToast("Meta Webhooks সিঙ্ক ও সাবস্ক্রাইব করা হচ্ছে...", "info");
    try {
        const res = await fetch("/api/facebook/subscribe", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("✅ ফেসবুক পেজ সফলভাবে মেটা ওয়েব হুকে (feed, messages) সাবস্ক্রাইব হয়েছে!", "success");
        } else {
            showToast(`⚠️ Webhook Subscribe: ${data.message || data.error || 'টোকেন পারমিশন চেক করুন'}`, "warning");
        }
    } catch (e) {
        showToast("Webhook সাবস্ক্রাইব রিকোয়েস্ট ব্যর্থ হয়েছে", "danger");
    }
}

// ==========================================
// 6. CONTENT & AI BRAIN TRAINING SUBTABS
// ==========================================
function switchContentSubtab(subtab, btn) {
    document.querySelectorAll(".content-subtab-btn").forEach(b => {
        b.className = "btn btn-secondary content-subtab-btn";
    });
    if (btn) btn.className = "btn btn-primary content-subtab-btn";

    document.getElementById("content-subtab-rules").style.display = subtab === 'rules' ? 'block' : 'none';
    document.getElementById("content-subtab-media").style.display = subtab === 'media' ? 'block' : 'none';
    document.getElementById("content-subtab-faqs").style.display = subtab === 'faqs' ? 'block' : 'none';
    document.getElementById("content-subtab-comments").style.display = subtab === 'comments' ? 'block' : 'none';

    if (subtab === 'rules') loadTrainingRules();
    else if (subtab === 'media') loadSavedMediaList();
    else if (subtab === 'faqs') loadFaqs();
    else if (subtab === 'comments') loadCommentLogs();
}

// ------------------------------------------
// AI BRAIN TRAINING RULES MANAGER
// ------------------------------------------
async function loadTrainingRules() {
    const container = document.getElementById("training-rules-list-container");
    if (!container) return;

    try {
        const res = await fetch(`/api/training/rules?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        container.innerHTML = "";

        if (!data.rules || data.rules.length === 0) {
            container.innerHTML = `<div style="padding: 24px; text-align: center; color: var(--text-muted);"><i class="fas fa-brain" style="font-size: 32px; opacity: 0.4; margin-bottom: 8px; display: block;"></i>কোনো কাস্টম ট্রেইনিং রুল যুক্ত করা হয়নি এই ওয়ার্কস্পেসে। নতুন রুল যুক্ত করতে উপরের বাটনে ক্লিক করুন।</div>`;
            return;
        }

        const grid = document.createElement("div");
        grid.style.cssText = "display: flex; flex-direction: column; gap: 12px;";

        data.rules.forEach(r => {
            const card = document.createElement("div");
            card.className = "glass-card";
            card.style.cssText = "padding: 14px 18px; margin: 0; display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; border: 1px solid rgba(255,255,255,0.08);";
            
            const isActive = r.is_active === 1;
            const categoryBadge = `<span class="badge" style="background: rgba(99, 102, 241, 0.2); color: #818cf8; font-size: 11px;">${r.category || 'General'}</span>`;
            const typeBadge = `<span class="badge" style="background: rgba(236, 72, 153, 0.15); color: #f472b6; font-size: 10px; text-transform: uppercase;">${r.rule_type || 'Rule'}</span>`;

            card.innerHTML = `
                <div style="flex: 1;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                        <strong style="color: #fff; font-size: 14px;">${r.title}</strong>
                        ${categoryBadge}
                        ${typeBadge}
                    </div>
                    ${r.question_or_trigger ? `<div style="font-size: 12px; color: #fbbf24; margin-bottom: 4px;"><i class="fas fa-bolt"></i> <strong>Trigger:</strong> "${r.question_or_trigger}"</div>` : ''}
                    <div style="font-size: 13px; color: var(--text-main); line-height: 1.5; background: rgba(0,0,0,0.2); padding: 8px 12px; border-radius: 6px; border-left: 3px solid ${isActive ? '#10b981' : '#6b7280'};">
                        ${r.response_or_rule}
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 10px; padding-top: 4px;">
                    <button class="btn" style="padding: 4px 10px; font-size: 11px; border-radius: 20px; ${isActive ? 'background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid #10b981;' : 'background: rgba(107, 114, 128, 0.2); color: #9ca3af; border: 1px solid #6b7280;'}" onclick="toggleTrainingRuleActive(${r.id})">
                        <i class="fas ${isActive ? 'fa-check-circle' : 'fa-circle-xmark'}"></i> ${isActive ? 'Active' : 'Disabled'}
                    </button>
                    <button class="btn btn-secondary" style="padding: 5px 8px; color: #ef4444;" onclick="deleteTrainingRuleById(${r.id})" title="Delete Rule">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
            grid.appendChild(card);
        });

        container.appendChild(grid);
    } catch (e) {
        console.error("Load training rules error:", e);
    }
}

async function handleCreateTrainingRule(e) {
    e.preventDefault();
    const title = document.getElementById("rule-title").value.trim();
    const category = document.getElementById("rule-category").value;
    const rule_type = document.getElementById("rule-type").value;
    const trigger = document.getElementById("rule-trigger").value.trim();
    const content = document.getElementById("rule-content").value.trim();

    if (!title || !content) return;

    try {
        const res = await fetch("/api/training/rules", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                title: title,
                category: category,
                rule_type: rule_type,
                question_or_trigger: trigger,
                response_or_rule: content,
                is_active: 1,
                workspace_id: currentWorkspaceId
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("এআই ট্রেইনিং রুল সফলভাবে যুক্ত হয়েছে!", "success");
            closeModal("modal-add-training-rule");
            document.getElementById("form-add-training-rule").reset();
            loadTrainingRules();
        }
    } catch (e) {
        showToast("রুল যুক্ত করা সম্ভব হয়নি", "danger");
    }
}

async function toggleTrainingRuleActive(ruleId) {
    try {
        await fetch(`/api/training/rules/${ruleId}/toggle`, { method: "POST" });
        loadTrainingRules();
        showToast("রুল স্ট্যাটাস আপডেট করা হয়েছে", "success");
    } catch (e) {
        showToast("Error updating status", "danger");
    }
}

async function deleteTrainingRuleById(ruleId) {
    if (!confirm("আপনি কি নিশ্চিত এই ট্রেইনিং রুলটি মুছে ফেলতে চান?")) return;
    try {
        await fetch(`/api/training/rules/${ruleId}`, { method: "DELETE" });
        loadTrainingRules();
        showToast("রুল ডিলিট সম্পন্ন হয়েছে", "success");
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ------------------------------------------
// SAVED MEDIA LIBRARY (VOICE & VIDEO)
// ------------------------------------------
async function loadSavedMediaList() {
    const container = document.getElementById("saved-media-grid");
    if (!container) return;

    try {
        const res = await fetch(`/api/saved-media?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        container.innerHTML = "";

        if (!data.media || data.media.length === 0) {
            container.innerHTML = `<div style="grid-column: 1/-1; padding: 24px; text-align: center; color: var(--text-muted);"><i class="fas fa-photo-video" style="font-size: 32px; opacity: 0.4; margin-bottom: 8px; display: block;"></i>কোনো সেভ করা ভয়েস বা ভিডিও নেই। "Upload Voice / Video" বাটনে ক্লিক করে যুক্ত করুন।</div>`;
            return;
        }

        data.media.forEach(m => {
            const card = document.createElement("div");
            card.className = "glass-card";
            card.style.cssText = "padding: 14px; margin: 0; display: flex; flex-direction: column; justify-content: space-between; border: 1px solid rgba(255,255,255,0.08);";

            const isVoice = m.media_type === 'voice';
            const isVideo = m.media_type === 'video';

            let previewHtml = "";
            if (isVoice) {
                previewHtml = `<audio controls style="width: 100%; margin: 8px 0; height: 36px;"><source src="${m.file_url}" type="audio/mpeg"></audio>`;
            } else if (isVideo) {
                previewHtml = `<video controls style="width: 100%; max-height: 140px; border-radius: 6px; margin: 8px 0; background: #000;"><source src="${m.file_url}" type="video/mp4"></video>`;
            } else {
                previewHtml = `<img src="${m.file_url}" style="width: 100%; height: 120px; object-fit: cover; border-radius: 6px; margin: 8px 0;">`;
            }

            card.innerHTML = `
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <strong style="color: #fff; font-size: 13px;">${m.title}</strong>
                        <span class="badge" style="font-size: 10px;">${isVoice ? '🎙️ Voice' : (isVideo ? '🎬 Video' : '🖼️ Photo')}</span>
                    </div>
                    ${m.description ? `<small style="color: var(--text-muted); display: block; margin-top: 4px;">${m.description}</small>` : ''}
                    ${previewHtml}
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.06);">
                    <small style="color: var(--text-dim); font-size: 10px;">${m.created_at || ''}</small>
                    <button class="btn btn-secondary" style="padding: 4px 8px; color: #ef4444; font-size: 11px;" onclick="deleteSavedMediaById(${m.id})">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error("Load saved media error:", e);
    }
}

async function handleUploadSavedMedia(e) {
    e.preventDefault();
    const title = document.getElementById("media-title").value.trim();
    const media_type = document.getElementById("media-type").value;
    const desc = document.getElementById("media-desc").value.trim();
    const fileInput = document.getElementById("media-file");

    if (!fileInput.files || fileInput.files.length === 0) {
        showToast("দয়া করে ফাইল সিলেক্ট করুন", "danger");
        return;
    }

    const formData = new FormData();
    formData.append("title", title);
    formData.append("media_type", media_type);
    formData.append("description", desc);
    formData.append("file", fileInput.files[0]);
    formData.append("workspace_id", currentWorkspaceId);

    try {
        showToast("আপলোড হচ্ছে...", "info");
        const res = await fetch("/api/saved-media/upload", {
            method: "POST",
            body: formData
        });
        const data = await res.json();
        if (data.success) {
            showToast("মিডিয়া সফলভাবে আপলোড হয়েছে!", "success");
            closeModal("modal-upload-media");
            document.getElementById("form-upload-media").reset();
            loadSavedMediaList();
        }
    } catch (e) {
        showToast("Upload failed", "danger");
    }
}

async function deleteSavedMediaById(mediaId) {
    if (!confirm("আপনি কি নিশ্চিত এই মিডিয়া ফাইলটি ডিলিট করতে চান?")) return;
    try {
        await fetch(`/api/saved-media/${mediaId}`, { method: "DELETE" });
        loadSavedMediaList();
        showToast("মিডিয়া ডিলিট সম্পন্ন হয়েছে", "success");
    } catch (e) {
        showToast("Delete failed", "danger");
    }
}

// ------------------------------------------
// QUICK MEDIA SEND IN OMNICHAT
// ------------------------------------------
let activeQuickMediaType = 'voice';

async function openQuickMediaModal(type) {
    activeQuickMediaType = type;
    const titleElem = document.getElementById("quick-media-modal-title");
    if (titleElem) {
        titleElem.innerHTML = type === 'voice' 
            ? '<i class="fas fa-microphone-lines" style="color:#ec4899;"></i> Send Saved Voice Note'
            : '<i class="fas fa-video" style="color:#3b82f6;"></i> Send Saved Product Demo Video';
    }

    const container = document.getElementById("quick-media-list-container");
    if (!container) return;

    try {
        container.innerHTML = `<div style="text-align: center; padding: 20px;"><i class="fas fa-spinner fa-spin"></i> Loading...</div>`;
        openModal("modal-quick-media");

        const res = await fetch(`/api/saved-media?type=${type}&workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        container.innerHTML = "";

        if (!data.media || data.media.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; padding: 25px; color: var(--text-muted);">
                    কোনো ${type === 'voice' ? 'ভয়েস নোট' : 'ভিডিও'} পাওয়া যায়নি।<br>
                    <button class="btn btn-primary" style="margin-top: 10px; font-size: 11px;" onclick="closeModal('modal-quick-media'); openModal('modal-upload-media');">
                        <i class="fas fa-upload"></i> Upload Now
                    </button>
                </div>
            `;
            return;
        }

        data.media.forEach(m => {
            const row = document.createElement("div");
            row.style.cssText = "padding: 10px 14px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; display: flex; justify-content: space-between; align-items: center; gap: 12px;";

            const preview = type === 'voice' 
                ? `<audio controls style="height: 32px; width: 180px;"><source src="${m.file_url}"></audio>`
                : `<video style="height: 40px; width: 60px; object-fit: cover; border-radius: 4px;" src="${m.file_url}"></video>`;

            row.innerHTML = `
                <div style="flex: 1;">
                    <strong style="color: #fff; font-size: 13px;">${m.title}</strong>
                    ${m.description ? `<small style="color: var(--text-muted); display: block;">${m.description}</small>` : ''}
                </div>
                <div>${preview}</div>
                <button class="btn btn-primary" style="padding: 6px 14px; font-size: 11px; white-space: nowrap;" onclick="sendSavedMediaToActiveChat(${m.id})">
                    <i class="fas fa-paper-plane"></i> Send
                </button>
            `;
            container.appendChild(row);
        });
    } catch (e) {
        console.error("Open quick media modal error:", e);
    }
}

async function sendSavedMediaToActiveChat(mediaId) {
    if (!activeConversationId) {
        showToast("Please select a conversation first", "warning");
        return;
    }

    try {
        showToast("Sending media to customer...", "info");
        const res = await fetch("/api/saved-media/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                conversation_id: activeConversationId,
                media_id: mediaId
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("মিডিয়া সফলভাবে কাস্টমারকে পাঠানো হয়েছে!", "success");
            closeModal("modal-quick-media");
            loadOmnichatMessages(activeConversationId);
            loadOmnichatConversations();
        } else {
            showToast(data.error || "Failed to send media", "danger");
        }
    } catch (e) {
        showToast("Send error", "danger");
    }
}

// ==========================================
// 7. OMNICHAT (INBOX)
// ==========================================
let activeConversationId = null;
let activeConversationsList = [];

async function loadOmnichatConversations() {
    const container = document.getElementById("omnichat-threads-list");
    if (!container) return;

    try {
        const pageFilter = document.getElementById("omnichat-page-filter")?.value || "";
        const channelFilter = document.getElementById("omnichat-channel-filter")?.value || "";

        let url = "/api/omnichat/conversations";
        const params = new URLSearchParams();
        params.append("workspace_id", currentWorkspaceId);
        if (pageFilter) params.append("page_id", pageFilter);
        if (channelFilter) params.append("channel", channelFilter);
        if (params.toString()) url += `?${params.toString()}`;

        const res = await fetch(url);
        const data = await res.json();


        container.innerHTML = "";
        if (!data.conversations || data.conversations.length === 0) {
            container.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--text-dim);">No active conversations found.</div>`;
            return;
        }

        activeConversationsList = data.conversations;

        data.conversations.forEach((c, idx) => {
            const item = document.createElement("div");
            item.style.cssText = "padding: 12px 16px; border-bottom: 1px solid var(--border-color); cursor: pointer; transition: var(--transition);";
            if (activeConversationId === c.id || (idx === 0 && !activeConversationId)) {
                activeConversationId = c.id;
                item.style.background = "var(--primary-soft)";
                updateOmnichatHeader(c);
            }
            const isWhatsApp = (c.channel || '').toLowerCase() === 'whatsapp';
            const channelBadge = isWhatsApp
                ? `<span class="badge" style="background: rgba(37, 211, 102, 0.2); color: #25d366; font-size: 10px; font-weight: 600;"><i class="fab fa-whatsapp"></i> WhatsApp</span>`
                : `<span class="badge" style="background: rgba(24, 119, 242, 0.2); color: #60a5fa; font-size: 10px; font-weight: 600;"><i class="fab fa-facebook-messenger"></i> Messenger</span>`;

            const pageBadge = c.page_name 
                ? `<span class="badge" style="background: rgba(99, 102, 241, 0.15); color: #818cf8; font-size: 9.5px; padding: 2px 6px; margin-left: 4px;">${c.page_name}</span>`
                : '';

            const aiStatusIcon = c.human_takeover === 1 
                ? `<span title="AI Paused for this customer" style="color: #f59e0b; font-size: 10px; margin-left: 6px;"><i class="fas fa-pause-circle"></i> Owner Mode</span>` 
                : `<span title="AI Auto-Reply Active" style="color: #10b981; font-size: 10px; margin-left: 6px;"><i class="fas fa-robot"></i> AI Active</span>`;

            item.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                    <strong style="color: #fff; font-size: 13.5px;">${c.customer_name || 'Customer'}</strong>
                    <div style="display: flex; align-items: center; gap: 4px;">${pageBadge} ${channelBadge}</div>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--text-muted);">
                    <span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px;">${c.last_message || ''}</span>
                    ${aiStatusIcon}
                </div>
            `;
            item.addEventListener("click", () => {
                activeConversationId = c.id;
                document.querySelectorAll("#omnichat-threads-list > div").forEach(d => d.style.background = "transparent");
                item.style.background = "var(--primary-soft)";
                updateOmnichatHeader(c);
                loadOmnichatMessages(c.id);
                // On mobile: smoothly switch to chat pane
                document.querySelector(".omnichat-box")?.classList.add("mobile-chat-open");
            });
            container.appendChild(item);
        });

        if (activeConversationId && window.innerWidth > 992) {
            loadOmnichatMessages(activeConversationId);
        }
    } catch (e) {
        console.error("Load Omnichat conversations error:", e);
    }
}

function closeOmnichatMobileChat() {
    document.querySelector(".omnichat-box")?.classList.remove("mobile-chat-open");
}

function updateOmnichatHeader(c) {
    if (!c) return;
    const nameElem = document.getElementById("omnichat-active-customer-name");
    const badgeElem = document.getElementById("omnichat-active-channel-badge");
    const aiBtn = document.getElementById("omnichat-ai-toggle-btn");
    const aiText = document.getElementById("omnichat-ai-toggle-text");

    if (nameElem) nameElem.innerText = c.customer_name || 'Customer';
    if (badgeElem) {
        badgeElem.innerText = (c.channel || 'whatsapp').toUpperCase();
        badgeElem.className = (c.channel === 'whatsapp') ? 'badge badge-confirmed' : 'badge badge-shipped';
    }

    if (aiBtn && aiText) {
        if (c.human_takeover === 1) {
            aiBtn.style.background = "rgba(245, 158, 11, 0.2)";
            aiBtn.style.border = "1px solid #f59e0b";
            aiBtn.style.color = "#fbbf24";
            aiText.innerText = "AI Paused (Owner Mode)";
            aiBtn.title = "Click to resume AI auto-reply for this customer";
        } else {
            aiBtn.style.background = "rgba(16, 185, 129, 0.15)";
            aiBtn.style.border = "1px solid #10b981";
            aiBtn.style.color = "#34d399";
            aiText.innerText = "AI Active";
            aiBtn.title = "Click to pause AI (take over conversation manually)";
        }
    }
}

async function toggleActiveChatAI() {
    if (!activeConversationId) return;

    try {
        const res = await fetch("/api/omnichat/toggle-ai", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ conversation_id: activeConversationId })
        });
        const data = await res.json();
        if (data.success) {
            const isPaused = data.human_takeover === 1;
            showToast(isPaused ? "এই কাস্টমারের জন্য এআই সাময়িকভাবে বন্ধ করা হয়েছে (Owner Mode)" : "এই কাস্টমারের জন্য এআই স্বয়ংক্রিয় উত্তর পুনরায় চালু করা হয়েছে (AI Active)", "info");
            loadOmnichatConversations();
        }
    } catch (e) {
        showToast("Failed to toggle AI status", "danger");
    }
}

async function loadOmnichatMessages(cid) {
    const container = document.getElementById("omnichat-messages-container");
    if (!container || !cid) return;

    try {
        const res = await fetch(`/api/omnichat/messages/${cid}`);
        const data = await res.json();

        container.innerHTML = "";
        data.messages.forEach(m => {
            const div = document.createElement("div");
            div.className = `message-bubble ${m.sender_type === 'user' ? 'message-user' : 'message-bot'}`;
            
            let html = "";
            if (m.content) {
                let formatted = m.content;
                // Render any markdown images as beautiful image cards
                formatted = formatted.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, src) => {
                    return `<div style="margin: 6px 0;"><img src="${src}" alt="${alt || 'Image'}" style="max-width: 220px; max-height: 180px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); display: block;"></div>`;
                });
                html += `<div>${formatted.replace(/\n/g, "<br>")}</div>`;
            }
            if (m.media_url) {
                if (m.message_type === 'voice' || m.message_type === 'audio') {
                    html += `<div style="margin-top: 6px;"><audio controls style="height: 32px; max-width: 240px;"><source src="${m.media_url}"></audio></div>`;
                } else if (m.message_type === 'video') {
                    html += `<div style="margin-top: 6px;"><video controls style="max-width: 240px; max-height: 180px; border-radius: 8px;"><source src="${m.media_url}"></video></div>`;
                } else {
                    html += `<div style="margin-top: 6px;"><img src="${m.media_url}" style="max-width: 220px; max-height: 180px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1);"></div>`;
                }
            }
            div.innerHTML = html;
            container.appendChild(div);
        });
        container.scrollTop = container.scrollHeight;
    } catch (e) {
        console.error("Load Omnichat messages error:", e);
    }
}

// Auto-poll Omnichat every 4 seconds for real-time live chat updates
setInterval(() => {
    const omnichatTab = document.getElementById("tab-omnichat");
    if (omnichatTab && omnichatTab.classList.contains("active")) {
        loadOmnichatConversations();
    }
}, 4000);

async function handleOmnichatSend(e) {
    e.preventDefault();
    const input = document.getElementById("omnichat-reply-input");
    const text = input.value.trim();
    if (!text || !activeConversationId) return;

    try {
        const res = await fetch("/api/omnichat/send", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ conversation_id: activeConversationId, content: text })
        });
        const data = await res.json();
        if (data.success) {
            input.value = "";
            loadOmnichatMessages(activeConversationId);
            loadOmnichatConversations();
            showToast("Message sent to customer", "success");
        } else {
            showToast(data.error || "Failed to send message via WhatsApp Cloud API", "danger");
        }
    } catch (e) {
        showToast("Send failed: Server error", "danger");
    }
}

// ==========================================
// 8. SETTINGS & AI CONFIGURATION
// ==========================================
let isAIMasterActive = true;

async function loadSettings() {
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        const s = data.settings || {};

        // Master Switch state
        isAIMasterActive = (s.ai_enabled !== "false");
        updateAIMasterButtonUI(isAIMasterActive);

        const fbToken = s.fb_page_access_token || "";
        const waToken = s.whatsapp_access_token || s.meta_system_user_access_token || "";
        const waStatus = s.whatsapp_connection_status || "connected";

        if (document.getElementById("setting-fb-token")) document.getElementById("setting-fb-token").value = fbToken;
        if (document.getElementById("setting-fb-page-id")) document.getElementById("setting-fb-page-id").value = s.fb_page_id || "";
        if (document.getElementById("setting-fb-app-secret")) document.getElementById("setting-fb-app-secret").value = s.fb_app_secret || "";

        if (document.getElementById("setting-wa-waba-id")) document.getElementById("setting-wa-waba-id").value = s.whatsapp_waba_id || "";
        if (document.getElementById("setting-wa-phone-id")) document.getElementById("setting-wa-phone-id").value = s.whatsapp_phone_number_id || "";
        if (document.getElementById("setting-wa-token")) document.getElementById("setting-wa-token").value = waToken;

        if (document.getElementById("setting-gemini-key")) document.getElementById("setting-gemini-key").value = s.gemini_api_key || "";
        if (document.getElementById("setting-shop-name")) document.getElementById("setting-shop-name").value = s.shop_name || "RS Graphics";
        if (document.getElementById("setting-shop-phone")) document.getElementById("setting-shop-phone").value = s.shop_phone || "";
        if (document.getElementById("setting-delivery-inside")) document.getElementById("setting-delivery-inside").value = s.delivery_inside_dhaka || "70";
        if (document.getElementById("setting-delivery-outside")) document.getElementById("setting-delivery-outside").value = s.delivery_outside_dhaka || "130";
        if (document.getElementById("setting-comment-reply-template")) document.getElementById("setting-comment-reply-template").value = s.comment_reply_template || "";

        // Display WhatsApp connection details
        const isWaConnected = (
            s.whatsapp_connection_status === "connected" 
            && s.whatsapp_phone_number_id 
            && s.whatsapp_phone_number_id !== "1265595526643418"
        );

        if (document.getElementById("wa-display-phone")) {
            document.getElementById("wa-display-phone").innerHTML = `<i class="fas fa-phone-alt" style="color: #25d366; font-size: 12px;"></i> +8801816504097`;
        }
        if (document.getElementById("wa-display-waba-id")) {
            document.getElementById("wa-display-waba-id").innerText = s.whatsapp_waba_id || "271335301757320";
        }
        if (document.getElementById("wa-display-phone-id")) {
            document.getElementById("wa-display-phone-id").innerText = isWaConnected ? s.whatsapp_phone_number_id : "Awaiting Meta verification";
        }

        // Update Facebook Connection Badge
        const fbBadge = document.getElementById("fb-status-badge");
        if (fbBadge) {
            if (s.fb_token_configured || (fbToken && fbToken.trim().length > 5)) {
                fbBadge.className = "badge badge-confirmed";
                fbBadge.innerHTML = `<i class="fas fa-check-circle"></i> Connected & Saved`;
            } else {
                fbBadge.className = "badge badge-pending";
                fbBadge.innerText = "Ready to Connect";
            }
        }

        // Update WhatsApp Connection Badge
        const waBadge = document.getElementById("wa-status-badge");
        if (waBadge) {
            if (isWaConnected) {
                waBadge.className = "badge badge-confirmed";
                waBadge.innerHTML = `<i class="fas fa-check-circle"></i> Connected & Saved (Coexistence Active)`;
            } else if (s.whatsapp_connection_status === "pending") {
                waBadge.className = "badge badge-pending";
                waBadge.innerText = "Verification Pending in Meta";
            } else {
                waBadge.className = "badge badge-pending";
                waBadge.innerHTML = `<i class="fas fa-circle-notch"></i> Ready to Connect (+8801816504097)`;
            }
        }

        // Dynamic Webhook URLs based on current origin
        const currentOrigin = window.location.origin;
        if (document.getElementById("setting-fb-webhook-display")) {
            document.getElementById("setting-fb-webhook-display").value = `${currentOrigin}/webhook/facebook`;
        }
        if (document.getElementById("setting-wa-webhook-display")) {
            document.getElementById("setting-wa-webhook-display").value = `${currentOrigin}/webhook/whatsapp`;
        }

        // AI Arena Setup tab inputs
        if (document.getElementById("arena-shop-name")) document.getElementById("arena-shop-name").value = s.shop_name || "RS Graphics";
        if (document.getElementById("arena-system-prompt")) document.getElementById("arena-system-prompt").value = s.ai_system_prompt || "";
        if (document.getElementById("phone-header-shop-name")) document.getElementById("phone-header-shop-name").innerText = s.shop_name || "RS Graphics";

    } catch (e) {
        console.error("Load settings error:", e);
    }
}

async function disconnectWhatsApp() {
    if (!confirm("Are you sure you want to reset WhatsApp Business connection status?")) return;
    try {
        const res = await fetch("/api/whatsapp/disconnect", { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("WhatsApp connection reset", "info");
            loadSettings();
        }
    } catch (e) {
        showToast("Failed to disconnect", "danger");
    }
}

// Meta Embedded Signup for WhatsApp Business App Coexistence
console.log("[WA EMBEDDED SIGNUP VERSION] 2026-08-20-IMAGEFIX");
let metaSDKInitialized = false;
let embeddedSignupSessionInfo = null;

// Listen for WhatsApp Embedded Signup message events from Meta
window.addEventListener('message', (event) => {
    if (event.origin !== "https://www.facebook.com" && event.origin !== "https://web.facebook.com") return;
    try {
        const data = typeof event.data === "string" ? JSON.parse(event.data) : event.data;
        if (data && (data.type === 'WA_EMBEDDED_SIGNUP' || data.event === 'FINISH' || data.event === 'COMPLETE')) {
            console.log('[WhatsApp Embedded Signup] Session Info Event received');
            embeddedSignupSessionInfo = data.data || data;
            const phoneId = embeddedSignupSessionInfo.phone_number_id || embeddedSignupSessionInfo.phoneNumberId;
            const wabaId = embeddedSignupSessionInfo.waba_id || embeddedSignupSessionInfo.wabaId;
            if (phoneId) console.log('[WA DEBUG] Phone Number ID received:', phoneId);
            if (wabaId) console.log('[WA DEBUG] WABA ID received:', wabaId);
        }
    } catch (e) {}
});

async function initMetaSDK(targetAppId) {
    const appId = String(targetAppId || "1274136137801052").trim();

    if (window.FB) {
        try {
            FB.init({
                appId: appId,
                cookie: true,
                xfbml: true,
                version: "v19.0"
            });
            metaSDKInitialized = true;
            return;
        } catch (e) {}
    }

    return new Promise((resolve) => {
        window.fbAsyncInit = function() {
            FB.init({
                appId: appId,
                cookie: true,
                xfbml: true,
                version: "v19.0"
            });
            metaSDKInitialized = true;
            resolve();
        };

        if (!document.getElementById("facebook-jssdk")) {
            const js = document.createElement("script");
            js.id = "facebook-jssdk";
            js.src = "https://connect.facebook.net/en_US/sdk.js";
            document.head.appendChild(js);
        } else {
            let checks = 0;
            const interval = setInterval(() => {
                checks++;
                if (window.FB) {
                    clearInterval(interval);
                    FB.init({
                        appId: appId,
                        cookie: true,
                        xfbml: true,
                        version: "v19.0"
                    });
                    metaSDKInitialized = true;
                    resolve();
                } else if (checks > 40) {
                    clearInterval(interval);
                    resolve();
                }
            }, 100);
        }
    });
}

async function launchWhatsAppEmbeddedSignup() {
    showToast("Connecting to Meta WhatsApp Business...", "info");

    try {
        const res = await fetch("/api/whatsapp/embedded-config");
        const config = await res.json();
        let rawId = String(config.config_id || "1003403176086013").trim();
        const configId = (rawId === "10034031760860138") ? "1003403176086013" : rawId;
        const appId = String(config.app_id || "1274136137801052").trim();

        if (!configId || configId.length === 0) {
            showToast("Meta Embedded Signup configuration missing. Please check META_EMBEDDED_SIGNUP_CONFIG_ID in Render.", "warning");
            const manualDetails = document.querySelector("#tab-integrations details");
            if (manualDetails) manualDetails.open = true;
            return;
        }

        await initMetaSDK(appId);

        if (!window.FB) {
            showToast("Meta SDK could not be loaded. Please check your network connection.", "danger");
            return;
        }

        const loginOptions = {
            config_id: configId,
            response_type: "code",
            override_default_response_type: true,
            extras: {
                setup: {},
                featureType: "whatsapp_business_app_onboarding",
                sessionInfoVersion: "3"
            }
        };

        console.log("[WA DEBUG] appId =", appId);
        console.log("[WA DEBUG] configId =", configId);
        console.log("[WA DEBUG] configId length =", configId.length);
        console.log("[WA DEBUG] loginOptions =", loginOptions);

        FB.login((response) => {
            console.log("[WA DEBUG] Meta login response:", response);
            if (response && response.authResponse && response.authResponse.code) {
                console.log("[WA DEBUG] authorization code received: YES");
                const code = response.authResponse.code;
                const sessionData = embeddedSignupSessionInfo || {};
                const wabaId = sessionData.waba_id || sessionData.wabaId || null;
                const phoneId = sessionData.phone_number_id || sessionData.phoneNumberId || null;
                const displayPhone = sessionData.display_phone_number || sessionData.displayPhoneNumber || '01816504097';

                if (wabaId) console.log("[WA DEBUG] WABA ID:", wabaId);
                if (phoneId) console.log("[WA DEBUG] Phone Number ID:", phoneId);

                fetch("/api/whatsapp/embedded-signup", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        code: code,
                        waba_id: wabaId,
                        phone_number_id: phoneId,
                        display_phone_number: displayPhone
                    })
                }).then(r => r.json()).then(result => {
                    console.log("[WA DEBUG] backend callback result:", result);
                    if (result && result.success) {
                        showToast("✅ WhatsApp Business App Connected (Coexistence Mode Active)!", "success");
                        loadSettings();
                    } else {
                        console.error("[WhatsApp Embedded Signup] Connection failed:", result);
                        showToast(result.message || "Embedded Signup failed", "danger");
                    }
                }).catch(err => {
                    console.error("[WhatsApp Embedded Signup] API error:", err);
                    showToast("Failed to save connection on server", "danger");
                });
            } else if (response && response.status === 'not_authorized') {
                console.warn("[WA DEBUG] Meta login not authorized");
                showToast("Meta login not authorized or cancelled", "warning");
            } else {
                console.log("[WA DEBUG] WhatsApp connection was cancelled or closed");
                showToast("WhatsApp connection was cancelled.", "warning");
            }
        }, loginOptions);

    } catch (err) {
        console.error("[WhatsApp Embedded Signup] Launch Error:", err);
        showToast("Failed to launch Meta Embedded Signup", "danger");
    }
}

function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === "password") {
        input.type = "text";
        if (btn) btn.innerHTML = `<i class="fas fa-eye-slash" style="color: var(--primary-light);"></i>`;
    } else {
        input.type = "password";
        if (btn) btn.innerHTML = `<i class="fas fa-eye"></i>`;
    }
}

function updateAIMasterButtonUI(active) {
    const btn = document.getElementById("ai-master-toggle-btn");
    const text = document.getElementById("ai-master-status-text");
    const mobileBtn = document.getElementById("mobile-ai-master-btn");
    const mobileText = document.getElementById("mobile-ai-master-text");

    if (btn) {
        if (active) {
            btn.style.background = "rgba(16, 185, 129, 0.15)";
            btn.style.borderColor = "#10b981";
            btn.style.color = "#34d399";
            btn.innerHTML = `<i class="fas fa-circle" style="font-size: 9px; color: #34d399;"></i> <span id="ai-master-status-text">AI Agent: Active (Auto-Reply)</span>`;
        } else {
            btn.style.background = "rgba(239, 68, 68, 0.15)";
            btn.style.borderColor = "#ef4444";
            btn.style.color = "#f87171";
            btn.innerHTML = `<i class="fas fa-pause-circle" style="font-size: 11px; color: #f87171;"></i> <span id="ai-master-status-text">AI Agent: Paused (Manual Mode)</span>`;
        }
    }

    if (mobileBtn) {
        if (active) {
            mobileBtn.style.background = "rgba(16, 185, 129, 0.15)";
            mobileBtn.style.borderColor = "#10b981";
            mobileBtn.style.color = "#34d399";
            mobileBtn.innerHTML = `<i class="fas fa-circle" style="font-size: 7px;"></i> <span id="mobile-ai-master-text">Active</span>`;
        } else {
            mobileBtn.style.background = "rgba(239, 68, 68, 0.15)";
            mobileBtn.style.borderColor = "#ef4444";
            mobileBtn.style.color = "#f87171";
            mobileBtn.innerHTML = `<i class="fas fa-pause-circle" style="font-size: 8px;"></i> <span id="mobile-ai-master-text">Paused</span>`;
        }
    }
}

async function toggleAIMasterSwitch() {
    isAIMasterActive = !isAIMasterActive;
    updateAIMasterButtonUI(isAIMasterActive);

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ai_enabled: isAIMasterActive ? "true" : "false" })
        });
        const data = await res.json();
        if (data.success) {
            if (isAIMasterActive) {
                showToast("🟢 এআই এজেন্ট চালু করা হয়েছে (২৪ ঘণ্টা অটো-রিপ্লাই মোড)", "success");
            } else {
                showToast("⏸️ এআই এজেন্ট বন্ধ করা হয়েছে (ম্যানুয়াল মোড)", "danger");
            }
        }
    } catch (e) {
        showToast("Switch update failed", "danger");
    }
}

async function saveFacebookSettings() {
    const token = document.getElementById("setting-fb-token") ? document.getElementById("setting-fb-token").value.trim() : "";
    if (!token) {
        showToast("দয়া করে Facebook Page Access Token-টি পেস্ট করুন", "warning");
        return;
    }

    if (token.includes("...")) {
        showToast("Token is already configured securely.", "info");
        return;
    }

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ fb_page_access_token: token })
        });
        const data = await res.json();
        if (data.success) {
            showToast("✅ Facebook Page Access Token সফলভাবে সংরক্ষিত হয়েছে!", "success");
            loadSettings();
        }
    } catch (e) {
        showToast("Failed to save Facebook token", "danger");
    }
}

async function saveWhatsAppSettings() {
    const wabaId = document.getElementById("setting-wa-waba-id") ? document.getElementById("setting-wa-waba-id").value.trim() : "";
    const phoneId = document.getElementById("setting-wa-phone-id") ? document.getElementById("setting-wa-phone-id").value.trim() : "";
    const token = document.getElementById("setting-wa-token") ? document.getElementById("setting-wa-token").value.trim() : "";

    const payload = {};
    if (wabaId) payload.whatsapp_waba_id = wabaId;
    if (phoneId) payload.whatsapp_phone_number_id = phoneId;
    if (token && !token.includes("...")) payload.whatsapp_access_token = token;
    payload.whatsapp_connection_mode = "business_app_coexistence";

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("✅ WhatsApp Settings সফলভাবে সংরক্ষিত হয়েছে!", "success");
            loadAllSettings();
        }
    } catch (e) {
        showToast("Failed to save WhatsApp settings", "danger");
    }
}

function setTrainerPrompt(snippet) {
    const ta = document.getElementById("arena-system-prompt");
    if (ta) {
        ta.value += (ta.value ? "\n" : "") + snippet;
        showToast("Shortcut added to AI knowledge prompt", "info");
    }
}

// ==========================================
// 9. SMARTPHONE CUSTOMER SIMULATOR (Presswayy Style)
// ==========================================
let currentSelectedPhoneImage = null;

function initSmartphoneSimulator() {
    const form = document.getElementById("phone-input-form");
    const input = document.getElementById("phone-text-input");
    const imageInput = document.getElementById("phone-image-upload");
    const previewBar = document.getElementById("phone-image-preview-bar");
    const previewThumb = document.getElementById("phone-image-preview-thumb");
    const previewName = document.getElementById("phone-image-preview-name");

    if (!form || !input) return;

    // Handle Image Selection from File Dialog
    if (imageInput) {
        imageInput.addEventListener("change", () => {
            if (imageInput.files && imageInput.files[0]) {
                const file = imageInput.files[0];
                currentSelectedPhoneImage = file;
                if (previewThumb) previewThumb.src = URL.createObjectURL(file);
                if (previewName) previewName.innerText = file.name;
                if (previewBar) previewBar.style.display = "flex";
                input.focus();
                showToast("📷 ছবি সিলেক্ট করা হয়েছে। মেসেজ লিখে বা সরাসরি 'Send' চাপুন।", "info");
            }
        });
    }

    // Support Pasting Images directly from Clipboard (Ctrl+V)
    input.addEventListener("paste", (e) => {
        const items = (e.clipboardData || e.originalEvent.clipboardData).items;
        for (let item of items) {
            if (item.type.indexOf("image") !== -1) {
                const blob = item.getAsFile();
                currentSelectedPhoneImage = blob;
                if (previewThumb) previewThumb.src = URL.createObjectURL(blob);
                if (previewName) previewName.innerText = "Pasted Screenshot.png";
                if (previewBar) previewBar.style.display = "flex";
                showToast("📷 স্ক্রিনশট পেস্ট হয়েছে!", "info");
                break;
            }
        }
    });

    // Form Submission (Text and/or Image)
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = input.value.trim();
        const imgFile = currentSelectedPhoneImage || (imageInput && imageInput.files ? imageInput.files[0] : null);

        if (!text && !imgFile) return;

        // Render User Message in Chat
        appendPhoneMessage("user", text, imgFile ? URL.createObjectURL(imgFile) : null);
        input.value = "";
        cancelPhoneImage();

        const formData = new FormData();
        if (text) formData.append("message", text);
        if (imgFile) formData.append("image", imgFile);
        formData.append("generate_voice", "false");

        const typingEl = appendPhoneTyping();

        try {
            const res = await fetch("/api/test/chat", {
                method: "POST",
                body: formData
            });
            const data = await res.json();
            if (typingEl) typingEl.remove();

            appendPhoneMessage("bot", data.reply_text, null, data.matched_images);

            if (data.order_created) {
                renderPhoneDetectedOrder(data.order_created);
                showToast(`🎉 Order successfully placed: #${data.order_created.order_code}`, "success");
                loadOverview();
                loadOrders();
            }
        } catch (err) {
            if (typingEl) typingEl.remove();
            appendPhoneMessage("bot", "Could not connect to AI. Please verify your Gemini API key.");
        }
    });
}

function cancelPhoneImage() {
    currentSelectedPhoneImage = null;
    const imageInput = document.getElementById("phone-image-upload");
    if (imageInput) imageInput.value = "";
    const previewBar = document.getElementById("phone-image-preview-bar");
    if (previewBar) previewBar.style.display = "none";
}

function sendPhoneQuickQuery(text) {
    const input = document.getElementById("phone-text-input");
    const form = document.getElementById("phone-input-form");
    if (input && form) {
        input.value = text;
        form.dispatchEvent(new Event("submit"));
    }
}

function appendPhoneMessage(sender, text, imgUrl = null, matchedImages = []) {
    const container = document.getElementById("phone-messages");
    if (!container) return;

    const div = document.createElement("div");
    div.className = `message-bubble message-${sender}`;

    let html = "";
    if (imgUrl) {
        html += `<img src="${imgUrl}" style="max-width: 100%; border-radius: 8px; margin-bottom: 6px; display: block;">`;
    }
    if (text) {
        let formatted = text;
        formatted = formatted.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, src) => {
            return `<div style="margin: 6px 0;"><img src="${src}" alt="${alt || 'Image'}" style="max-width: 100%; max-height: 180px; object-fit: contain; border-radius: 8px; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); display: block;"></div>`;
        });
        html += `<div>${formatted.replace(/\n/g, "<br>")}</div>`;
    }
    if (matchedImages && matchedImages.length > 0) {
        html += `<div style="display:flex; gap:6px; margin-top:6px; flex-wrap:wrap;">`;
        matchedImages.forEach(img => {
            html += `<img src="${img}" style="width: 70px; height: 70px; object-fit: cover; border-radius: 6px; border: 1px solid var(--border-color);">`;
        });
        html += `</div>`;
    }

    div.innerHTML = html;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendPhoneTyping() {
    const container = document.getElementById("phone-messages");
    const div = document.createElement("div");
    div.className = "message-bubble message-bot";
    div.innerHTML = `<span style="font-style: italic; color: var(--text-muted);"><i class="fas fa-spinner fa-spin"></i> Typing...</span>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function clearPhoneChat() {
    const container = document.getElementById("phone-messages");
    if (container) {
        container.innerHTML = `<div class="message-bubble message-bot">আসসালামু আলাইকুম আপু/ভাইয়া! 😊 আমাদের শপে আপনাকে স্বাগতম। আপনি কোনো প্রডাক্টের তথ্য জানতে চান বা অর্ডার করতে চান?</div>`;
    }
    const orderCard = document.getElementById("phone-detected-order-card");
    if (orderCard) orderCard.style.display = "none";
}

function renderPhoneDetectedOrder(order) {
    const card = document.getElementById("phone-detected-order-card");
    if (!card) return;

    card.style.display = "block";
    card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 4px;">
            <strong style="color:#34d399; font-size: 12px;"><i class="fas fa-check-circle"></i> New Order Captured!</strong>
            <span class="badge badge-pending" style="font-size: 9px;">Pending</span>
        </div>
        <div style="font-size: 11.5px; color: #fff;">
            <strong>#${order.order_code}</strong> | ${order.customer_name} (${order.customer_phone})<br>
            <strong>Total: ৳${order.total_amount}</strong> (Delivery: ৳${order.delivery_charge})
        </div>
    `;
}

// ==========================================
// 10. MODALS & TOASTS
// ==========================================
function initModals() {
    document.querySelectorAll(".modal-overlay").forEach(m => {
        m.addEventListener("click", (e) => {
            if (e.target === m) m.classList.remove("active");
        });
    });
}

function openModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.add("active");
}

function closeModal(id) {
    const m = document.getElementById(id);
    if (m) m.classList.remove("active");
}

function showToast(message, type = "info") {
    const container = document.getElementById("toast-container") || createToastContainer();
    const toast = document.createElement("div");
    toast.className = `toast`;
    
    let icon = "fa-info-circle";
    if (type === "success") icon = "fa-check-circle";
    if (type === "danger") icon = "fa-exclamation-circle";

    toast.innerHTML = `<i class="fas ${icon}" style="color: var(--${type});"></i> <span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

function createToastContainer() {
    const div = document.createElement("div");
    div.id = "toast-container";
    div.className = "toast-container";
    document.body.appendChild(div);
    return div;
}

// ==========================================
// 11. TRAIN CONTENT & AI AUTO-SYNTHESIZER
// ==========================================
function switchContentSubtab(tabName, btn) {
    document.querySelectorAll(".content-subtab-btn").forEach(b => {
        b.className = "btn btn-secondary content-subtab-btn";
    });
    if (btn) btn.className = "btn btn-primary content-subtab-btn";

    const subtabs = ["rules", "media", "faqs", "comments"];
    subtabs.forEach(t => {
        const el = document.getElementById(`content-subtab-${t}`);
        if (el) el.style.display = (t === tabName) ? "block" : "none";
    });

    if (tabName === "rules") loadTrainingRules();
    if (tabName === "media") loadSavedMediaList();
    if (tabName === "faqs") loadFaqs();
}

async function loadTrainingRules() {
    const container = document.getElementById("training-rules-list-container");
    if (!container) return;

    try {
        const res = await fetch(`/api/training/rules?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        const rules = data.rules || [];

        if (rules.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; color: var(--text-dim); padding: 30px; border: 1px dashed rgba(255,255,255,0.1); border-radius: 8px;">
                    <i class="fas fa-brain" style="font-size: 28px; color: var(--primary-light); margin-bottom: 10px; display: block;"></i>
                    এখনো কোনো স্পেশাল এআই রুলস যোগ করা হয়নি।<br>
                    উপরে আপনার শপের পলিসি বা কাস্টমার হ্যান্ডলিংয়ের কথা বাংলায় লিখে <strong>'🧠 অটো-সিন্থেসাইজ ও এআই ট্রেইন করুন'</strong> বাটনে চাপুন।
                </div>
            `;
            return;
        }

        container.innerHTML = rules.map(r => `
            <div style="background: rgba(13, 17, 28, 0.7); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: flex-start; gap: 14px;">
                <div style="flex: 1;">
                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                        <span class="badge" style="background: rgba(37,99,235,0.25); color: #60a5fa; font-size: 11px;">${r.category || 'General'}</span>
                        <strong style="font-size: 14px; color: #fff;">${r.title}</strong>
                        ${r.is_active ? '<span style="color: #34d399; font-size: 11px;"><i class="fas fa-check-circle"></i> Active</span>' : '<span style="color: #ef4444; font-size: 11px;"><i class="fas fa-pause-circle"></i> Paused</span>'}
                    </div>
                    ${r.question_or_trigger ? `<div style="font-size: 12px; color: #fbbf24; margin-bottom: 4px;"><strong>ট্রিগার:</strong> ${r.question_or_trigger}</div>` : ''}
                    <p style="font-size: 13px; color: var(--text-muted); line-height: 1.5; margin: 0;">${r.response_or_rule}</p>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-sm" style="background: ${r.is_active ? 'rgba(239,68,68,0.15); color: #f87171;' : 'rgba(16,185,129,0.15); color: #34d399;'}" onclick="toggleTrainingRuleActive(${r.id})">
                        ${r.is_active ? '<i class="fas fa-pause"></i> Pause' : '<i class="fas fa-play"></i> Activate'}
                    </button>
                    <button class="btn btn-sm" style="background: rgba(239,68,68,0.2); color: #f87171;" onclick="deleteTrainingRuleById(${r.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('');
    } catch (e) {
        console.error("loadTrainingRules error:", e);
    }
}

async function handleAutoSynthesizeTraining() {
    const textarea = document.getElementById("auto-synthesize-input");
    const btn = document.getElementById("btn-auto-synthesize");
    const alertBox = document.getElementById("synthesize-result-alert");
    const text = textarea ? textarea.value.trim() : "";

    if (!text) {
        showToast("দয়া করে আপনার ব্যবসায়িক নির্দেশনা বা কথাগুলো বক্সে লিখুন", "danger");
        return;
    }

    const originalBtnHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> এআই ব্রেইন বিশ্লেষণ করছে...`;

    if (alertBox) alertBox.style.display = "none";

    try {
        const res = await fetch("/api/training/synthesize", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ raw_text: text, workspace_id: currentWorkspaceId })
        });
        const data = await res.json();

        if (data.success && data.count > 0) {
            textarea.value = "";
            showToast(`🎉 চমৎকার! ${data.count}টি সুনির্দিষ্ট সেলস রুল এআই ব্রেইনে যুক্ত হয়েছে!`, "success");
            
            if (alertBox) {
                alertBox.style.display = "block";
                alertBox.style.background = "rgba(16, 185, 129, 0.15)";
                alertBox.style.border = "1px solid #10b981";
                alertBox.style.color = "#34d399";
                alertBox.innerHTML = `<i class="fas fa-check-circle"></i> <strong>সফল হয়েছে:</strong> আপনার এলোমেলো নোট থেকে <strong>${data.count}টি রুল</strong> স্বয়ংক্রিয়ভাবে আলাদা করে এআই ব্রেইনে সক্রিয় করা হয়েছে।`;
            }
            loadTrainingRules();
        } else {
            showToast(data.message || "রুল সিন্থেসাইজে সমস্যা হয়েছে", "danger");
        }
    } catch (e) {
        console.error("handleAutoSynthesizeTraining error:", e);
        showToast("সার্ভার এরর: এআই ট্রেইনিং সফল হয়নি", "danger");
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
    }
}

async function toggleTrainingRuleActive(id) {
    try {
        const res = await fetch(`/api/training/rules/${id}/toggle`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("রুল স্ট্যাটাস পরিবর্তন করা হয়েছে", "success");
            loadTrainingRules();
        }
    } catch (e) {
        console.error("toggleTrainingRuleActive error:", e);
    }
}

async function deleteTrainingRuleById(id) {
    if (!confirm("আপনি কি নিশ্চিত এই ট্রেইনিং রুলটি মুছে ফেলতে চান?")) return;
    try {
        const res = await fetch(`/api/training/rules/${id}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("ট্রেইনিং রুলটি মুছে ফেলা হয়েছে", "info");
            loadTrainingRules();
        }
    } catch (e) {
        console.error("deleteTrainingRuleById error:", e);
    }
}

async function loadSavedMediaList() {
    const grid = document.getElementById("saved-media-grid");
    if (!grid) return;

    try {
        const res = await fetch(`/api/saved-media?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        const media = data.media || [];

        if (media.length === 0) {
            grid.innerHTML = `
                <div style="grid-column: 1/-1; text-align: center; color: var(--text-dim); padding: 40px;">
                    কোনো সেভ করা ভয়েস ক্লিপ বা ডেমো ভিডিও নেই। উপরে '+ Upload Voice / Video' বাটনে ক্লিক করুন।
                </div>
            `;
            return;
        }

        grid.innerHTML = media.map(m => `
            <div class="glass-card" style="padding: 14px; margin-bottom: 0; background: rgba(13, 17, 28, 0.75);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span class="badge" style="background: ${m.media_type === 'voice' ? 'rgba(236,72,153,0.2)' : 'rgba(59,130,246,0.2)'}; color: ${m.media_type === 'voice' ? '#f472b6' : '#60a5fa'}; font-size: 11px;">
                        <i class="fas ${m.media_type === 'voice' ? 'fa-microphone' : 'fa-video'}"></i> ${m.media_type.toUpperCase()}
                    </span>
                    <button class="btn btn-sm" style="background: rgba(239,68,68,0.2); color: #f87171; padding: 2px 6px;" onclick="deleteSavedMediaById(${m.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
                <strong style="font-size: 13px; color: #fff; display: block; margin-bottom: 6px;">${m.title}</strong>
                ${m.media_type === 'voice' ? `
                    <audio controls style="width: 100%; height: 32px; margin-top: 6px;">
                        <source src="${m.file_url}" type="audio/mpeg">
                    </audio>
                ` : `
                    <video controls style="width: 100%; max-height: 140px; border-radius: 6px; margin-top: 6px; background: #000;">
                        <source src="${m.file_url}" type="video/mp4">
                    </video>
                `}
                <small style="color: var(--text-dim); display: block; margin-top: 6px;">${m.description || ''}</small>
            </div>
        `).join('');
    } catch (e) {
        console.error("loadSavedMediaList error:", e);
    }
}

async function deleteSavedMediaById(id) {
    if (!confirm("আপনি কি নিশ্চিত এই মিডিয়া ফাইলটি মুছে ফেলতে চান?")) return;
    try {
        const res = await fetch(`/api/saved-media/${id}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("মিডিয়া ফাইলটি মুছে ফেলা হয়েছে", "info");
            loadSavedMediaList();
        }
    } catch (e) {
        console.error("deleteSavedMediaById error:", e);
    }
}

// ==========================================
// 12. GENERAL & BLACKLIST SETTINGS
// ==========================================
async function loadAllSettings() {
    try {
        const res = await fetch("/api/settings");
        const data = await res.json();
        const settings = data.settings || {};

        const setVal = (id, key, def) => {
            const el = document.getElementById(id);
            if (el && settings[key] !== undefined && settings[key] !== null) el.value = settings[key];
            else if (el && def !== undefined) el.value = def;
        };

        const shopName = settings["shop_name"] || "RS Graphics (আরএস গ্রাফিক্স)";
        const shopPhone = settings["shop_phone"] || "01816504097";

        setVal("setting-shop-name", "shop_name", shopName);
        setVal("setting-shop-phone", "shop_phone", shopPhone);
        setVal("setting-delivery-inside", "delivery_inside_dhaka", 70);
        setVal("setting-delivery-outside", "delivery_outside_dhaka", 130);
        setVal("setting-blacklisted-numbers", "blacklisted_ai_numbers", "");

        // Comment automation settings
        const setCheck = (id, key, def) => {
            const el = document.getElementById(id);
            if (el) {
                if (settings[key] !== undefined && settings[key] !== null) {
                    el.checked = String(settings[key]).toLowerCase() === "true";
                } else if (def !== undefined) {
                    el.checked = def;
                }
            }
        };

        setCheck("setting-auto-comment", "comment_auto_reply", true);
        setCheck("setting-private-inbox", "private_message_on_comment", true);
        setVal("setting-comment-ai-mode", "comment_ai_mode", "ai_smart");
        setVal("setting-comment-reply-template", "comment_reply_template", "ধন্যবাদ {name} স্যার/ম্যাম! বিস্তারিত তথ্য ও ছবি আপনার ইনবক্সে পাঠানো হয়েছে 🥰");
        toggleCommentModeUI();

        // Also sync AI Train Tab Inputs
        setVal("arena-shop-name", "shop_name", shopName);
        setVal("arena-system-prompt", "ai_system_prompt", "");
        
        const phoneHeader = document.getElementById("phone-header-shop-name");
        if (phoneHeader) phoneHeader.innerText = shopName;
        
        await loadMutedContacts();
    } catch (e) {
        console.error("loadAllSettings error:", e);
    }
}

function toggleCommentModeUI() {
    const modeEl = document.getElementById("setting-comment-ai-mode");
    const tplGroup = document.getElementById("comment-template-group");
    if (modeEl && tplGroup) {
        tplGroup.style.display = modeEl.value === "template" ? "block" : "none";
    }
}

// ------------------------------------------
// MUTED / BLACKLISTED CONTACTS MANAGER
// ------------------------------------------
let cachedMutedContacts = [];

async function loadMutedContacts() {
    const listContainer = document.getElementById("muted-contacts-list-container");
    const dashContainer = document.getElementById("dash-muted-contacts-chips");
    const countBadge = document.getElementById("muted-count-badge");
    const hiddenInput = document.getElementById("setting-blacklisted-numbers");

    try {
        const res = await fetch("/api/muted-contacts");
        const data = await res.json();
        cachedMutedContacts = data.contacts || [];
        const rawNumbers = data.numbers || [];

        if (hiddenInput) hiddenInput.value = rawNumbers.join(", ");
        if (countBadge) countBadge.innerText = `${cachedMutedContacts.length}টি নম্বর`;

        const emptyListHtml = `
            <div style="background: rgba(10, 14, 23, 0.7); border: 1px dashed rgba(255,255,255,0.15); border-radius: 8px; padding: 16px; text-align: center; color: var(--text-dim); font-size: 12.5px;">
                <i class="fas fa-info-circle" style="margin-right: 4px;"></i> এখনো কোনো নম্বর মিউট করা হয়নি। উপরের বাটন বা নিচের ইনপুট দিয়ে নম্বর যোগ করুন।
            </div>
        `;

        if (cachedMutedContacts.length === 0) {
            if (listContainer) listContainer.innerHTML = emptyListHtml;
            if (dashContainer) dashContainer.innerHTML = `<span style="color: var(--text-dim); font-size: 12px;"><i class="fas fa-info-circle"></i> কোনো নম্বর মিউট করা নেই</span>`;
            return;
        }

        // Render Settings Detailed List
        if (listContainer) {
            listContainer.innerHTML = cachedMutedContacts.map(c => `
                <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(239,68,68,0.3); border-radius: 8px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; transition: var(--transition);">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <div style="width: 34px; height: 34px; border-radius: 50%; background: rgba(239,68,68,0.15); display: flex; align-items: center; justify-content: center; color: #f87171; font-size: 14px; flex-shrink: 0;">
                            <i class="fas fa-phone-slash"></i>
                        </div>
                        <div>
                            <div style="font-weight: 600; color: #fff; font-size: 13.5px; display: flex; align-items: center; gap: 6px;">
                                <span>${c.name || 'কাস্টমার'}</span>
                                <span class="badge" style="background: rgba(239,68,68,0.2); color: #f87171; font-size: 10px;">🚫 এআই বন্ধ</span>
                            </div>
                            <div style="font-size: 12.5px; color: #fca5a5; font-family: monospace; letter-spacing: 0.5px; margin-top: 2px;">
                                ${c.phone}
                            </div>
                        </div>
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <button type="button" class="btn btn-sm" style="background: rgba(16,185,129,0.18); border: 1px solid #10b981; color: #34d399; font-size: 11.5px; font-weight: 600; padding: 6px 12px; border-radius: 6px; display: inline-flex; align-items: center; gap: 5px;" onclick="unmuteContact('${c.phone}')" title="এআই উত্তর পুনরায় চালু করুন">
                            <i class="fas fa-unlock"></i> আনব্লক করুন
                        </button>
                        <button type="button" class="btn btn-sm" style="background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #fca5a5; padding: 6px 9px; border-radius: 6px;" onclick="unmuteContact('${c.phone}')" title="লিস্ট থেকে মুছে ফেলুন">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        }

        // Render Dashboard Compact Chips
        if (dashContainer) {
            dashContainer.innerHTML = cachedMutedContacts.map(c => `
                <span style="display: inline-flex; align-items: center; gap: 6px; background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.35); color: #fca5a5; padding: 4px 10px; border-radius: 16px; font-size: 12px; font-weight: 500;">
                    <i class="fas fa-phone-slash" style="font-size: 10px;"></i>
                    <span>${c.name && c.name !== 'কাস্টমার' ? c.name + ' (' + c.phone + ')' : c.phone}</span>
                    <i class="fas fa-times" style="cursor: pointer; margin-left: 4px; color: #f87171;" onclick="unmuteContact('${c.phone}')" title="আনব্লক করুন"></i>
                </span>
            `).join('');
        }

    } catch (e) {
        console.error("loadMutedContacts error:", e);
    }
}

async function handleManualAddMute() {
    const input = document.getElementById("manual-mute-phone-input");
    if (!input || !input.value.trim()) {
        showToast("দয়া করে একটি নম্বর লিখুন (যেমন: 01816504097)", "warning");
        return;
    }

    const clean = input.value.trim();
    try {
        const res = await fetch("/api/muted-contacts/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phone: clean })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`✅ ${clean} সফলভাবে এআই মিউট লিস্টে যুক্ত হয়েছে!`, "success");
            input.value = "";
            await loadMutedContacts();
        } else {
            showToast(data.message || "মিউট করতে সমস্যা হয়েছে", "danger");
        }
    } catch (e) {
        console.error("handleManualAddMute error:", e);
        showToast("মিউট করতে সমস্যা হয়েছে", "danger");
    }
}

async function unmuteContact(phone) {
    if (!phone) return;
    try {
        const res = await fetch("/api/muted-contacts/remove", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phone: phone })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`🔓 ${phone} সফলভাবে আনব্লক করা হয়েছে!`, "info");
            await loadMutedContacts();
        }
    } catch (e) {
        console.error("unmuteContact error:", e);
        showToast("আনব্লক করতে সমস্যা হয়েছে", "danger");
    }
}

// 1. Native Android & Web Contact Picker Trigger
async function pickPhoneOrWhatsAppContact() {
    // Check if running inside Android Native App Wrapper
    if (window.AndroidBridge && typeof window.AndroidBridge.openContactPicker === "function") {
        try {
            window.AndroidBridge.openContactPicker();
            return;
        } catch (e) {
            console.error("AndroidBridge error:", e);
        }
    }

    // Web Contact Picker API (Chrome on Android)
    if ("contacts" in navigator && "select" in navigator.contacts) {
        try {
            const props = ["name", "tel"];
            const opts = { multiple: true };
            const contacts = await navigator.contacts.select(props, opts);
            if (contacts && contacts.length > 0) {
                let addedCount = 0;
                for (const c of contacts) {
                    if (c.tel && c.tel.length > 0) {
                        for (const t of c.tel) {
                            const clean = t.replace(/\s+/g, "").replace(/-/g, "");
                            if (clean) {
                                await fetch("/api/muted-contacts/add", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ phone: clean })
                                });
                                addedCount++;
                            }
                        }
                    }
                }
                if (addedCount > 0) {
                    await loadMutedContacts();
                    showToast(`🎉 ${addedCount}টি কন্টাক্ট এআই মিউট লিস্টে যুক্ত হয়েছে!`, "success");
                }
                return;
            }
        } catch (e) {
            console.log("Web Contact Picker cancelled or not supported, opening Chat selector modal:", e);
        }
    }

    // Fallback: Open Chat Selector Modal
    openChatSelectorModal();
}

// Callback invoked by Android Native App
window.onNativeContactPicked = async function(name, phone) {
    if (!phone) return;
    const clean = phone.replace(/\s+/g, "").replace(/-/g, "");
    try {
        const res = await fetch("/api/muted-contacts/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phone: clean })
        });
        const data = await res.json();
        if (data.success) {
            showToast(`✅ ${name ? name + ' (' + clean + ')' : clean} এআই মিউট লিস্টে যুক্ত হয়েছে!`, "success");
            await loadMutedContacts();
        }
    } catch (e) {
        console.error("onNativeContactPicked error:", e);
    }
};

// 2. Chat Selector Modal (WhatsApp & Messenger Chats)
let cachedConversationsForMute = [];

async function openChatSelectorModal() {
    openModal("modal-select-chats-to-mute");
    const container = document.getElementById("chat-selector-list-container");
    if (container) {
        container.innerHTML = `<div style="text-align: center; color: var(--text-dim); padding: 20px;"><i class="fas fa-spinner fa-spin"></i> চ্যাট লিস্ট লোড হচ্ছে...</div>`;
    }

    try {
        const res = await fetch("/api/conversations");
        const data = await res.json();
        cachedConversationsForMute = data.conversations || [];
        renderMuteChatSelectorList(cachedConversationsForMute);
    } catch (e) {
        console.error("openChatSelectorModal error:", e);
        if (container) container.innerHTML = `<div style="color: #f87171; padding: 10px;">চ্যাট লোড করা যায়নি</div>`;
    }
}

function renderMuteChatSelectorList(convs) {
    const container = document.getElementById("chat-selector-list-container");
    if (!container) return;

    if (!convs || convs.length === 0) {
        container.innerHTML = `<div style="text-align: center; color: var(--text-dim); padding: 20px;">কোনো সক্রিয় চ্যাট পাওয়া যায়নি।</div>`;
        return;
    }

    const currentMutedNumbers = cachedMutedContacts.map(c => c.phone);

    container.innerHTML = convs.map(c => {
        const sender = c.sender_id || "";
        const isChecked = currentMutedNumbers.some(m => sender.includes(m) || m.includes(sender));
        const channelIcon = c.channel === "whatsapp" ? "fab fa-whatsapp" : "fab fa-facebook-messenger";
        const channelColor = c.channel === "whatsapp" ? "#25d366" : "#0084ff";

        return `
            <label style="display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 6px; background: rgba(255,255,255,0.03); cursor: pointer; border: 1px solid rgba(255,255,255,0.06);">
                <input type="checkbox" class="mute-chat-checkbox" value="${sender}" ${isChecked ? 'checked' : ''} style="width: 16px; height: 16px; accent-color: #ef4444;">
                <div style="flex: 1;">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <i class="${channelIcon}" style="color: ${channelColor};"></i>
                        <strong style="font-size: 13px; color: #fff;">${c.customer_name || 'Customer'}</strong>
                    </div>
                    <span style="font-size: 11.5px; color: var(--text-muted);">${c.sender_id || ''}</span>
                </div>
                ${isChecked ? '<span class="badge" style="background: rgba(239,68,68,0.2); color: #f87171; font-size: 10px;">Muted</span>' : ''}
            </label>
        `;
    }).join('');
}

function filterMuteChatSelectorList() {
    const search = document.getElementById("chat-selector-search-input")?.value.toLowerCase() || "";
    const filtered = cachedConversationsForMute.filter(c => 
        (c.customer_name && c.customer_name.toLowerCase().includes(search)) ||
        (c.sender_id && c.sender_id.toLowerCase().includes(search))
    );
    renderMuteChatSelectorList(filtered);
}

async function confirmChatSelectorMute() {
    const checkboxes = document.querySelectorAll(".mute-chat-checkbox");
    const currentMutedNumbers = cachedMutedContacts.map(c => c.phone);
    let addedCount = 0;
    let removedCount = 0;

    for (const cb of checkboxes) {
        const val = cb.value.trim();
        if (!val) continue;

        if (cb.checked) {
            await fetch("/api/muted-contacts/add", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ phone: val })
            });
            addedCount++;
        } else {
            // If it was previously muted and now unchecked, unblock it
            const isCurrentlyMuted = currentMutedNumbers.some(m => val.includes(m) || m.includes(val));
            if (isCurrentlyMuted) {
                await fetch("/api/muted-contacts/remove", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ phone: val })
                });
                removedCount++;
            }
        }
    }

    await loadMutedContacts();
    closeModal("modal-select-chats-to-mute");
    showToast(`✅ কন্টাক্ট ব্লক লিস্ট সফলভাবে আপডেট হয়েছে!`, "success");
}

async function saveAllSettings() {
    // Automatically add any number typed in the manual mute input before saving
    const manualMuteEl = document.getElementById("manual-mute-phone-input");
    if (manualMuteEl && manualMuteEl.value.trim()) {
        await handleManualAddMute();
    }

    const getVal = (id) => {
        const el = document.getElementById(id);
        return el ? el.value.trim() : "";
    };

    const shopName = getVal("setting-shop-name") || getVal("arena-shop-name") || "RS Graphics (আরএস গ্রাফিক্স)";
    const shopPhone = getVal("setting-shop-phone") || "01816504097";

    const getChecked = (id) => {
        const el = document.getElementById(id);
        return el ? (el.checked ? "true" : "false") : "true";
    };

    const payload = {
        shop_name: shopName,
        shop_phone: shopPhone,
        delivery_inside_dhaka: getVal("setting-delivery-inside") || "70",
        delivery_outside_dhaka: getVal("setting-delivery-outside") || "130",
        blacklisted_ai_numbers: getVal("setting-blacklisted-numbers"),
        comment_auto_reply: getChecked("setting-auto-comment"),
        private_message_on_comment: getChecked("setting-private-inbox"),
        comment_ai_mode: getVal("setting-comment-ai-mode") || "ai_smart",
        comment_reply_template: getVal("setting-comment-reply-template") || "ধন্যবাদ {name} স্যার/ম্যাম! বিস্তারিত তথ্য ও ছবি আপনার ইনবক্সে পাঠানো হয়েছে 🥰"
    };

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("✅ সেটিংস সফলভাবে সেভ হয়েছে!", "success");
            const aName = document.getElementById("arena-shop-name");
            if (aName) aName.value = shopName;
            const pName = document.getElementById("phone-header-shop-name");
            if (pName) pName.innerText = shopName;
            await loadMutedContacts();
        } else {
            showToast("সেটিংস সেভ করতে সমস্যা হয়েছে", "danger");
        }
    } catch (e) {
        console.error("saveAllSettings error:", e);
        showToast("সার্ভার এরর", "danger");
    }
}

async function saveArenaSettings() {
    const getVal = (id) => {
        const el = document.getElementById(id);
        return el ? el.value.trim() : "";
    };

    const shopName = getVal("arena-shop-name") || getVal("setting-shop-name") || "RS Graphics (আরএস গ্রাফিক্স)";
    const prompt = getVal("arena-system-prompt");
    const geminiKey = getVal("arena-gemini-key");

    const payload = {
        shop_name: shopName
    };
    if (prompt) payload.ai_system_prompt = prompt;
    if (geminiKey) payload.gemini_api_key = geminiKey;

    try {
        const res = await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("✅ AI ব্রেইন ও শপের নাম সফলভাবে সংরক্ষিত হয়েছে!", "success");
            const sName = document.getElementById("setting-shop-name");
            if (sName) sName.value = shopName;
            const pName = document.getElementById("phone-header-shop-name");
            if (pName) pName.innerText = shopName;
        } else {
            showToast("সংরক্ষণ করতে সমস্যা হয়েছে", "danger");
        }
    } catch (e) {
        console.error("saveArenaSettings error:", e);
        showToast("সার্ভার এরর", "danger");
    }
}

// Direct WhatsApp Business App Opener (Explicitly targets com.whatsapp.w4b)
function openWhatsAppBusinessApp(phone = "") {
    if (window.AndroidBridge && typeof window.AndroidBridge.openWhatsAppBusiness === "function") {
        window.AndroidBridge.openWhatsAppBusiness(phone);
        return;
    }
    const clean = phone.replace("+", "").replace(/\s+/g, "").replace(/-/g, "");
    if (/Android/i.test(navigator.userAgent)) {
        // Android intent specifically for WhatsApp Business
        if (clean) {
            window.location.href = `intent://send?phone=${clean}#Intent;package=com.whatsapp.w4b;scheme=whatsapp;end`;
        } else {
            window.location.href = `intent:#Intent;package=com.whatsapp.w4b;end`;
        }
    } else {
        if (clean) {
            window.open(`https://api.whatsapp.com/send?phone=${clean}`, "_blank");
        } else {
            window.open("https://web.whatsapp.com", "_blank");
        }
    }
}

// Direct WhatsApp Personal App Opener (Explicitly targets com.whatsapp)
function openWhatsAppAppDirectly(phone = "") {
    if (window.AndroidBridge && typeof window.AndroidBridge.openWhatsApp === "function") {
        window.AndroidBridge.openWhatsApp(phone);
        return;
    }
    const clean = phone.replace("+", "").replace(/\s+/g, "").replace(/-/g, "");
    if (/Android/i.test(navigator.userAgent)) {
        if (clean) {
            window.location.href = `intent://send?phone=${clean}#Intent;package=com.whatsapp;scheme=whatsapp;end`;
        } else {
            window.location.href = `intent:#Intent;package=com.whatsapp;end`;
        }
    } else {
        if (clean) {
            window.open(`https://api.whatsapp.com/send?phone=${clean}`, "_blank");
        } else {
            window.open("https://web.whatsapp.com", "_blank");
        }
    }
}

// ==========================================
// MULTI-PAGE & MULTI-WHATSAPP MANAGEMENT
// ==========================================
let globalConnectedPages = [];

async function loadConnectedPages() {
    const container = document.getElementById("connected-pages-list");
    if (!container) return;

    try {
        const res = await fetch("/api/pages");
        const data = await res.json();
        if (data.success) {
            globalConnectedPages = data.pages || [];
            renderConnectedPages(globalConnectedPages);
            populateOmnichatPageFilter(globalConnectedPages);
        }
    } catch (e) {
        console.error("Load connected pages error:", e);
    }
}

function renderConnectedPages(pages) {
    const container = document.getElementById("connected-pages-list");
    if (!container) return;

    if (!pages || pages.length === 0) {
        container.innerHTML = `
            <div style="text-align: center; padding: 25px; color: var(--text-muted); background: rgba(0,0,0,0.2); border-radius: 10px;">
                <i class="fab fa-facebook" style="font-size: 32px; opacity: 0.3; margin-bottom: 8px; display: block;"></i>
                No connected pages found. Click "+ Connect Another Facebook Page" to add Page 1 or Page 2.
            </div>
        `;
        return;
    }

    container.innerHTML = "";
    pages.forEach((p, idx) => {
        const card = document.createElement("div");
        card.style.cssText = "background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px;";

        const hasWA = p.whatsapp && p.whatsapp.phone_number_id;
        const waNumber = hasWA ? (p.whatsapp.display_phone_number || p.whatsapp.phone_number_id) : 'Not Linked';

        card.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="width: 36px; height: 36px; border-radius: 8px; background: rgba(24, 119, 242, 0.15); display: flex; align-items: center; justify-content: center; color: #60a5fa; font-size: 18px;">
                        <i class="fab fa-facebook-messenger"></i>
                    </div>
                    <div>
                        <div style="display: flex; align-items: center; gap: 6px;">
                            <strong style="color: #fff; font-size: 14px;">${p.page_name || 'Facebook Page'}</strong>
                            ${idx === 0 ? '<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399; font-size: 9.5px;">Primary Page 1</span>' : '<span class="badge" style="background: rgba(99, 102, 241, 0.2); color: #818cf8; font-size: 9.5px;">Page ' + (idx + 1) + '</span>'}
                        </div>
                        <small style="color: var(--text-muted); font-size: 11px;">Page ID: ${p.page_id} | Shop: ${p.shop_name || 'RS Graphics'}</small>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span class="badge badge-confirmed" style="font-size: 10px;"><i class="fas fa-check-circle"></i> Messenger Connected</span>
                    <span class="badge badge-confirmed" style="font-size: 10px;"><i class="fas fa-comments"></i> Auto Comments</span>
                </div>
            </div>

            <!-- Page Details & WhatsApp Status Row -->
            <div style="background: rgba(0,0,0,0.25); border-radius: 8px; padding: 10px 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; font-size: 12px;">
                <div>
                    <span style="color: var(--text-muted); display: block; font-size: 10.5px;">Linked WhatsApp Business</span>
                    <strong style="color: ${hasWA ? '#34d399' : 'var(--text-dim)'};">
                        <i class="fab fa-whatsapp" style="color: #25d366;"></i> ${waNumber}
                    </strong>
                </div>
                <div>
                    <span style="color: var(--text-muted); display: block; font-size: 10.5px;">Delivery Charges</span>
                    <strong style="color: #e2e8f0;">৳${p.delivery_inside_dhaka || 70} (Inside) / ৳${p.delivery_outside_dhaka || 130} (Outside)</strong>
                </div>
                <div>
                    <span style="color: var(--text-muted); display: block; font-size: 10.5px;">AI Custom Persona</span>
                    <strong style="color: ${p.ai_system_prompt ? '#a78bfa' : '#64748b'};">
                        ${p.ai_system_prompt ? 'Custom Prompt Active' : 'Default RS AI Brain'}
                    </strong>
                </div>
            </div>

            <!-- Actions Bar -->
            <div style="display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap;">
                <button class="btn btn-secondary" style="font-size: 11px; padding: 5px 10px;" onclick="openPageWhatsAppModal('${p.page_id}')">
                    <i class="fab fa-whatsapp" style="color: #25d366;"></i> ${hasWA ? 'Manage WhatsApp' : 'Link WhatsApp'}
                </button>
                <button class="btn btn-secondary" style="font-size: 11px; padding: 5px 10px;" onclick="openManagePageModal('${p.page_id}')">
                    <i class="fas fa-sliders-h" style="color: var(--primary-light);"></i> Manage Store & AI
                </button>
                ${idx !== 0 ? `
                    <button class="btn btn-secondary" style="font-size: 11px; padding: 5px 10px; color: #ef4444;" onclick="disconnectPageDirectly('${p.page_id}')">
                        <i class="fas fa-trash-alt"></i> Disconnect
                    </button>
                ` : ''}
            </div>
        `;
        container.appendChild(card);
    });
}

function populateOmnichatPageFilter(pages) {
    const select = document.getElementById("omnichat-page-filter");
    if (!select) return;

    const currentVal = select.value;
    select.innerHTML = '<option value="">All Pages & WA</option>';

    pages.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.page_id;
        opt.innerText = p.page_name || p.shop_name || `Page (${p.page_id})`;
        select.appendChild(opt);
    });

    if (currentVal) select.value = currentVal;
}

function openConnectPageModal() {
    document.getElementById("form-connect-page")?.reset();
    openModal("modal-connect-page");
}

async function handleConnectPageSubmit(e) {
    e.preventDefault();
    const pageId = document.getElementById("new-page-id")?.value.trim();
    const pageName = document.getElementById("new-page-name")?.value.trim();
    const phone = document.getElementById("new-page-phone")?.value.trim();
    const token = document.getElementById("new-page-token")?.value.trim();
    const waPhoneId = document.getElementById("new-page-wa-phone-id")?.value.trim();
    const waDisplayPhone = document.getElementById("new-page-wa-display-phone")?.value.trim();
    const waWabaId = document.getElementById("new-page-wa-waba-id")?.value.trim();

    if (!pageId || !token) {
        showToast("Page ID and Access Token are required", "danger");
        return;
    }

    try {
        showToast("Connecting Facebook Page...", "info");
        const res = await fetch("/api/pages/connect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                page_id: pageId,
                page_name: pageName,
                shop_name: pageName,
                shop_phone: phone,
                page_access_token: token,
                whatsapp_phone_number_id: waPhoneId,
                whatsapp_display_phone_number: waDisplayPhone,
                whatsapp_waba_id: waWabaId
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast(data.message || "Page connected successfully!", "success");
            closeModal("modal-connect-page");
            loadConnectedPages();
            loadOmnichatConversations();
        } else {
            showToast(data.error || "Failed to connect page", "danger");
        }
    } catch (e) {
        showToast("Connection error: Server failure", "danger");
    }
}

let activeManagingPageId = null;

function openManagePageModal(pageId) {
    const p = globalConnectedPages.find(x => x.page_id === String(pageId));
    if (!p) return;

    activeManagingPageId = pageId;
    document.getElementById("edit-page-id").value = p.page_id;
    document.getElementById("edit-page-name").value = p.page_name || p.shop_name || '';
    document.getElementById("edit-page-phone").value = p.shop_phone || '';
    document.getElementById("edit-page-delivery-inside").value = p.delivery_inside_dhaka || 70;
    document.getElementById("edit-page-delivery-outside").value = p.delivery_outside_dhaka || 130;
    document.getElementById("edit-page-prompt").value = p.ai_system_prompt || '';
    document.getElementById("edit-page-token").value = '';

    openModal("modal-manage-page");
}

async function handleManagePageSubmit(e) {
    e.preventDefault();
    const pageId = document.getElementById("edit-page-id")?.value;
    const pageName = document.getElementById("edit-page-name")?.value.trim();
    const phone = document.getElementById("edit-page-phone")?.value.trim();
    const inside = document.getElementById("edit-page-delivery-inside")?.value;
    const outside = document.getElementById("edit-page-delivery-outside")?.value;
    const prompt = document.getElementById("edit-page-prompt")?.value.trim();
    const token = document.getElementById("edit-page-token")?.value.trim();

    if (!pageId) return;

    const payload = {
        page_name: pageName,
        shop_name: pageName,
        shop_phone: phone,
        delivery_inside_dhaka: parseInt(inside) || 70,
        delivery_outside_dhaka: parseInt(outside) || 130,
        ai_system_prompt: prompt
    };
    if (token) payload.page_access_token = token;

    try {
        const res = await fetch(`/api/pages/${pageId}/edit`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("পেইজের সেটিংস সফলভাবে আপডেট হয়েছে!", "success");
            closeModal("modal-manage-page");
            loadConnectedPages();
        } else {
            showToast(data.error || "Update failed", "danger");
        }
    } catch (e) {
        showToast("Update error", "danger");
    }
}

async function confirmDisconnectCurrentPage() {
    if (!activeManagingPageId) return;
    if (!confirm("আপনি কি নিশ্চিত এই ফেসবুক পেইজের কানেকশন বিচ্ছিন্ন করতে চান?")) return;

    try {
        const res = await fetch(`/api/pages/${activeManagingPageId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("পেইজ ডিসকানেক্ট করা হয়েছে", "success");
            closeModal("modal-manage-page");
            loadConnectedPages();
            loadOmnichatConversations();
        } else {
            showToast(data.error || "Disconnect failed", "danger");
        }
    } catch (e) {
        showToast("Disconnect error", "danger");
    }
}

async function disconnectPageDirectly(pageId) {
    if (!confirm("আপনি কি নিশ্চিত এই ফেসবুক পেইজের কানেকশন বিচ্ছিন্ন করতে চান?")) return;

    try {
        const res = await fetch(`/api/pages/${pageId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("পেইজ ডিসকানেক্ট করা হয়েছে", "success");
            loadConnectedPages();
            loadOmnichatConversations();
        } else {
            showToast(data.error || "Disconnect failed", "danger");
        }
    } catch (e) {
        showToast("Disconnect error", "danger");
    }
}

function openPageWhatsAppModal(pageId) {
    const p = globalConnectedPages.find(x => x.page_id === String(pageId));
    if (!p) return;

    document.getElementById("wa-modal-page-id").value = pageId;
    const wa = p.whatsapp || {};
    document.getElementById("wa-modal-display-phone").value = wa.display_phone_number || '';
    document.getElementById("wa-modal-phone-id").value = wa.phone_number_id || '';
    document.getElementById("wa-modal-waba-id").value = wa.waba_id || '';
    document.getElementById("wa-modal-access-token").value = '';

    openModal("modal-page-whatsapp");
}

async function handlePageWhatsAppSubmit(e) {
    e.preventDefault();
    const pageId = document.getElementById("wa-modal-page-id")?.value;
    const displayPhone = document.getElementById("wa-modal-display-phone")?.value.trim();
    const phoneId = document.getElementById("wa-modal-phone-id")?.value.trim();
    const wabaId = document.getElementById("wa-modal-waba-id")?.value.trim();
    const token = document.getElementById("wa-modal-access-token")?.value.trim();

    if (!pageId || !phoneId) {
        showToast("Phone Number ID is required", "danger");
        return;
    }

    try {
        const res = await fetch(`/api/pages/${pageId}/whatsapp/connect`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                phone_number_id: phoneId,
                display_phone_number: displayPhone,
                waba_id: wabaId,
                access_token: token
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("হোয়াটসঅ্যাপ অ্যাকাউন্ট সফলভাবে পেইজের সাথে যুক্ত হয়েছে!", "success");
            closeModal("modal-page-whatsapp");
            loadConnectedPages();
        } else {
            showToast(data.error || "Failed to link WhatsApp", "danger");
        }
    } catch (e) {
        showToast("Server error", "danger");
    }
}

async function disconnectPageWhatsAppAction() {
    const pageId = document.getElementById("wa-modal-page-id")?.value;
    if (!pageId) return;
    if (!confirm("আপনি কি নিশ্চিত এই পেইজের হোয়াটসঅ্যাপ অ্যাকাউন্ট ডিসকানেক্ট করতে চান?")) return;

    try {
        const res = await fetch(`/api/pages/${pageId}/whatsapp/disconnect`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast("হোয়াটসঅ্যাপ ডিসকানেক্ট করা হয়েছে", "success");
            closeModal("modal-page-whatsapp");
            loadConnectedPages();
        }
    } catch (e) {
        showToast("Server error", "danger");
    }
}
// =========================================================
// GOOGLE FORMS & ID CARD AUTOMATION FRONTEND LOGIC
// =========================================================
let currentOpenSubmissionsFormId = null;

async function loadGoogleFormsTab() {
    try {
        await Promise.all([
            loadGoogleAccountStatus(),
            loadFormFieldsList(),
            loadGeneratedFormsList()
        ]);
    } catch (e) {
        console.error("loadGoogleFormsTab error:", e);
    }
}

async function loadGoogleAccountStatus() {
    try {
        const res = await fetch(`/api/google/status?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        
        const connBadge = document.getElementById("gforms-conn-badge");
        const connMsg = document.getElementById("gforms-conn-msg");
        const emailEl = document.getElementById("gforms-conn-email");
        const driveStatus = document.getElementById("gforms-drive-status");
        const formsStatus = document.getElementById("gforms-forms-status");
        const sheetsStatus = document.getElementById("gforms-sheets-status");
        const btnConnect = document.getElementById("btn-connect-google");
        const btnDisconnect = document.getElementById("btn-disconnect-google");

        const masterBadge = document.getElementById("gforms-master-badge");
        const masterMsg = document.getElementById("gforms-master-msg");
        const masterMetaGrid = document.getElementById("master-form-meta-grid");

        // 1. Connection Status Card
        if (data.connected) {
            if (connBadge) {
                connBadge.className = "badge";
                connBadge.style.background = "rgba(16, 185, 129, 0.2)";
                connBadge.style.color = "#34d399";
                connBadge.style.border = "1px solid rgba(16, 185, 129, 0.3)";
                connBadge.innerText = "Connected";
            }
            if (connMsg) {
                connMsg.innerText = "Google Account is connected.";
                connMsg.style.color = "#34d399";
            }
            if (emailEl) emailEl.innerText = data.masked_email || data.google_account_email || "Connected";
            if (driveStatus) driveStatus.innerHTML = `<i class="fas fa-check-circle" style="color: #34d399;"></i> Drive API: Ready`;
            if (formsStatus) formsStatus.innerHTML = `<i class="fas fa-check-circle" style="color: #34d399;"></i> Forms API: Ready`;
            if (sheetsStatus) sheetsStatus.innerHTML = `<i class="fas fa-check-circle" style="color: #34d399;"></i> Sheets API: Ready`;
            if (btnConnect) btnConnect.innerHTML = `<i class="fas fa-rotate"></i> Re-Authenticate`;
            if (btnDisconnect) btnDisconnect.style.display = "inline-flex";
        } else {
            if (connBadge) {
                connBadge.className = "badge";
                connBadge.style.background = "rgba(239, 68, 68, 0.2)";
                connBadge.style.color = "#f87171";
                connBadge.style.border = "1px solid rgba(239, 68, 68, 0.3)";
                connBadge.innerText = "Not Connected";
            }
            if (connMsg) {
                connMsg.innerText = "Google Account is not connected.";
                connMsg.style.color = "#f87171";
            }
            if (emailEl) emailEl.innerText = "None";
            if (driveStatus) driveStatus.innerHTML = `<i class="fas fa-circle-notch" style="color: var(--text-dim);"></i> Drive API: Pending`;
            if (formsStatus) formsStatus.innerHTML = `<i class="fas fa-circle-notch" style="color: var(--text-dim);"></i> Forms API: Pending`;
            if (sheetsStatus) sheetsStatus.innerHTML = `<i class="fas fa-circle-notch" style="color: var(--text-dim);"></i> Sheets API: Pending`;
            if (btnConnect) btnConnect.innerHTML = `<i class="fab fa-google"></i> Connect Google Account`;
            if (btnDisconnect) btnDisconnect.style.display = "none";
        }

        // 2. Master Form Card & Meta Grid
        if (data.master_status === "configured" && data.master_form_id) {
            if (masterBadge) {
                masterBadge.className = "badge";
                masterBadge.style.background = "rgba(16, 185, 129, 0.2)";
                masterBadge.style.color = "#34d399";
                masterBadge.style.border = "1px solid rgba(16, 185, 129, 0.3)";
                masterBadge.innerText = "Connected & Verified";
            }
            if (masterMsg) {
                masterMsg.innerText = "Master Form is configured and active.";
                masterMsg.style.color = "#34d399";
            }
            if (masterMetaGrid) masterMetaGrid.style.display = "block";

            const nameEl = document.getElementById("master-display-name");
            if (nameEl) nameEl.innerText = data.master_form_name || "ID Card Information Form";

            const idEl = document.getElementById("master-display-id");
            if (idEl) idEl.innerText = data.master_form_id;

            const urlEl = document.getElementById("master-display-url");
            if (urlEl && data.master_form_url) {
                urlEl.href = data.master_form_url;
                urlEl.dataset.url = data.master_form_url;
            }

            const editEl = document.getElementById("master-display-edit-url");
            if (editEl && data.master_edit_url) {
                editEl.href = data.master_edit_url;
            }

            const sheetEl = document.getElementById("master-display-sheet-url");
            if (sheetEl && data.master_sheet_url) {
                sheetEl.href = data.master_sheet_url;
            }

            const uploadBadge = document.getElementById("master-display-upload-badge");
            if (uploadBadge) {
                if (data.master_has_file_upload) {
                    uploadBadge.className = "badge";
                    uploadBadge.style.background = "rgba(16, 185, 129, 0.2)";
                    uploadBadge.style.color = "#34d399";
                    uploadBadge.style.border = "1px solid rgba(16, 185, 129, 0.3)";
                    uploadBadge.innerText = "Verified ✓ (Drive File Upload)";
                } else {
                    uploadBadge.className = "badge";
                    uploadBadge.style.background = "rgba(234, 179, 8, 0.2)";
                    uploadBadge.style.color = "#facc15";
                    uploadBadge.style.border = "1px solid rgba(234, 179, 8, 0.3)";
                    uploadBadge.innerText = "Edit mode-এ File Upload প্রশ্ন যোগ করুন ⚠️";
                }
            }
        } else {
            if (masterBadge) {
                masterBadge.className = "badge";
                masterBadge.style.background = "rgba(239, 68, 68, 0.2)";
                masterBadge.style.color = "#f87171";
                masterBadge.style.border = "1px solid rgba(239, 68, 68, 0.3)";
                masterBadge.innerText = "Not Configured";
            }
            if (masterMsg) {
                masterMsg.innerText = "Master Form is not configured.";
                masterMsg.style.color = "#f87171";
            }
            if (masterMetaGrid) masterMetaGrid.style.display = "none";
        }
    } catch (e) {
        console.error("loadGoogleAccountStatus error:", e);
    }
}

async function startGoogleOAuthConnect() {
    try {
        const currentOrigin = window.location.origin;
        const redirectUri = `${currentOrigin}/api/google/auth/callback`;
        const res = await fetch(`/api/google/auth/start?workspace_id=${currentWorkspaceId}&redirect_uri=${encodeURIComponent(redirectUri)}`);
        const data = await res.json();
        if (data.success && data.auth_url) {
            window.location.href = data.auth_url;
        } else {
            showToast(data.error || data.detail || "Failed to initiate Google OAuth", "danger");
        }
    } catch (e) {
        showToast("OAuth network error", "danger");
    }
}

async function openGoogleCredentialsModal() {
    try {
        const redirectEl = document.getElementById("gcred-redirect-uri");
        const clientIdEl = document.getElementById("gcred-client-id");
        const clientSecretEl = document.getElementById("gcred-client-secret");
        const emailEl = document.getElementById("gcred-account-email");
        const refreshEl = document.getElementById("gcred-refresh-token");

        // Set dynamic redirect URI based on current origin
        const currentOrigin = window.location.origin;
        if (redirectEl) redirectEl.value = `${currentOrigin}/api/google/auth/callback`;

        const res = await fetch(`/api/google/credentials?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        if (data.success) {
            if (clientIdEl && data.client_id) clientIdEl.value = data.client_id;
            if (clientSecretEl && data.has_client_secret) clientSecretEl.placeholder = "•••••••••••••••• (Configured)";
            if (emailEl && data.account_email) emailEl.value = data.account_email;
            if (refreshEl && data.has_refresh_token) refreshEl.placeholder = "•••••••••••••••• (Configured & Saved)";
        }
        openModal("modal-google-credentials");
    } catch (e) {
        console.error("openGoogleCredentialsModal error:", e);
        openModal("modal-google-credentials");
    }
}

function copyGoogleRedirectUri() {
    const redirectEl = document.getElementById("gcred-redirect-uri");
    if (redirectEl && redirectEl.value) {
        navigator.clipboard.writeText(redirectEl.value);
        showToast("Redirect URI কপি করা হয়েছে!", "success");
    }
}

async function handleSaveGoogleCredentials(e) {
    e.preventDefault();
    const clientId = (document.getElementById("gcred-client-id")?.value || "").trim();
    const clientSecret = (document.getElementById("gcred-client-secret")?.value || "").trim();
    const accountEmail = (document.getElementById("gcred-account-email")?.value || "").trim();
    const refreshToken = (document.getElementById("gcred-refresh-token")?.value || "").trim();
    const redirectUri = (document.getElementById("gcred-redirect-uri")?.value || "").trim();

    try {
        const payload = {
            workspace_id: currentWorkspaceId,
            redirect_uri: redirectUri
        };
        if (clientId) payload.client_id = clientId;
        if (clientSecret) payload.client_secret = clientSecret;
        if (accountEmail) payload.account_email = accountEmail;
        if (refreshToken) payload.refresh_token = refreshToken;

        const res = await fetch("/api/google/credentials", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast("Google credentials সফলভাবে সেভ হয়েছে!", "success");
            closeModal("modal-google-credentials");
            loadGoogleAccountStatus();
        } else {
            showToast(data.detail || data.error || "ক্রেডেনশিয়াল সেভ করতে ব্যর্থ হয়েছে", "danger");
        }
    } catch (err) {
        showToast("Network error saving Google credentials", "danger");
    }
}

async function disconnectGoogleAccount() {
    if (!confirm("আপনি কি নিশ্চিত এই ওয়ার্কস্পেসের Google Account ডিসকানেক্ট করতে চান?")) return;
    try {
        const res = await fetch("/api/google/disconnect", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workspace_id: currentWorkspaceId })
        });
        const data = await res.json();
        if (data.success) {
            showToast("Google account disconnected.", "success");
            loadGoogleAccountStatus();
        }
    } catch (e) {
        showToast("Disconnect error", "danger");
    }
}

async function openSelectMasterFormModal() {
    const selectEl = document.getElementById("select-drive-master-form");
    const manualInput = document.getElementById("manual-master-form-id");
    
    if (selectEl) {
        selectEl.innerHTML = `<option value="">-- গুগল ড্রাইভ থেকে ফর্ম খোঁজা হচ্ছে... --</option>`;
    }
    
    openModal("modal-select-master-form");

    try {
        const res = await fetch(`/api/google/master-forms?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        if (selectEl) {
            if (data.success && data.forms && data.forms.length > 0) {
                selectEl.innerHTML = `<option value="">-- ড্রাইভের ফর্ম নির্বাচন করুন (${data.forms.length}টি পাওয়া গেছে) --</option>` +
                    data.forms.map(f => `<option value="${f.id}">${f.name} (${f.id})</option>`).join("");
            } else {
                selectEl.innerHTML = `<option value="">কোনো Google Form পাওয়া যায়নি (সরাসরি ফর্ম আইডি দিন)</option>`;
            }
        }
    } catch (err) {
        if (selectEl) selectEl.innerHTML = `<option value="">ড্রাইভের ফর্ম লোড করা যায়নি (সরাসরি আইডি দিন)</option>`;
    }
}

function onDriveMasterFormSelected(formId) {
    const manualInput = document.getElementById("manual-master-form-id");
    if (manualInput && formId) {
        manualInput.value = formId;
    }
}

async function handleSelectMasterFormSubmit(e) {
    e.preventDefault();
    const formId = document.getElementById("manual-master-form-id")?.value?.trim();
    if (!formId) {
        showToast("দয়া করে Master Google Form ID দিন", "warning");
        return;
    }

    showToast("Master Form যাচাই করা হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন", "info");

    try {
        const res = await fetch("/api/google/master-forms/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: currentWorkspaceId,
                master_form_id: formId
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(data.message || `Master Form '${data.master_form_name}' সফলভাবে যুক্ত হয়েছে!`, "success");
            closeModal("modal-select-master-form");
            loadGoogleAccountStatus();
        } else {
            showToast(data.detail || "Master Form যাচাই ব্যর্থ হয়েছে। ফর্ম আইডি এবং এক্সেস চেক করুন।", "danger");
        }
    } catch (e) {
        showToast("Server error verifying Master Form", "danger");
    }
}

function openCreateMasterFormModal() {
    document.getElementById("form-create-master-form")?.reset();
    openModal("modal-create-master-form");
}

async function handleCreateMasterTemplateSubmit(e) {
    e.preventDefault();
    const title = document.getElementById("new-master-title")?.value?.trim() || "ID Card Information Form";
    const desc = document.getElementById("new-master-desc")?.value?.trim();

    showToast("ড্রাইভে মাস্টার ফর্ম ও রেসপন্স শিট তৈরি হচ্ছে...", "info");

    try {
        const res = await fetch("/api/google/master-forms/create-template", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: currentWorkspaceId,
                title: title,
                description: desc
            })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast(`Master Form '${title}' সফলভাবে তৈরি হয়েছে!`, "success");
            closeModal("modal-create-master-form");
            loadGoogleAccountStatus();
            
            if (data.edit_url) {
                // Open edit URL so user can see and configure file upload question in forms UI
                window.open(data.edit_url, "_blank");
            }
        } else {
            showToast(data.detail || "মাস্টার ফর্ম তৈরিতে সমস্যা হয়েছে। গুগল একাউন্ট কানেকশন চেক করুন।", "danger");
        }
    } catch (err) {
        showToast("Network error creating master form template", "danger");
    }
}

async function verifyCurrentMasterForm() {
    const idEl = document.getElementById("master-display-id");
    const formId = idEl ? idEl.innerText.trim() : "";
    if (!formId || formId === "-") {
        showToast("কোনো Master Form কনফিগার করা নেই। আগে Master Form নির্বাচন বা তৈরি করুন।", "warning");
        return;
    }

    showToast("Master Form লাইভ যাচাই করা হচ্ছে...", "info");

    try {
        const res = await fetch("/api/google/master-forms/verify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: currentWorkspaceId,
                master_form_id: formId
            })
        });
        const data = await res.json();
        if (res.ok && data.valid) {
            showToast(`✓ Master Form '${data.form_name}' যাচাই সফল! (প্রশ্ন সংখ্যা: ${data.items_count})`, "success");
            loadGoogleAccountStatus();
        } else {
            showToast(data.detail || "Master Form যাচাই ব্যর্থ হয়েছে।", "danger");
        }
    } catch (err) {
        showToast("Verification request failed", "danger");
    }
}

function copyMasterFormUrl() {
    const urlEl = document.getElementById("master-display-url");
    const url = urlEl ? (urlEl.dataset.url || urlEl.href) : "";
    if (url && url !== "#") {
        copyTextToClipboard(url);
    } else {
        showToast("কোনো ফর্ম লিংক পাওয়া যায়নি", "warning");
    }
}

function toggleFieldsManager() {
    const body = document.getElementById("fields-manager-body");
    const icon = document.getElementById("fields-toggle-icon");
    if (!body) return;

    if (body.style.display === "none" || !body.style.display) {
        body.style.display = "block";
        if (icon) icon.style.transform = "rotate(180deg)";
    } else {
        body.style.display = "none";
        if (icon) icon.style.transform = "rotate(0deg)";
    }
}

async function loadFormFieldsList() {
    try {
        const res = await fetch(`/api/google/fields?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        const tbody = document.getElementById("gforms-fields-tbody");
        if (!tbody) return;

        if (!data.fields || data.fields.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-dim); padding: 15px;">কোনো ফিল্ড কনফিগার করা নেই। ডিফল্ট ফিল্ড লোড হবে।</td></tr>`;
            return;
        }

        tbody.innerHTML = data.fields.map(f => {
            const isFile = f.field_type === "file_upload";
            const reqBadge = f.required 
                ? `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #34d399; font-size: 11px;">Yes</span>` 
                : `<span class="badge" style="background: rgba(255,255,255,0.06); color: var(--text-dim); font-size: 11px;">No</span>`;
            
            return `
                <tr>
                    <td><strong style="color: #fff;">${f.field_label}</strong> <span style="font-size: 11px; color: var(--text-dim);">(${f.field_key})</span></td>
                    <td><span style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-size: 11px;">${f.field_type}</span></td>
                    <td>${reqBadge}</td>
                    <td>${f.sort_order}</td>
                    <td>
                        ${isFile ? `<span style="font-size: 11px; color: var(--text-dim);">Master Form</span>` : `
                        <button class="btn btn-danger btn-sm" style="padding: 3px 7px; font-size: 11px;" onclick="deleteFormField(${f.id})" title="মুছুন">
                            <i class="fas fa-trash"></i>
                        </button>`}
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("loadFormFieldsList error:", e);
    }
}

function openAddFieldModal() {
    document.getElementById("form-add-field")?.reset();
    openModal("modal-add-form-field");
}

async function handleAddFieldSubmit(e) {
    e.preventDefault();
    const label = document.getElementById("new-field-label")?.value?.trim();
    let key = document.getElementById("new-field-key")?.value?.trim();
    const ftype = document.getElementById("new-field-type")?.value || "short_answer";
    const req = parseInt(document.getElementById("new-field-required")?.value || "1");

    if (!label) {
        showToast("ফিল্ডের নাম দিন", "warning");
        return;
    }
    if (!key) {
        key = label.toLowerCase().replace(/[^a-z0-9]/g, "_").slice(0, 30);
    }

    try {
        const res = await fetch("/api/google/fields", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: currentWorkspaceId,
                field_key: key,
                field_label: label,
                field_type: ftype,
                required: req,
                sort_order: 10
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("ফিল্ড সফলভাবে যুক্ত হয়েছে!", "success");
            closeModal("modal-add-form-field");
            loadFormFieldsList();
        }
    } catch (err) {
        showToast("Error adding field", "danger");
    }
}

async function deleteFormField(fieldId) {
    if (!confirm("আপনি কি নিশ্চিত এই ফিল্ডটি মুছে ফেলতে চান?")) return;
    try {
        const res = await fetch(`/api/google/fields/${fieldId}?workspace_id=${currentWorkspaceId}`, { method: "DELETE" });
        const data = await res.json();
        if (data.success) {
            showToast("ফিল্ড মুছে ফেলা হয়েছে", "success");
            loadFormFieldsList();
        }
    } catch (e) {
        showToast("Delete error", "danger");
    }
}

let allGeneratedFormsCache = [];

function renderGeneratedFormsRows(forms) {
    const tbody = document.getElementById("gforms-table-tbody");
    if (!tbody) return;

    if (!forms || forms.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 25px;">কোনো প্রতিষ্ঠানের ফর্ম পাওয়া যায়নি।</td></tr>`;
        return;
    }

    tbody.innerHTML = forms.map(f => {
        const formUrl = f.responder_uri || f.form_url;
        const sheetUrl = f.response_sheet_url || (f.response_destination_id ? `https://docs.google.com/spreadsheets/d/${f.response_destination_id}/edit` : "");
        const mobile = f.institution_mobile || f.institution_phone || "";
        
        return `
            <tr>
                <td>
                    <strong style="color: #fff; font-size: 13px;">${f.institution_name}</strong>
                    ${mobile ? `
                    <div style="font-size: 11.5px; color: #38bdf8; margin-top: 2px; display: flex; align-items: center; gap: 4px;">
                        <i class="fas fa-mobile-screen"></i> <code>${mobile}</code>
                    </div>` : ''}
                </td>
                <td>
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <a href="${formUrl}" target="_blank" style="color: #38bdf8; font-weight: 600; text-decoration: none; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;">
                            <i class="fas fa-arrow-up-right-from-square"></i> Open Form
                        </a>
                        <button class="btn btn-secondary btn-sm" style="padding: 2px 6px; font-size: 10.5px;" onclick="copyTextToClipboard('${formUrl}')" title="লিংক কপি করুন">
                            <i class="fas fa-copy"></i>
                        </button>
                    </div>
                </td>
                <td>
                    ${sheetUrl ? `
                    <a href="${sheetUrl}" target="_blank" style="color: #34d399; font-weight: 600; text-decoration: none; font-size: 12px; display: inline-flex; align-items: center; gap: 4px;">
                        <i class="fas fa-table"></i> Google Sheet
                    </a>` : `<span style="color: var(--text-dim); font-size: 11px;">Not Linked</span>`}
                </td>
                <td>
                    <span class="badge" style="background: rgba(99, 102, 241, 0.2); color: #818cf8; font-weight: 700; font-size: 12px; padding: 3px 8px;">
                        ${f.submission_count || 0} জন
                    </span>
                </td>
                <td style="font-size: 11px; color: var(--text-dim);">
                    ${f.last_synced_at ? f.last_synced_at.slice(0, 16) : 'Never'}
                </td>
                <td>
                    <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                        <button class="btn btn-primary btn-sm" style="padding: 4px 8px; font-size: 11px;" onclick="viewFormSubmissions('${f.form_id}', '${f.institution_name}')" title="রেসপন্স দেখুন">
                            <i class="fas fa-users"></i> Submissions
                        </button>
                        <button class="btn btn-secondary btn-sm" style="padding: 4px 8px; font-size: 11px;" onclick="syncInstitutionForm('${f.form_id}')" title="ডাটা সিঙ্ক করুন">
                            <i class="fas fa-rotate"></i> Sync
                        </button>
                        <button class="btn btn-sm" style="background: rgba(37, 211, 102, 0.2); color: #4ade80; border: 1px solid rgba(37, 211, 102, 0.4); padding: 4px 8px; font-size: 11px;" onclick="openSendFormWhatsAppModal('${f.form_id}', '${f.institution_name}', '${formUrl}')" title="WhatsApp এ পাঠান">
                            <i class="fab fa-whatsapp"></i> Send
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

function filterFormsByMobile(query) {
    const q = (query || "").trim().toLowerCase();
    if (!q) {
        renderGeneratedFormsRows(allGeneratedFormsCache);
        return;
    }
    const filtered = allGeneratedFormsCache.filter(f => {
        const phone = (f.institution_mobile || f.institution_phone || "").toLowerCase();
        const name = (f.institution_name || "").toLowerCase();
        return phone.includes(q) || name.includes(q);
    });
    renderGeneratedFormsRows(filtered);
}

function clearFormsSearch() {
    const searchInput = document.getElementById("gforms-search-mobile");
    if (searchInput) searchInput.value = "";
    renderGeneratedFormsRows(allGeneratedFormsCache);
}

async function loadGeneratedFormsList() {
    try {
        const res = await fetch(`/api/google/forms?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        allGeneratedFormsCache = data.forms || [];
        
        const searchInput = document.getElementById("gforms-search-mobile");
        if (searchInput && searchInput.value.trim()) {
            filterFormsByMobile(searchInput.value);
        } else {
            renderGeneratedFormsRows(allGeneratedFormsCache);
        }
    } catch (e) {
        console.error("loadGeneratedFormsList error:", e);
    }
}

// ============================================================
// 5-STEP INSTITUTION GOOGLE FORM GENERATOR WIZARD
// ============================================================
let wizardCurrentStep = 1;
let wizardStandardFields = [];
let wizardSelectedKeys = new Set(["student_name", "father_name", "class_name", "roll", "student_photo"]);
let wizardAllowDuplicate = false;
let wizardCreatedForm = null;
let wizardMobileSearchTimeout = null;

async function loadWizardStandardFields() {
    if (wizardStandardFields.length > 0) return;
    try {
        const res = await fetch("/api/google/fields/standard");
        const data = await res.json();
        if (data.success && data.fields) {
            wizardStandardFields = data.fields;
        }
    } catch (e) {
        console.error("Failed to load standard fields:", e);
        // Fallback standard catalog
        wizardStandardFields = [
            { key: "student_name", label: "শিক্ষার্থীর নাম", type: "short_answer", required: true },
            { key: "father_name", label: "পিতার নাম", type: "short_answer", required: true },
            { key: "mother_name", label: "মাতার নাম", type: "short_answer", required: false },
            { key: "dob", label: "জন্মতারিখ", type: "date", required: false },
            { key: "class_name", label: "শ্রেণি", type: "short_answer", required: true },
            { key: "section", label: "শাখা", type: "short_answer", required: false },
            { key: "roll", label: "রোল", type: "short_answer", required: true },
            { key: "reg_no", label: "রেজিস্ট্রেশন নম্বর", type: "short_answer", required: false },
            { key: "blood_group", label: "রক্তের গ্রুপ", type: "dropdown", required: false },
            { key: "student_phone", label: "শিক্ষার্থীর মোবাইল", type: "short_answer", required: false },
            { key: "guardian_phone", label: "অভিভাবকের মোবাইল", type: "short_answer", required: false },
            { key: "address", label: "ঠিকানা", type: "paragraph", required: false },
            { key: "student_photo", label: "ছবি", type: "file_upload", required: true },
            { key: "student_signature", label: "স্বাক্ষর", type: "file_upload", required: false }
        ];
    }
}

function renderWizardFieldsGrid() {
    const container = document.getElementById("wizard-fields-grid");
    if (!container) return;
    container.innerHTML = "";

    wizardStandardFields.forEach(f => {
        const isChecked = wizardSelectedKeys.has(f.key);
        const card = document.createElement("label");
        card.style.cssText = `
            display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 6px;
            background: ${isChecked ? "rgba(99, 102, 241, 0.18)" : "rgba(255,255,255,0.03)"};
            border: 1px solid ${isChecked ? "rgba(99, 102, 241, 0.5)" : "rgba(255,255,255,0.08)"};
            cursor: pointer; transition: all 0.2s; user-select: none;
        `;
        card.innerHTML = `
            <input type="checkbox" value="${f.key}" ${isChecked ? "checked" : ""} onchange="toggleWizardField('${f.key}')" style="cursor: pointer; accent-color: #6366f1;">
            <span style="font-size: 12px; color: ${isChecked ? "#fff" : "var(--text-muted);"}; font-weight: ${isChecked ? "600" : "normal"};">
                ${f.label} ${f.type === 'file_upload' ? '<i class="fas fa-camera" style="color: #38bdf8; font-size: 10px;"></i>' : ''}
            </span>
        `;
        container.appendChild(card);
    });
}

function toggleWizardField(key) {
    if (wizardSelectedKeys.has(key)) {
        wizardSelectedKeys.delete(key);
    } else {
        wizardSelectedKeys.add(key);
    }
    renderWizardFieldsGrid();
}

function wizardSelectAllFields(selectAll) {
    if (selectAll) {
        wizardStandardFields.forEach(f => wizardSelectedKeys.add(f.key));
    } else {
        wizardSelectedKeys.clear();
    }
    renderWizardFieldsGrid();
}

function wizardSelectDefaultFields() {
    wizardSelectedKeys = new Set(["student_name", "father_name", "class_name", "roll", "student_photo"]);
    renderWizardFieldsGrid();
}

function showWizardStep(step) {
    wizardCurrentStep = step;

    // Update Top Step Pills
    for (let i = 1; i <= 5; i++) {
        const pill = document.getElementById(`wstep-tab-${i}`);
        if (pill) {
            if (i === step) {
                pill.style.color = "#38bdf8";
                pill.style.fontWeight = "bold";
                const numSpan = pill.querySelector("span");
                if (numSpan) {
                    numSpan.style.background = "#38bdf8";
                    numSpan.style.color = "#0f172a";
                }
            } else if (i < step) {
                pill.style.color = "#34d399";
                pill.style.fontWeight = "600";
                const numSpan = pill.querySelector("span");
                if (numSpan) {
                    numSpan.style.background = "#34d399";
                    numSpan.style.color = "#0f172a";
                }
            } else {
                pill.style.color = "var(--text-dim)";
                pill.style.fontWeight = "normal";
                const numSpan = pill.querySelector("span");
                if (numSpan) {
                    numSpan.style.background = "rgba(255,255,255,0.1)";
                    numSpan.style.color = "#fff";
                }
            }
        }
        const view = document.getElementById(`wizard-view-step-${i}`);
        if (view) view.style.display = (i === step) ? "block" : "none";
    }

    // Update Footer Buttons
    const btnCancel = document.getElementById("btn-wiz-cancel");
    const btnPrev = document.getElementById("btn-wiz-prev");
    const btnStep1Next = document.getElementById("btn-wiz-step1-next");
    const btnStep2Next = document.getElementById("btn-wiz-step2-next");
    const btnConfirm = document.getElementById("btn-wiz-create-confirm");
    const btnWa = document.getElementById("btn-wiz-succ-wa");
    const btnDone = document.getElementById("btn-wiz-succ-done");

    if (btnCancel) btnCancel.style.display = (step === 1) ? "inline-block" : "none";
    if (btnPrev) btnPrev.style.display = (step === 2 || step === 3) ? "inline-block" : "none";
    if (btnStep1Next) btnStep1Next.style.display = (step === 1) ? "inline-block" : "none";
    if (btnStep2Next) btnStep2Next.style.display = (step === 2) ? "inline-block" : "none";
    if (btnConfirm) btnConfirm.style.display = (step === 3) ? "inline-block" : "none";
    if (btnWa) btnWa.style.display = (step === 5) ? "inline-block" : "none";
    if (btnDone) btnDone.style.display = (step === 5) ? "inline-block" : "none";
}

async function openCreateInstitutionFormModal() {
    // Reset state
    wizardCurrentStep = 1;
    wizardAllowDuplicate = false;
    wizardCreatedForm = null;
    wizardSelectedKeys = new Set(["student_name", "father_name", "class_name", "roll", "student_photo"]);

    // Reset fields
    const nameInp = document.getElementById("wiz-inst-name");
    const phoneInp = document.getElementById("wiz-inst-phone");
    const descInp = document.getElementById("wiz-inst-desc");
    const natInp = document.getElementById("wiz-natural-text");
    const dupBox = document.getElementById("wiz-dup-institution-box");

    if (nameInp) nameInp.value = "";
    if (phoneInp) phoneInp.value = "";
    if (descInp) descInp.value = "";
    if (natInp) natInp.value = "";
    if (dupBox) dupBox.style.display = "none";

    await loadWizardStandardFields();
    renderWizardFieldsGrid();
    showWizardStep(1);
    openModal("modal-create-institution-form");
}

function handleWizardMobileChange(val) {
    if (wizardMobileSearchTimeout) clearTimeout(wizardMobileSearchTimeout);
    const cleanVal = (val || "").trim();
    if (cleanVal.length < 7) {
        document.getElementById("wiz-dup-institution-box").style.display = "none";
        return;
    }

    wizardMobileSearchTimeout = setTimeout(async () => {
        try {
            const res = await fetch(`/api/google/institutions/search?mobile=${encodeURIComponent(cleanVal)}&workspace_id=${currentWorkspaceId}`);
            const data = await res.json();
            const dupBox = document.getElementById("wiz-dup-institution-box");
            const dupMsg = document.getElementById("wiz-dup-msg");

            if (data.success && (data.institution || (data.forms && data.forms.length > 0))) {
                const instName = data.institution?.name || data.forms?.[0]?.institution_name || "বিদ্যমান প্রতিষ্ঠান";
                const formCount = data.forms ? data.forms.length : 1;
                dupMsg.innerText = `'${instName}' (${cleanVal}) নামে ইতোমধ্যে ${formCount}টি গুগল ফর্ম ডাটাবেজে রয়েছে।`;
                dupBox.style.display = "block";
            } else {
                dupBox.style.display = "none";
            }
        } catch (e) {
            console.error("Duplicate mobile check error:", e);
        }
    }, 400);
}

function handleUseExistingInstitution() {
    showToast("পূর্বের তৈরি প্রতিষ্ঠানের তালিকা দেখতে ড্যাশবোর্ডের সার্চ বার ব্যবহার করুন।", "info");
    closeModal("modal-create-institution-form");
}

function handleAllowNewFormForExisting() {
    wizardAllowDuplicate = true;
    document.getElementById("wiz-dup-institution-box").style.display = "none";
    showToast("নতুন গুগল ফর্ম তৈরির মোড সক্রিয় হয়েছে।", "success");
    wizardStep1Next();
}

function wizardStep1Next() {
    const instName = document.getElementById("wiz-inst-name")?.value?.trim();
    const phone = document.getElementById("wiz-inst-phone")?.value?.trim();

    if (!instName) {
        showToast("প্রতিষ্ঠানের নাম প্রদান করা বাধ্যতামূলক", "warning");
        document.getElementById("wiz-inst-name")?.focus();
        return;
    }
    if (!phone) {
        showToast("প্রতিষ্ঠানের মোবাইল নম্বর প্রদান করা বাধ্যতামূলক", "warning");
        document.getElementById("wiz-inst-phone")?.focus();
        return;
    }

    showWizardStep(2);
}

function wizardStep2Next() {
    if (wizardSelectedKeys.size === 0) {
        showToast("কমপক্ষে একটি তথ্য বা ফিল্ড নির্বাচন করুন", "warning");
        return;
    }

    // Populate Step 3 Preview
    const instName = document.getElementById("wiz-inst-name")?.value?.trim();
    const phone = document.getElementById("wiz-inst-phone")?.value?.trim();

    document.getElementById("wiz-preview-inst-name").innerText = instName;
    document.getElementById("wiz-preview-inst-phone").innerText = phone;

    const badgesContainer = document.getElementById("wiz-preview-badges-list");
    badgesContainer.innerHTML = "";

    const selectedList = wizardStandardFields.filter(f => wizardSelectedKeys.has(f.key));
    selectedList.forEach(f => {
        const badge = document.createElement("span");
        badge.style.cssText = "background: rgba(99, 102, 241, 0.2); border: 1px solid #6366f1; color: #c7d2fe; padding: 4px 10px; border-radius: 20px; font-size: 11.5px; display: inline-flex; align-items: center; gap: 5px; font-weight: 600;";
        badge.innerHTML = `<i class="fas fa-check" style="color: #34d399;"></i> ${f.label}`;
        badgesContainer.appendChild(badge);
    });

    showWizardStep(3);
}

function wizardGoPrev() {
    if (wizardCurrentStep === 2) {
        showWizardStep(1);
    } else if (wizardCurrentStep === 3) {
        showWizardStep(2);
    }
}

async function wizardDetectFieldsAI() {
    const text = document.getElementById("wiz-natural-text")?.value?.trim();
    if (!text) {
        showToast("কী কী তথ্য লাগবে তা সংক্ষেপে লিখে বলুন", "warning");
        return;
    }

    showToast("AI তথ্য শনাক্ত করছে... অনুগ্রহ করে অপেক্ষা করুন", "info");

    try {
        const res = await fetch("/api/google/forms/preview-fields", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: currentWorkspaceId,
                text: text
            })
        });
        const data = await res.json();
        if (data.success && data.field_keys) {
            wizardSelectedKeys = new Set(data.field_keys);
            renderWizardFieldsGrid();
            showToast("AI সফলভাবে ফিল্ডগুলো শনাক্ত করেছে!", "success");
            wizardStep2Next();
        } else {
            showToast("AI ফিল্ড শনাক্তকরণ ব্যর্থ হয়েছে। ম্যানুয়ালি চেক করুন।", "danger");
        }
    } catch (e) {
        showToast("AI সার্ভিস সংযোগে সমস্যা হয়েছে", "danger");
    }
}

async function executeWizardFormGeneration() {
    const instName = document.getElementById("wiz-inst-name")?.value?.trim();
    const phone = document.getElementById("wiz-inst-phone")?.value?.trim();
    const desc = document.getElementById("wiz-inst-desc")?.value?.trim();
    const selectedKeys = Array.from(wizardSelectedKeys);

    showWizardStep(4);

    // Live progress tick animation helper
    const updateProgressStep = (stepNum, text, isDone) => {
        const elem = document.getElementById(`wp-step-${stepNum}`);
        if (elem) {
            if (isDone) {
                elem.style.color = "#34d399";
                elem.innerHTML = `<i class="fas fa-check-circle"></i> ${text}`;
            } else {
                elem.style.color = "#38bdf8";
                elem.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${text}`;
            }
        }
    };

    setTimeout(() => updateProgressStep(1, "মাস্টার ফর্ম ক্লোন সম্পন্ন", true), 600);
    setTimeout(() => updateProgressStep(2, "ফিল্ড কনফিগারেশন প্রয়োগ সম্পন্ন", true), 1200);
    setTimeout(() => updateProgressStep(3, "গুগল শিট তৈরি সম্পন্ন", true), 1800);
    setTimeout(() => updateProgressStep(4, "ড্রাইভ ফোল্ডার সাজানো সম্পন্ন", true), 2400);
    setTimeout(() => updateProgressStep(5, "File Upload (ছবি) প্রশ্ন যাচাই সম্পন্ন", true), 2900);

    try {
        const res = await fetch("/api/google/forms/create", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: currentWorkspaceId,
                institution_name: instName,
                institution_mobile: phone,
                institution_phone: phone,
                custom_description: desc,
                selected_fields: selectedKeys,
                allow_duplicate: wizardAllowDuplicate
            })
        });

        const data = await res.json();
        if (res.ok && data.success) {
            wizardCreatedForm = data;
            
            // Populate Success Screen
            document.getElementById("wiz-succ-name").innerText = data.institution_name || instName;
            document.getElementById("wiz-succ-phone").innerText = data.institution_mobile || phone;
            
            const formLink = document.getElementById("wiz-succ-form-url");
            const sheetLink = document.getElementById("wiz-succ-sheet-url");

            if (formLink) formLink.href = data.responder_url || data.form_url || "#";
            if (sheetLink) sheetLink.href = data.sheet_url || "#";

            showWizardStep(5);
            showToast(`'${instName}' এর Google Form সফলভাবে তৈরি হয়েছে!`, "success");
            loadGeneratedFormsList();
        } else {
            showToast(data.detail || data.error || "গুগল ফর্ম তৈরিতে সমস্যা হয়েছে।", "danger");
            showWizardStep(3);
        }
    } catch (e) {
        showToast("Network error creating Google Form", "danger");
        showWizardStep(3);
    }
}

function copyWizardFormUrl() {
    if (!wizardCreatedForm) return;
    const url = wizardCreatedForm.responder_url || wizardCreatedForm.form_url;
    if (url) {
        navigator.clipboard.writeText(url).then(() => {
            showToast("গুগল ফর্মের লিংক ক্লিপবোর্ডে কপি হয়েছে!", "success");
        });
    }
}

function wizardSendFormWhatsApp() {
    if (!wizardCreatedForm) return;
    closeModal("modal-create-institution-form");
    openSendFormWhatsAppModal(
        wizardCreatedForm.form_id,
        wizardCreatedForm.institution_name,
        wizardCreatedForm.responder_url || wizardCreatedForm.form_url
    );
}

function openSendFormWhatsAppModal(formId, instName, formUrl) {
    document.getElementById("wa-send-form-id").value = formId;
    document.getElementById("wa-send-inst-name").value = instName;
    document.getElementById("wa-send-phone").value = "";
    
    const defaultMsg = `আসসালামু আলাইকুম।\n\n*${instName}* এর আইডি কার্ড (ID Card) তথ্য ও ছবি সংগ্রহের জন্য গুগল ফর্ম প্রস্তুত করা হয়েছে।\n\n📝 ফর্ম লিংক:\n${formUrl}\n\nঅনুগ্রহ করে শিক্ষার্থীদের সঠিক তথ্য ও ছবি আপলোড করুন।`;
    document.getElementById("wa-send-message").value = defaultMsg;

    openModal("modal-send-form-whatsapp");
}

async function handleSendFormWhatsApp(e) {
    e.preventDefault();
    const formId = document.getElementById("wa-send-form-id")?.value;
    const phone = document.getElementById("wa-send-phone")?.value?.trim();
    const message = document.getElementById("wa-send-message")?.value?.trim();

    if (!phone) {
        showToast("গ্রাহকের WhatsApp নম্বর দিন", "warning");
        return;
    }

    try {
        const res = await fetch(`/api/google/forms/${formId}/send-whatsapp`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                workspace_id: currentWorkspaceId,
                recipient_phone: phone,
                custom_message: message
            })
        });
        const data = await res.json();
        if (data.success) {
            showToast("WhatsApp এ ফর্ম লিংক সফলভাবে পাঠানো হয়েছে!", "success");
            closeModal("modal-send-form-whatsapp");
        } else {
            showToast(data.error || "WhatsApp পাঠানো সম্ভব হয়নি", "danger");
        }
    } catch (err) {
        showToast("WhatsApp send error", "danger");
    }
}

async function syncInstitutionForm(formId) {
    showToast("রেসপন্স সিঙ্ক হচ্ছে...", "info");
    try {
        const res = await fetch(`/api/google/forms/${formId}/sync?workspace_id=${currentWorkspaceId}`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
            showToast(`সিঙ্ক সম্পন্ন! মোট রেসপন্স: ${data.total_submissions} (নতুন: ${data.new_submissions_imported})`, "success");
            loadGeneratedFormsList();
        } else {
            showToast(data.error || "সিঙ্ক ব্যর্থ হয়েছে", "danger");
        }
    } catch (e) {
        showToast("Sync network error", "danger");
    }
}

async function viewFormSubmissions(formId, instName) {
    currentOpenSubmissionsFormId = formId;
    const titleEl = document.getElementById("subs-modal-title");
    if (titleEl) titleEl.innerText = `${instName} - শিক্ষার্থীদের সাবমিশন তালিকা`;

    const tbody = document.getElementById("subs-modal-tbody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 20px;"><i class="fas fa-spinner fa-spin"></i> ডাটা লোড হচ্ছে...</td></tr>`;
    
    openModal("modal-view-submissions");

    try {
        const res = await fetch(`/api/google/forms/${formId}/responses?workspace_id=${currentWorkspaceId}`);
        const data = await res.json();
        if (!tbody) return;

        if (!data.submissions || data.submissions.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 25px;">এখনো কোনো শিক্ষার্থী ফর্ম পূরণ করেনি। 'Sync Responses' বাটনে চাপ দিয়ে লাইভ ডাটা চেক করতে পারেন।</td></tr>`;
            return;
        }

        tbody.innerHTML = data.submissions.map(s => {
            const photoUrl = s.photo_drive_url || s.photo_thumbnail_url;
            const photoHtml = photoUrl ? `
                <a href="${photoUrl}" target="_blank" title="ছবি দেখুন">
                    <img src="${photoUrl}" style="width: 42px; height: 42px; object-fit: cover; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15);" onerror="this.onerror=null;this.src='/static/img/photo_placeholder.png';">
                </a>
            ` : `<span style="font-size: 11px; color: var(--text-dim);">No Photo</span>`;

            return `
                <tr>
                    <td>${photoHtml}</td>
                    <td><strong style="color: #fff;">${s.student_name || 'N/A'}</strong></td>
                    <td><span class="badge" style="background: rgba(255,255,255,0.06);">${s.student_roll || '-'}</span></td>
                    <td>${s.student_class || '-'}</td>
                    <td>${s.student_phone || '-'}</td>
                    <td style="font-size: 11px; color: var(--text-dim);">${s.submission_timestamp ? s.submission_timestamp.slice(0, 16) : '-'}</td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #f87171; padding: 20px;">ডাটা লোড করতে সমস্যা হয়েছে।</td></tr>`;
    }
}

async function syncCurrentOpenFormSubmissions() {
    if (!currentOpenSubmissionsFormId) return;
    await syncInstitutionForm(currentOpenSubmissionsFormId);
    viewFormSubmissions(currentOpenSubmissionsFormId, "Institution");
}

function copyTextToClipboard(text) {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        showToast("লিংক ক্লিপবোর্ডে কপি করা হয়েছে!", "success");
    }).catch(() => {
        showToast("কপি করা সম্ভব হয়নি", "warning");
    });
}




